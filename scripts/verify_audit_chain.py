#!/usr/bin/env python3
"""Independently verify an exported SafeFace audit chain (JSON Lines).

Deliberately self-contained: it uses only the Python standard library and does
NOT import any SafeFace code, so a third party (e.g. a defence expert) can
check the chain with nothing but this ~60-line file and the export.

Rule checked for every entry, in sequence order:
    entry_hash == SHA-256( prev_hash || canonical_json({seq, ts, actor, action,
                                                       target_type, target_id, details}) )
with prev_hash of the first entry = 64 zeros, consecutive seq numbers, and
canonical JSON = UTF-8, sorted keys, separators (",", ":"), no ASCII escaping.

Usage:
    python verify_audit_chain.py safeface-audit.jsonl [--expected-head <hash>]
Get the export from GET /api/v1/audit/export (supervisor or auditor).
--expected-head compares the final hash with a head recorded earlier on
write-once media (detects truncation of the most recent entries).
Exit status 0 = intact, 1 = broken.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys

GENESIS = "0" * 64
FIELDS = ("seq", "ts", "actor", "action", "target_type", "target_id", "details")


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("export")
    ap.add_argument("--expected-head")
    args = ap.parse_args()
    prev, expected_seq, count = GENESIS, 1, 0
    with open(args.export, encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            count += 1
            if row["seq"] != expected_seq:
                print(f"BROKEN at line {line_no}: expected seq {expected_seq}, found {row['seq']} (entry missing?)")
                return 1
            if row["prev_hash"] != prev:
                print(f"BROKEN at seq {row['seq']}: prev_hash does not link to the previous entry")
                return 1
            payload = {k: row[k] for k in FIELDS}
            digest = hashlib.sha256(prev.encode("ascii") + canonical(payload)).hexdigest()
            if digest != row["entry_hash"]:
                print(f"BROKEN at seq {row['seq']}: content does not match its hash (entry altered)")
                return 1
            prev, expected_seq = row["entry_hash"], expected_seq + 1
    if args.expected_head and args.expected_head != prev:
        print(f"BROKEN: chain head {prev} differs from the expected head {args.expected_head} "
              "(entries removed from the end, or wrong export)")
        return 1
    print(f"INTACT: {count} entries verified; head seq {expected_seq - 1}, head hash {prev}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
