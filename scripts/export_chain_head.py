"""Write the current audit-chain head to write-once storage (TDD §5 "Log tampering").

Run daily (host cron / systemd timer) inside the API container:
  docker compose -f infra/docker-compose.yml exec api python /app/scripts/export_chain_head.py
It verifies the chain, then stores {date, head_seq, head_hash, entries} as an
object-locked record in the evidence-originals bucket under audit-heads/.
Also print it, so the operator can copy it to a second write-once medium
(e.g. a WORM USB or a signed paper log).
"""

from __future__ import annotations

import json
import sys

sys.path.insert(0, "/app")

from app.core import audit  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.storage import get_store  # noqa: E402
from app.core.timeutil import iso, utcnow  # noqa: E402
from app.db.session import session_scope  # noqa: E402


def main() -> int:
    with session_scope() as s:
        result = audit.verify_chain(s)
        record = {"exported_at": iso(utcnow()), "ok": result.ok, "head_seq": result.head_seq,
                  "head_hash": result.head_hash, "entries": result.entries_checked,
                  "problem": result.problem}
        audit.record(s, "system (chain-head export)", "audit.head_exported", "audit", "chain", record)
    key = f"audit-heads/{record['exported_at'][:10]}-{record['head_seq']}.json"
    get_store().put_bytes(get_settings().bucket_originals, key, json.dumps(record).encode(), "application/json")
    print(json.dumps(record))
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
