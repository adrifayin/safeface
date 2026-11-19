"""Diagnostic: run every applicable module on stored evidence and print the scores.

Run inside a worker container (read-only, nothing is recorded in the case):
    python /app/scripts/diagnose_item.py <filename-substring> [...]
Pulls the sealed original to a temporary directory, verifies its SHA-256, runs the
modules, prints one line per score, and deletes the temporary copy.
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.hashing import hash_file
from app.core.storage import get_store
from app.db.models import EvidenceItem
from app.db.session import session_scope
from app.modules.base import MediaType, WorkingCopy
from app.modules.registry import all_modules

SKIP = {"integrity.hash", "image.source_match"}  # need references / covered elsewhere


def main(patterns: list[str]) -> None:
    store = get_store()
    with session_scope() as s:
        items = [(e.id, e.original_filename, e.media_type, e.storage_key, e.storage_version_id, e.sha256, e.md5)
                 for e in s.execute(select(EvidenceItem)).scalars()
                 if any(p.lower() in e.original_filename.lower() for p in patterns)]
    for eid, name, mt, key, ver, sha, md5 in items:
        print(f"\n=== {name[:70]} ({mt})")
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            dest = t / f"item{Path(name).suffix.lower()}"
            store.download_to(get_settings().bucket_originals, key, dest)
            if hash_file(dest).sha256 != sha:
                print("  HASH MISMATCH - skipped")
                continue
            for m in all_modules().values():
                if m.id in SKIP or MediaType(mt) not in m.media_types or not m.availability().available:
                    continue
                out = t / m.id
                out.mkdir()
                wc = WorkingCopy(str(eid), dest, sha, md5, MediaType(mt), name, "questioned", sha, md5, out)
                t0 = time.time()
                try:
                    f = m.run(wc, [], m.merged_params({}))
                except Exception as exc:  # noqa: BLE001
                    print(f"  {m.id:26s} ERROR {exc.__class__.__name__}: {exc}")
                    continue
                sc = ", ".join(f"{x.name}={x.value:.3f}" for x in f.scores if x.value is not None)
                print(f"  {m.id:26s} {time.time() - t0:5.1f}s  {sc}")
                print(f"  {'':26s}        -> {f.summary[:160]}")


if __name__ == "__main__":
    main(sys.argv[1:] or ["gemini", "High-angle", "WhatsApp"])
