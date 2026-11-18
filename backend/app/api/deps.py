"""Request dependencies: DB session, authenticated user and authorisation helpers."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.policy import Action, is_allowed
from app.core.security import AuthError, JWKSCache, Principal, decode_token
from app.core.timeutil import utcnow
from app.db.models import Case, CaseMember, EvidenceItem, User
from app.db.session import get_sessionmaker

_bearer = HTTPBearer(auto_error=False)


def get_db() -> Iterator[Session]:
    """One transaction per request: committed only if the handler succeeds."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


DB = Annotated[Session, Depends(get_db)]


@lru_cache
def get_jwks() -> JWKSCache:
    s = get_settings()
    return JWKSCache(s.oidc_jwks_url, s.oidc_jwks_file)


@dataclass(frozen=True)
class CurrentUser:
    principal: Principal
    user: User

    @property
    def actor(self) -> str:
        return self.principal.actor

    @property
    def id(self) -> uuid.UUID:
        return self.user.id


def current_user(
    db: DB, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
) -> CurrentUser:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    try:
        principal = decode_token(creds.credentials, get_settings(), get_jwks())
    except AuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    user = db.execute(select(User).where(User.keycloak_sub == principal.sub)).scalar_one_or_none()
    roles = sorted(r.value for r in principal.roles)
    if user is None:
        user = User(
            keycloak_sub=principal.sub, username=principal.username,
            display_name=principal.display_name, roles=roles,
        )
        db.add(user)
    else:
        if not user.active:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "account deactivated")
        user.username = principal.username
        user.display_name = principal.display_name
        user.roles = roles
        user.last_seen_at = utcnow()
    db.flush()
    return CurrentUser(principal, user)


Me = Annotated[CurrentUser, Depends(current_user)]


def forbid() -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, "not permitted")


def require(me: CurrentUser, action: Action) -> None:
    """Authorise a non-case-scoped action."""
    if not is_allowed(me.principal.roles, action, None):
        raise forbid()


def membership(db: Session, case_id: uuid.UUID, user_id: uuid.UUID) -> str | None:
    row = db.get(CaseMember, (case_id, user_id))
    return row.permission if row else None


def load_case(db: Session, me: CurrentUser, case_id: uuid.UUID, action: Action) -> Case:
    """Load a case and authorise ``action`` on it. 404 hides existence from non-members."""
    case = db.get(Case, case_id)
    perm = membership(db, case_id, me.id) if case else None
    if case is None or (perm is None and not is_allowed(me.principal.roles, action, None)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "case not found")
    if not is_allowed(me.principal.roles, action, perm):
        raise forbid()
    if case.status != "open" and action in (Action.EVIDENCE_UPLOAD, Action.ANALYSIS_TIER1, Action.ANALYSIS_TIER2,
                                            Action.NOTE_WRITE, Action.CONCLUSION_WRITE):
        raise HTTPException(status.HTTP_409_CONFLICT, f"case is {case.status}: no new evidence, analyses or notes")
    if case.status == "disposed" and action == Action.EVIDENCE_VIEW:
        raise HTTPException(status.HTTP_410_GONE, "case disposed: evidence media is no longer available")
    return case


def load_evidence(
    db: Session, me: CurrentUser, evidence_id: uuid.UUID, action: Action
) -> EvidenceItem:
    item = db.get(EvidenceItem, evidence_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "evidence not found")
    try:
        load_case(db, me, item.case_id, action)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "evidence not found") from exc
        raise
    return item
