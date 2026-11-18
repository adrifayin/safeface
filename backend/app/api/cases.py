"""Cases and case membership (SRS FR-1.1)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DB, Me, load_case, membership, require
from app.api.schemas import CaseCreate, CaseDetail, CaseOut, MemberAdd, MemberOut
from app.api.serialise import evidence_out
from app.core import audit
from app.core.policy import Action, Role, default_membership, is_allowed
from app.db.models import Case, CaseMember, CasePermission, User

router = APIRouter(prefix="/cases", tags=["cases"])


@router.get("", response_model=list[CaseOut])
def list_cases(db: DB, me: Me) -> list[CaseOut]:
    if is_allowed(me.principal.roles, Action.CASE_LIST_ALL, None):
        cases = db.execute(select(Case).order_by(Case.created_at.desc())).scalars().all()
    else:
        if not is_allowed(me.principal.roles, Action.CASE_VIEW, CasePermission.VIEW):
            return []
        cases = db.execute(
            select(Case).join(CaseMember).where(CaseMember.user_id == me.id)
            .order_by(Case.created_at.desc())
        ).scalars().all()
    out = []
    for case in cases:
        item = CaseOut.model_validate(case)
        item.my_permission = membership(db, case.id, me.id)
        out.append(item)
    return out


@router.post("", response_model=CaseOut, status_code=status.HTTP_201_CREATED)
def create_case(body: CaseCreate, db: DB, me: Me) -> CaseOut:
    require(me, Action.CASE_CREATE)
    case = Case(
        case_no=body.case_no, fir_no=body.fir_no, crime_head=body.crime_head,
        investigating_officer=body.investigating_officer, description=body.description,
        created_by_id=me.id, assigned_examiner_id=body.assigned_examiner_id,
    )
    db.add(case)
    try:
        db.flush()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "case number already exists") from exc
    db.add(CaseMember(
        case_id=case.id, user_id=me.id, permission=default_membership(me.principal.roles),
        added_by_id=me.id,
    ))
    if body.assigned_examiner_id and body.assigned_examiner_id != me.id:
        examiner = db.get(User, body.assigned_examiner_id)
        if examiner is None or Role.EXAMINER.value not in examiner.roles:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "assigned examiner unknown")
        db.add(CaseMember(
            case_id=case.id, user_id=examiner.id, permission=CasePermission.ANALYSE,
            added_by_id=me.id,
        ))
    db.flush()
    audit.record(db, me.actor, "case.created", "case", case.id, body.model_dump(mode="json"))
    out = CaseOut.model_validate(case)
    out.my_permission = membership(db, case.id, me.id)
    return out


@router.get("/{case_id}", response_model=CaseDetail)
def get_case(case_id: uuid.UUID, db: DB, me: Me) -> CaseDetail:
    """Case metadata. Supervisors who assign cases may open it without being members
    (to add members); this never includes media, which still requires membership."""
    if membership(db, case_id, me.id) is None and is_allowed(me.principal.roles, Action.CASE_ASSIGN, None):
        found = db.get(Case, case_id)
        if found is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "case not found")
        case = found
        audit.record(db, me.actor, "case.viewed", "case", case.id, {"basis": "supervisor oversight (not a member)"})
    else:
        case = load_case(db, me, case_id, Action.CASE_VIEW)
        audit.record(db, me.actor, "case.viewed", "case", case.id)
    detail = CaseDetail.model_validate(case, from_attributes=True)
    detail.evidence = [evidence_out(db, e) for e in case.evidence]
    detail.members = [
        MemberOut(user_id=m.user_id, permission=m.permission, added_at=m.added_at,
                  username=m.user.username, display_name=m.user.display_name)
        for m in case.members
    ]
    detail.my_permission = membership(db, case.id, me.id)
    return detail


@router.post("/{case_id}/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
def add_member(case_id: uuid.UUID, body: MemberAdd, db: DB, me: Me) -> MemberOut:
    require(me, Action.CASE_ASSIGN)
    case = db.get(Case, case_id)
    user = db.get(User, body.user_id)
    if case is None or user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "case or user not found")
    if user.roles == [Role.ADMIN.value]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "administrators cannot join cases")
    existing = db.get(CaseMember, (case_id, user.id))
    if existing:
        existing.permission = body.permission
        row = existing
    else:
        row = CaseMember(case_id=case_id, user_id=user.id, permission=body.permission,
                         added_by_id=me.id)
        db.add(row)
    db.flush()
    audit.record(db, me.actor, "case.member_set", "case", case_id,
                 {"user_id": str(user.id), "username": user.username,
                  "permission": body.permission.value})
    return MemberOut(user_id=user.id, permission=row.permission, added_at=row.added_at,
                     username=user.username, display_name=user.display_name)
