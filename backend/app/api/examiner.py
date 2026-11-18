"""Examiner notes, conclusions and supervisor approval (FR-5.4, FR-5.5)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import DB, Me, forbid, load_evidence, membership
from app.api.schemas import (
    ConclusionApprove,
    ConclusionCreate,
    ConclusionOut,
    NoteCreate,
    NoteOut,
)
from app.api.serialise import conclusion_out
from app.core import audit
from app.core.policy import Action, role_allows
from app.core.timeutil import utcnow
from app.db.models import (
    CONCLUSION_LABELS,
    CaseMember,
    CasePermission,
    Conclusion,
    EvidenceItem,
    EvidenceKind,
    ExaminerNote,
    FindingRow,
)

router = APIRouter(tags=["examiner"])


@router.post("/evidence/{evidence_id}/notes", response_model=NoteOut,
             status_code=status.HTTP_201_CREATED)
def add_note(evidence_id: uuid.UUID, body: NoteCreate, db: DB, me: Me) -> NoteOut:
    item = load_evidence(db, me, evidence_id, Action.NOTE_WRITE)
    if body.finding_id:
        finding = db.get(FindingRow, body.finding_id)
        if finding is None or finding.evidence_id != item.id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "finding not on this item")
    note = ExaminerNote(evidence_id=item.id, finding_id=body.finding_id, author_id=me.id,
                        text=body.text)
    db.add(note)
    db.flush()
    audit.record(db, me.actor, "note.added", "evidence", item.id,
                 {"note_id": str(note.id), "finding_id": str(body.finding_id or ""),
                  "text": body.text})
    out = NoteOut.model_validate(note)
    out.author_name = me.user.display_name
    return out


@router.get("/evidence/{evidence_id}/notes", response_model=list[NoteOut])
def list_notes(evidence_id: uuid.UUID, db: DB, me: Me) -> list[NoteOut]:
    item = load_evidence(db, me, evidence_id, Action.EVIDENCE_VIEW)
    notes = db.execute(select(ExaminerNote).where(ExaminerNote.evidence_id == item.id)
                       .order_by(ExaminerNote.created_at)).scalars()
    out = []
    for n in notes:
        o = NoteOut.model_validate(n)
        o.author_name = n.author.display_name
        out.append(o)
    return out


@router.post("/evidence/{evidence_id}/conclusion", response_model=ConclusionOut,
             status_code=status.HTTP_201_CREATED)
def add_conclusion(evidence_id: uuid.UUID, body: ConclusionCreate, db: DB, me: Me) -> ConclusionOut:
    item = load_evidence(db, me, evidence_id, Action.CONCLUSION_WRITE)
    if item.kind != EvidenceKind.QUESTIONED:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "conclusions are recorded on questioned items")
    row = Conclusion(evidence_id=item.id, scale_value=body.scale_value.value,
                     rationale=body.rationale, author_id=me.id)
    db.add(row)
    db.flush()
    audit.record(db, me.actor, "conclusion.recorded", "evidence", item.id, {
        "conclusion_id": str(row.id), "scale_value": row.scale_value,
        "scale_label": CONCLUSION_LABELS[row.scale_value], "rationale": row.rationale,
    })
    db.refresh(row)
    return conclusion_out(db, row)


@router.get("/evidence/{evidence_id}/conclusions", response_model=list[ConclusionOut])
def list_conclusions(evidence_id: uuid.UUID, db: DB, me: Me) -> list[ConclusionOut]:
    item = load_evidence(db, me, evidence_id, Action.CASE_VIEW)
    rows = db.execute(select(Conclusion).where(Conclusion.evidence_id == item.id)
                      .order_by(Conclusion.created_at)).scalars()
    return [conclusion_out(db, r) for r in rows]


@router.get("/approvals/pending", response_model=list[ConclusionOut])
def pending_approvals(db: DB, me: Me) -> list[ConclusionOut]:
    """Unapproved conclusions in cases where the caller holds ``approve``.

    Role check only here; the query itself restricts rows to cases where the
    caller is a member with ``approve`` permission.
    """
    if not role_allows(me.principal.roles, Action.CONCLUSION_APPROVE):
        raise forbid()
    rows = db.execute(
        select(Conclusion)
        .join(EvidenceItem, EvidenceItem.id == Conclusion.evidence_id)
        .join(CaseMember, CaseMember.case_id == EvidenceItem.case_id)
        .where(CaseMember.user_id == me.id, CaseMember.permission == CasePermission.APPROVE,
               Conclusion.approved_at.is_(None))
        .order_by(Conclusion.created_at)
    ).scalars()
    return [conclusion_out(db, r) for r in rows]


@router.post("/conclusions/{conclusion_id}/approve", response_model=ConclusionOut)
def approve(conclusion_id: uuid.UUID, body: ConclusionApprove, db: DB, me: Me) -> ConclusionOut:
    row = db.get(Conclusion, conclusion_id, with_for_update=True)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conclusion not found")
    item = load_evidence(db, me, row.evidence_id, Action.CONCLUSION_APPROVE)
    if row.author_id == me.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "separation of duties: you cannot approve your own conclusion")
    if row.approved_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "already approved")
    latest = db.execute(select(Conclusion.id).where(Conclusion.evidence_id == item.id)
                        .order_by(Conclusion.created_at.desc()).limit(1)).scalar_one()
    if latest != row.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "a newer conclusion supersedes this one")
    assert membership(db, item.case_id, me.id) == CasePermission.APPROVE
    row.approved_by_id = me.id
    row.approved_at = utcnow()
    row.approval_comment = body.comment
    db.flush()
    audit.record(db, me.actor, "conclusion.approved", "evidence", item.id, {
        "conclusion_id": str(row.id), "scale_value": row.scale_value, "comment": body.comment,
    })
    db.refresh(row)
    return conclusion_out(db, row)
