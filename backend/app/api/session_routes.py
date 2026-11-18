"""Login/logout audit events and the current user (FR-6.2).

Keycloak performs the actual login (password + TOTP). The web client calls
``POST /session`` immediately after the OIDC callback so every login is
recorded in the SafeFace audit chain as well as in Keycloak's event store.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.api.deps import DB, Me
from app.api.schemas import UserOut
from app.core import audit

router = APIRouter(tags=["session"])


@router.get("/me")
def me_route(me: Me) -> dict[str, Any]:
    return {"user": UserOut.model_validate(me.user).model_dump(mode="json"),
            "roles": sorted(r.value for r in me.principal.roles)}


@router.post("/session")
def session_start(request: Request, db: DB, me: Me) -> dict[str, str]:
    audit.record(db, me.actor, "auth.login", "user", me.id, {
        "session_id": me.principal.session_id or "",
        "client_ip": request.headers.get("x-real-ip", request.client.host if request.client else ""),
        "user_agent": request.headers.get("user-agent", "")[:300],
    })
    return {"status": "recorded"}


@router.post("/session/logout")
def session_end(db: DB, me: Me) -> dict[str, str]:
    audit.record(db, me.actor, "auth.logout", "user", me.id,
                 {"session_id": me.principal.session_id or ""})
    return {"status": "recorded"}
