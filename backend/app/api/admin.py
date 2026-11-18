"""Administration: user mirror and model registry with a two-person rule (FR-6.1, FR-6.3).

Users and roles are managed in Keycloak; this API shows a read-only mirror.
Enabling or disabling a model needs an admin request AND a supervisor
approval, both audited (TDD §5 "Poisoned or swapped models").
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import DB, Me, require
from app.api.schemas import RegistryChangeCreate, RegistryChangeOut, RegistryOut, UserOut
from app.core import audit
from app.core.policy import Action
from app.core.timeutil import utcnow
from app.db.models import ModelRegistryChange, ModelRegistryEntry, User
from app.modules import weights

router = APIRouter(prefix="/admin", tags=["admin"])


def sync_registry(db: Session, actor: str) -> None:
    """Upsert models/registry.yaml into model_registry and push disabled names."""
    weights.load_registry.cache_clear()
    for entry in weights.load_registry().values():
        row = db.get(ModelRegistryEntry, entry.name)
        values = dict(
            module_id=entry.module_id, version=entry.version, weights_path=entry.path,
            weights_sha256=entry.sha256, licence=entry.licence, source=entry.source,
            validation_summary=entry.validation,
        )
        if row is None:
            db.add(ModelRegistryEntry(name=entry.name, enabled=True, **values))
            audit.record(db, actor, "registry.entry_added", "model", entry.name, values)
        elif any(getattr(row, k) != v for k, v in values.items()):
            for k, v in values.items():
                setattr(row, k, v)
            row.synced_at = utcnow()
            audit.record(db, actor, "registry.entry_changed", "model", entry.name, values)
    db.flush()
    disabled = db.execute(select(ModelRegistryEntry.name).where(
        ModelRegistryEntry.enabled.is_(False))).scalars()
    weights.set_disabled(set(disabled))


@router.get("/users", response_model=list[UserOut])
def users(db: DB, me: Me) -> list[UserOut]:
    require(me, Action.ADMIN_USERS)
    rows = db.execute(select(User).order_by(User.username)).scalars()
    return [UserOut.model_validate(u) for u in rows]


@router.get("/directory", response_model=list[UserOut])
def directory(db: DB, me: Me) -> list[UserOut]:
    """Users a supervisor can assign to cases."""
    require(me, Action.CASE_ASSIGN)
    rows = db.execute(select(User).where(User.active.is_(True)).order_by(User.username)).scalars()
    return [UserOut.model_validate(u) for u in rows]


@router.get("/models", response_model=list[RegistryOut])
def models(db: DB, me: Me) -> list[RegistryOut]:
    require(me, Action.MODELS_VIEW)
    out = []
    for row in db.execute(select(ModelRegistryEntry).order_by(ModelRegistryEntry.name)).scalars():
        r = RegistryOut.model_validate(row)
        avail = weights.weights_availability([row.name])
        r.installed = avail.available
        r.status = "ready (checksum verified on each load)" if avail.available else avail.reason
        out.append(r)
    return out


@router.get("/model-changes", response_model=list[RegistryChangeOut])
def model_changes(db: DB, me: Me) -> list[RegistryChangeOut]:
    require(me, Action.MODELS_VIEW)
    rows = db.execute(select(ModelRegistryChange).order_by(ModelRegistryChange.requested_at.desc()))
    return [RegistryChangeOut.model_validate(r) for r in rows.scalars()]


@router.post("/models/{name}/change-requests", response_model=RegistryChangeOut,
             status_code=status.HTTP_201_CREATED)
def request_change(name: str, body: RegistryChangeCreate, db: DB, me: Me) -> RegistryChangeOut:
    require(me, Action.MODELS_REQUEST_CHANGE)
    if db.get(ModelRegistryEntry, name) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "registry entry not found")
    row = ModelRegistryChange(name=name, enabled_requested=body.enabled, reason=body.reason,
                              requested_by_id=me.id)
    db.add(row)
    db.flush()
    audit.record(db, me.actor, "registry.change_requested", "model", name,
                 {"change_id": str(row.id), "enabled": body.enabled, "reason": body.reason})
    return RegistryChangeOut.model_validate(row)


@router.post("/model-changes/{change_id}/{decision}", response_model=RegistryChangeOut)
def decide_change(change_id: uuid.UUID, decision: str, db: DB, me: Me) -> RegistryChangeOut:
    require(me, Action.MODELS_APPROVE_CHANGE)
    if decision not in ("approve", "reject"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown decision")
    row = db.get(ModelRegistryChange, change_id, with_for_update=True)
    if row is None or row.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "no pending change with this id")
    if row.requested_by_id == me.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "two-person rule: requester cannot decide")
    row.status = "approved" if decision == "approve" else "rejected"
    row.decided_by_id = me.id
    row.decided_at = utcnow()
    if decision == "approve":
        entry = db.get(ModelRegistryEntry, row.name)
        assert entry is not None
        entry.enabled = row.enabled_requested
    db.flush()
    audit.record(db, me.actor, f"registry.change_{row.status}", "model", row.name,
                 {"change_id": str(row.id), "enabled": row.enabled_requested})
    sync_registry(db, me.actor)
    return RegistryChangeOut.model_validate(row)
