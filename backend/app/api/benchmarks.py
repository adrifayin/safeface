"""Phase 4: run and list validation benchmarks from the Administration screen (SRS FR-6.4)."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import DB, Me, require
from app.core import audit
from app.core.config import get_settings
from app.core.policy import Action
from app.db.models import BenchmarkRun
from app.db.session import after_commit
from app.modules.registry import get_module
from app.services.benchmark import PRIMARY, list_datasets

router = APIRouter(prefix="/admin", tags=["benchmarks"])


class BenchmarkCreate(BaseModel):
    module_id: str
    dataset: str
    robustness: bool = False


def _out(r: BenchmarkRun) -> dict[str, Any]:
    return {"id": str(r.id), "module_id": r.module_id, "dataset": r.dataset, "robustness": r.robustness,
            "status": r.status, "requested_at": r.requested_at.isoformat(),
            "finished_at": r.finished_at.isoformat() if r.finished_at else None, "results": r.results,
            "error": r.error}


@router.get("/datasets")
def datasets(me: Me) -> dict[str, Any]:
    require(me, Action.MODELS_VIEW)
    return {"datasets": list_datasets(Path(get_settings().datasets_dir)), "modules": sorted(PRIMARY),
            "layout": "<dataset>/real/*, <dataset>/fake/*, optional <dataset>/masks/<stem>.png"}


@router.get("/benchmarks")
def runs(db: DB, me: Me) -> list[dict[str, Any]]:
    require(me, Action.MODELS_VIEW)
    rows = db.execute(select(BenchmarkRun).order_by(BenchmarkRun.requested_at.desc()).limit(100)).scalars()
    return [_out(r) for r in rows]


@router.post("/benchmarks", status_code=status.HTTP_202_ACCEPTED)
def start(body: BenchmarkCreate, db: DB, me: Me) -> dict[str, Any]:
    require(me, Action.BENCHMARK_RUN)
    if body.module_id not in PRIMARY:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "this module has no benchmark score defined")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", body.dataset) or body.dataset.startswith("."):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid dataset name")
    if body.dataset not in {d["name"] for d in list_datasets(Path(get_settings().datasets_dir))}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dataset not found under the datasets folder")
    module = get_module(body.module_id)
    run = BenchmarkRun(module_id=body.module_id, dataset=body.dataset, robustness=body.robustness,
                       requested_by_id=me.id, results={})
    db.add(run)
    db.flush()
    audit.record(db, me.actor, "benchmark.queued", "module", body.module_id,
                 {"run_id": str(run.id), "dataset": body.dataset, "robustness": body.robustness})
    run_id, queue = str(run.id), "gpu" if module.requires_gpu else "cpu"

    def dispatch() -> None:
        from app.workers.tasks import benchmark_task

        benchmark_task.apply_async(args=[run_id], queue=queue)

    after_commit(db, dispatch)
    return _out(run)


__all__ = ["router", "uuid"]
