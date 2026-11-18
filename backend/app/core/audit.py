"""Append-only, hash-chained audit log.

    entry_hash = SHA-256( prev_hash || canonical_json(entry) )

where ``entry`` = {seq, ts, actor, action, target_type, target_id, details} and
the first entry uses a prev_hash of 64 zeros. Any edit, deletion, insertion or
reordering of rows breaks the chain and is reported by :func:`verify_chain`.

Writers serialise on a PostgreSQL advisory lock held for the rest of the
transaction, so ``seq`` is gap-free and the chain is linear. Because the
audit entry is written in the same transaction as the state change it
describes, a change can never commit without its audit entry (and vice versa).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.canonical import canonical_json, normalise
from app.core.timeutil import iso, utcnow
from app.db.models import AuditLog

GENESIS_HASH = "0" * 64
# Arbitrary constant identifying the audit-chain advisory lock.
AUDIT_LOCK_KEY = 0x5AFEFACE
SYSTEM_ACTOR = "system"


def entry_payload(
    seq: int,
    ts: datetime,
    actor: str,
    action: str,
    target_type: str,
    target_id: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    return {
        "seq": seq,
        "ts": iso(ts),
        "actor": actor,
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "details": details,
    }


def compute_entry_hash(prev_hash: str, payload: dict[str, Any]) -> str:
    return hashlib.sha256(prev_hash.encode("ascii") + canonical_json(payload)).hexdigest()


def record(
    session: Session,
    actor: str,
    action: str,
    target_type: str,
    target_id: object,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    """Append one entry. Must be called inside the transaction of the change."""
    session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": AUDIT_LOCK_KEY})
    last = session.execute(
        select(AuditLog.seq, AuditLog.entry_hash).order_by(AuditLog.seq.desc()).limit(1)
    ).first()
    seq = (last.seq + 1) if last else 1
    prev_hash = last.entry_hash if last else GENESIS_HASH
    ts = utcnow()
    clean_details = normalise(details or {})
    payload = entry_payload(seq, ts, actor, action, target_type, str(target_id), clean_details)
    row = AuditLog(
        seq=seq,
        ts=ts,
        actor=actor,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        details=clean_details,
        prev_hash=prev_hash,
        entry_hash=compute_entry_hash(prev_hash, payload),
    )
    session.add(row)
    session.flush()
    return row


@dataclass(frozen=True)
class ChainVerification:
    ok: bool
    entries_checked: int
    head_seq: int
    head_hash: str
    first_bad_seq: int | None
    problem: str | None


def verify_rows(rows: Any) -> ChainVerification:
    """Verify an ordered iterable of rows with the AuditLog attributes."""
    prev_hash = GENESIS_HASH
    expected_seq = 1
    count = 0
    for row in rows:
        count += 1
        if row.seq != expected_seq:
            return ChainVerification(
                False, count, row.seq, prev_hash, expected_seq,
                f"sequence gap: expected {expected_seq}, found {row.seq} (entry deleted?)",
            )
        if row.prev_hash != prev_hash:
            return ChainVerification(
                False, count, row.seq, prev_hash, row.seq, "prev_hash does not match previous entry"
            )
        payload = entry_payload(
            row.seq, row.ts, row.actor, row.action, row.target_type, row.target_id, row.details
        )
        if compute_entry_hash(prev_hash, payload) != row.entry_hash:
            return ChainVerification(
                False, count, row.seq, prev_hash, row.seq, "entry content does not match its hash"
            )
        prev_hash = row.entry_hash
        expected_seq += 1
    return ChainVerification(True, count, expected_seq - 1, prev_hash, None, None)


def verify_chain(session: Session) -> ChainVerification:
    rows = session.execute(select(AuditLog).order_by(AuditLog.seq)).scalars()
    return verify_rows(rows.yield_per(1000))
