"""Audit log access and chain verification (FR-6.2, NFR-S5)."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.deps import DB, Me, require
from app.api.schemas import AuditEntryOut, AuditVerifyOut
from app.core import audit
from app.core.canonical import canonical_json
from app.core.policy import Action
from app.core.timeutil import iso, utcnow
from app.db.models import AuditLog
from app.db.session import session_scope

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/verify", response_model=AuditVerifyOut)
def verify(db: DB, me: Me) -> AuditVerifyOut:
    require(me, Action.AUDIT_VERIFY)
    result = audit.verify_chain(db)
    audit.record(db, me.actor, "audit.verified", "audit", "chain", {
        "ok": result.ok, "entries_checked": result.entries_checked,
        "head_hash": result.head_hash, "first_bad_seq": result.first_bad_seq,
    })
    return AuditVerifyOut(**result.__dict__, verified_at=utcnow())


@router.get("/entries", response_model=list[AuditEntryOut])
def entries(
    db: DB, me: Me,
    after_seq: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    target_id: str | None = None,
) -> list[AuditEntryOut]:
    require(me, Action.AUDIT_VIEW)
    q = select(AuditLog).where(AuditLog.seq > after_seq).order_by(AuditLog.seq).limit(limit)
    if target_id:
        q = q.where(AuditLog.target_id == target_id)
    return [AuditEntryOut.model_validate(r) for r in db.execute(q).scalars()]


@router.get("/export")
def export(db: DB, me: Me) -> StreamingResponse:
    """Export the full chain as JSON Lines for court or offline verification."""
    require(me, Action.AUDIT_VIEW)
    audit.record(db, me.actor, "audit.exported", "audit", "chain")
    db.commit()

    def rows() -> Iterator[bytes]:
        with session_scope() as s:
            for r in s.execute(select(AuditLog).order_by(AuditLog.seq)).scalars().yield_per(1000):
                yield canonical_json({
                    "seq": r.seq, "ts": iso(r.ts), "actor": r.actor, "action": r.action,
                    "target_type": r.target_type, "target_id": r.target_id,
                    "details": r.details, "prev_hash": r.prev_hash, "entry_hash": r.entry_hash,
                }) + b"\n"

    return StreamingResponse(rows(), media_type="application/x-ndjson", headers={
        "Content-Disposition": 'attachment; filename="safeface-audit.jsonl"',
    })
