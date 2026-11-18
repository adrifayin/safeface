"""Registered analysis modules with availability and validation summaries."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import Me, require
from app.api.schemas import ModuleOut
from app.core.policy import Action
from app.modules.base import FAMILY_LABELS, FAMILY_ORDER
from app.modules.registry import all_modules
from app.modules.status import effective
from app.modules.weights import load_registry

router = APIRouter(tags=["modules"])


def module_list() -> list[ModuleOut]:
    registry = load_registry()
    out = []
    order = {f: i for i, f in enumerate(FAMILY_ORDER)}
    mods = sorted(all_modules().values(), key=lambda m: (order[m.family], m.tier, m.id))
    status = effective(mods)
    for m in mods:
        avail = status[m.id].availability
        validation = [
            {"weights": n, **registry[n].validation} for n in m.required_weights if n in registry
        ]
        out.append(ModuleOut(
            id=m.id, version=m.version, name=m.name, description=m.description,
            family=m.family.value, family_label=FAMILY_LABELS[m.family],
            media_types=sorted(t.value for t in m.media_types), tier=m.tier,
            requires_gpu=m.requires_gpu, requires_reference=m.requires_reference,
            limitations=m.limitations, triage_indicator=m.triage_indicator,
            available=avail.available, unavailable_reason=avail.reason,
            default_params=m.default_params, validation=validation,
        ))
    return out


@router.get("/modules", response_model=list[ModuleOut])
def list_modules(me: Me) -> list[ModuleOut]:
    require(me, Action.MODULES_VIEW)
    return module_list()
