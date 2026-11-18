"""Case closure and approved disposal of derived data (SRS FR-6.5, TDD §5 "Data retention").

- A supervisor closes a case (no new evidence, analyses or notes afterwards).
- A supervisor requests disposal, citing the retention order or court direction.
- A DIFFERENT supervisor approves or rejects (two-person rule).
- Approval deletes working copies and figures of every item and marks the case
  "disposed". Database records (hashes, findings, notes, conclusions, reports,
  audit) are retained as the record of what was done. Originals are under
  write-once object lock and can only be removed after the lock expires;
  the approval records each original's lock date.
Every step is written to the audit chain.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DB, Me, require
from app.core import audit
from app.core.config import get_settings
from app.core.policy import Action
from app.core.storage import get_store
from app.core.timeutil import utcnow
from app.db.models import Case, DisposalRequest, EvidenceItem
from app.services.retention import purge_work_files

router = APIRouter(tags=["disposal"])


class DisposalCreate(BaseModel):
    reason: str = Field(min_length=10, max_length=2000)
    authority: str = Field(min_length=5, max_length=512)


def _out(r: DisposalRequest) -> dict[str, Any]:
    return {"id": str(r.id), "case_id": str(r.case_id), "reason": r.reason, "authority": r.authority,
            "requested_by_id": str(r.requested_by_id), "requested_at": r.requested_at.isoformat(),
            "status": r.status, "decided_by_id": str(r.decided_by_id) if r.decided_by_id else None,
            "decided_at": r.decided_at.isoformat() if r.decided_at else None, "result": r.result}


@router.post("/cases/{case_id}/close")
def close_case(case_id: uuid.UUID, db: DB, me: Me) -> dict[str, str]:
    require(me, Action.CASE_CLOSE)
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "case not found")
    if case.status != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, f"case is already {case.status}")
    case.status = "closed"
    audit.record(db, me.actor, "case.closed", "case", case.id)
    return {"status": "closed"}


@router.get("/cases/{case_id}/disposals")
def list_disposals(case_id: uuid.UUID, db: DB, me: Me) -> list[dict[str, Any]]:
    require(me, Action.CASE_DISPOSE)
    rows = db.execute(select(DisposalRequest).where(DisposalRequest.case_id == case_id)
                      .order_by(DisposalRequest.requested_at)).scalars()
    return [_out(r) for r in rows]


@router.post("/cases/{case_id}/disposals", status_code=status.HTTP_201_CREATED)
def request_disposal(case_id: uuid.UUID, body: DisposalCreate, db: DB, me: Me) -> dict[str, Any]:
    require(me, Action.CASE_DISPOSE)
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "case not found")
    if case.status != "closed":
        raise HTTPException(status.HTTP_409_CONFLICT, "only a closed case can be disposed of")
    if db.execute(select(DisposalRequest).where(DisposalRequest.case_id == case_id,
                                                DisposalRequest.status == "pending")).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "a disposal request is already pending")
    row = DisposalRequest(case_id=case_id, reason=body.reason, authority=body.authority, requested_by_id=me.id,
                          result={})
    db.add(row)
    db.flush()
    audit.record(db, me.actor, "case.disposal_requested", "case", case_id,
                 {"request_id": str(row.id), "reason": body.reason, "authority": body.authority})
    return _out(row)


@router.post("/disposals/{request_id}/{decision}")
def decide_disposal(request_id: uuid.UUID, decision: str, db: DB, me: Me) -> dict[str, Any]:
    require(me, Action.CASE_DISPOSE)
    if decision not in ("approve", "reject"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown decision")
    row = db.get(DisposalRequest, request_id, with_for_update=True)
    if row is None or row.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "no pending disposal request with this id")
    if row.requested_by_id == me.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "two-person rule: the requester cannot decide")
    row.decided_by_id = me.id
    row.decided_at = utcnow()
    case = db.get(Case, row.case_id)
    assert case is not None
    if decision == "reject":
        row.status = "rejected"
        audit.record(db, me.actor, "case.disposal_rejected", "case", case.id, {"request_id": str(row.id)})
        return _out(row)
    s = get_settings()
    store = get_store()
    removed: list[str] = []
    originals: list[dict[str, Any]] = []
    for item in db.execute(select(EvidenceItem).where(EvidenceItem.case_id == case.id)).scalars():
        removed += purge_work_files(db, store, item, f"{me.actor} (approved disposal)")
        originals.append({"evidence_id": str(item.id), "sha256": item.sha256,
                          "lock": store.retention(s.bucket_originals, item.storage_key, item.storage_version_id)})
    row.status = "approved"
    row.result = {"derived_objects_deleted": len(removed), "originals": originals,
                  "note": "Originals remain under write-once lock until the date shown and can be removed only "
                          "after it expires. Database records are retained as the record of the case."}
    case.status = "disposed"
    audit.record(db, me.actor, "case.disposal_approved", "case", case.id,
                 {"request_id": str(row.id), "derived_objects_deleted": len(removed), "originals": originals})
    return _out(row)
