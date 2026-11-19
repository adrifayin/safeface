"""Creating analysis jobs and dispatching them to the right queue."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.db.models import EvidenceItem, EvidenceKind, EvidenceReference, Job, JobStatus
from app.db.session import after_commit
from app.modules.base import AnalysisModule, MediaType
from app.modules.registry import all_modules, get_module
from app.modules.status import effective, module_queue


def queue_name(module: AnalysisModule) -> str:
    return module_queue(module)


def _dispatch(job_id: uuid.UUID, queue: str) -> None:
    from app.workers.tasks import run_analysis

    run_analysis.apply_async(args=[str(job_id)], queue=queue)


def _dispatcher(job_id: uuid.UUID, queue: str) -> Callable[[], None]:
    return lambda: _dispatch(job_id, queue)


def linked_reference_ids(session: Session, questioned_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        session.execute(
            select(EvidenceReference.reference_id).where(
                EvidenceReference.questioned_id == questioned_id
            )
        ).scalars()
    )


def create_jobs(
    session: Session,
    actor: str,
    user_id: uuid.UUID,
    item: EvidenceItem,
    module_ids: list[str],
    params: dict[str, dict[str, Any]],
    reference_ids: list[uuid.UUID],
    allowed_tiers: set[int],
    rerun_of: uuid.UUID | None = None,
) -> list[Job]:
    """Validate and create jobs; they are sent to Celery after commit."""
    jobs: list[Job] = []
    for module_id in module_ids:
        try:
            module = get_module(module_id)
        except KeyError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
        if module.tier not in allowed_tiers:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, f"{module_id} is a Tier {module.tier} (examiner) tool"
            )
        if MediaType(item.media_type) not in module.media_types:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, f"{module_id} does not support {item.media_type}"
            )
        refs = reference_ids or (linked_reference_ids(session, item.id) if module.requires_reference else [])
        if module.requires_reference and not refs:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, f"{module_id} needs at least one reference image"
            )
        for ref_id in refs:
            ref = session.get(EvidenceItem, ref_id)
            if ref is None or ref.case_id != item.case_id or ref.id == item.id:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"bad reference {ref_id}")
        module_params = params.get(module_id, {})
        try:
            module.merged_params(module_params)
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
        job = Job(
            evidence_id=item.id,
            module_id=module.id,
            module_version=module.version,
            params=module_params,
            reference_ids=[str(r) for r in (refs if module.requires_reference else [])],
            queue=queue_name(module),
            status=JobStatus.QUEUED,
            requested_by_id=user_id,
            rerun_of_finding_id=rerun_of,
        )
        session.add(job)
        session.flush()
        audit.record(
            session, actor, "analysis.queued", "evidence", item.id,
            {"job_id": str(job.id), "module_id": module.id, "module_version": module.version,
             "params": module_params, "reference_ids": job.reference_ids,
             "rerun_of_finding_id": str(rerun_of) if rerun_of else None},
        )
        after_commit(session, _dispatcher(job.id, job.queue))
        jobs.append(job)
    return jobs


def missing_module_ids(session: Session, item: EvidenceItem) -> list[str]:
    """Automatic checks that have no result for the current module version and are not queued.

    Covers items uploaded before a check was installed or upgraded."""
    from app.db.models import FindingRow

    run, _ = triage_module_ids(item)
    modules = all_modules()
    have = {(f.module_id, f.module_version) for f in
            session.execute(select(FindingRow).where(FindingRow.evidence_id == item.id)).scalars()}
    busy = {j.module_id for j in session.execute(select(Job).where(Job.evidence_id == item.id)).scalars()
            if j.status in (JobStatus.QUEUED, JobStatus.RUNNING)}
    return [m for m in run if (m, modules[m].version) not in have and m not in busy]


def triage_module_ids(item: EvidenceItem) -> tuple[list[str], list[str]]:
    """Tier 1 modules to run automatically on ingest: (to_run, skipped_unavailable)."""
    if item.kind == EvidenceKind.REFERENCE:
        return ["integrity.hash"], []
    candidates = [m for m in all_modules().values()
                  if m.tier == 1 and not m.requires_reference and MediaType(item.media_type) in m.media_types]
    status = effective(candidates)
    run, skipped = [], []
    for module in candidates:
        st = status[module.id]
        # Unknown (worker not reported yet) is queued: the worker decides and records it.
        if st.availability.available or not st.known:
            run.append(module.id)
        else:
            skipped.append(module.id)
    return run, skipped
