"""Analysis job execution.

For each job the worker:
1. marks it running (audited);
2. downloads the working copy (and references) to a private temp directory
   and re-hashes them: a copy whose SHA-256 differs from the ingest hash is
   refused;
3. applies deterministic settings and runs the module;
4. uploads artefacts and stores the immutable finding with full provenance
   (audited).
Failures and unavailable modules are recorded, never silently dropped.
"""

from __future__ import annotations

import logging
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from celery.signals import worker_ready
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.canonical import normalise
from app.core.config import get_settings
from app.core.environment import set_deterministic, static_environment
from app.core.hashing import hash_file
from app.core.storage import ObjectStore, artefact_key, get_store
from app.core.timeutil import iso, utcnow
from app.db.models import (
    EvidenceItem,
    FindingRow,
    Job,
    JobStatus,
    ModelRegistryEntry,
    User,
    WorkingCopyRow,
)
from app.db.session import session_scope
from app.modules import weights
from app.modules.base import (
    AnalysisModule,
    Finding,
    MediaType,
    ModuleUnavailable,
    WorkingCopy,
)
from app.modules.registry import get_module
from app.modules.status import report_worker_status
from app.modules.weights import WeightsError
from app.services.retention import purge_delay, purge_work_files, restore_working_copy, schedule_purge
from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)

EXTENSIONS = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/heic": ".heic",
    "video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm",
    "video/x-matroska": ".mkv", "audio/wav": ".wav", "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a", "audio/ogg": ".ogg",
}


class IntegrityFailure(Exception):
    """A working copy does not match the hash recorded at ingest."""


@worker_ready.connect  # type: ignore[misc]
def _report_status(**_: Any) -> None:
    """Tell the API which modules this worker can run (tools/weights present)."""
    queue = get_settings().worker_queue
    if queue:
        report_worker_status(queue)


@celery_app.task(name="safeface.run_analysis")  # type: ignore[misc]
def run_analysis(job_id: str) -> None:
    execute_job(uuid.UUID(job_id))


def _actor(session: Session, job: Job) -> str:
    user = session.get(User, job.requested_by_id)
    who = user.username if user else str(job.requested_by_id)
    return f"worker:{static_environment()['host']} for {who}"


def _latest_working_copy(session: Session, evidence_id: uuid.UUID) -> WorkingCopyRow:
    row = session.execute(
        select(WorkingCopyRow)
        .where(WorkingCopyRow.evidence_id == evidence_id, WorkingCopyRow.derived_from.is_(None))
        .order_by(WorkingCopyRow.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        raise IntegrityFailure(f"no working copy for evidence {evidence_id}")
    return row


def fetch_working_copy(
    session: Session, store: ObjectStore, evidence: EvidenceItem, dest: Path
) -> WorkingCopy:
    """Download and hash-verify the working copy of ``evidence`` into ``dest``."""
    restore_working_copy(session, store, evidence, "worker (restore for analysis)")
    wc = _latest_working_copy(session, evidence.id)
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"item{EXTENSIONS.get(evidence.detected_mime, '.bin')}"
    store.download_to(get_settings().bucket_working, wc.storage_key, path)
    digests = hash_file(path)
    if digests.sha256 != wc.sha256 or digests.sha256 != evidence.sha256:
        raise IntegrityFailure(
            f"working copy of {evidence.id} has SHA-256 {digests.sha256}; "
            f"ingest recorded {evidence.sha256}. Analysis refused."
        )
    workdir = dest / "out"
    workdir.mkdir(exist_ok=True)
    return WorkingCopy(
        evidence_id=str(evidence.id),
        path=path,
        sha256=digests.sha256,
        md5=digests.md5,
        media_type=MediaType(evidence.media_type),
        original_filename=evidence.original_filename,
        kind=evidence.kind,
        original_sha256=evidence.sha256,
        original_md5=evidence.md5,
        workdir=workdir,
    )


@celery_app.task(name="safeface.run_benchmark")  # type: ignore[misc]
def benchmark_task(run_id: str) -> None:
    """Phase 4 validation run (can take long: one module run per dataset item)."""
    from app.db.models import BenchmarkRun
    from app.services.benchmark import run_benchmark

    rid = uuid.UUID(run_id)
    with session_scope() as session:
        run = session.get(BenchmarkRun, rid)
        if run is None or run.status != "queued":
            return
        run.status = "running"
        module_id, dataset, robustness = run.module_id, run.dataset, run.robustness
    try:
        results = run_benchmark(module_id, Path(get_settings().datasets_dir) / dataset, robustness)
        status_, error = "succeeded", None
    except Exception as exc:  # noqa: BLE001 - recorded on the run
        results, status_, error = {}, "failed", f"{exc.__class__.__name__}: {exc}"[:2000]
    with session_scope() as session:
        run = session.get(BenchmarkRun, rid)
        assert run is not None
        run.status, run.results, run.error, run.finished_at = status_, normalise(results), error, utcnow()
        audit.record(session, "system (benchmark)", f"benchmark.{status_}", "module", module_id,
                     {"run_id": run_id, "dataset": dataset, "clean": results.get("clean", {}), "error": error})


@celery_app.task(name="safeface.purge_work_files")  # type: ignore[misc]
def purge_task(evidence_id: str) -> None:
    """Purge working files once no analysis of the item has run for the retention period."""
    eid = uuid.UUID(evidence_id)
    with session_scope() as session:
        wait = purge_delay(session, eid)
        if wait is not None:
            schedule_purge(eid, wait)
            return
        item = session.get(EvidenceItem, eid)
        if item is not None:
            purge_work_files(session, get_store(), item, "system (7-minute retention)")


def _finish(job_id: uuid.UUID, status: JobStatus, error: str, action: str) -> None:
    with session_scope() as session:
        job = session.get(Job, job_id, with_for_update=True)
        assert job is not None
        job.status = status
        job.error = error[:4000]
        job.finished_at = utcnow()
        audit.record(
            session, _actor(session, job), action, "evidence", job.evidence_id,
            {"job_id": str(job.id), "module_id": job.module_id, "error": error[:500]},
        )
        evidence_id = job.evidence_id
    schedule_purge(evidence_id)


def execute_job(job_id: uuid.UUID) -> None:
    settings = get_settings()
    store = get_store()

    with session_scope() as session:
        job = session.get(Job, job_id, with_for_update=True)
        if job is None or job.status != JobStatus.QUEUED:
            log.warning("job %s not runnable (missing or not queued)", job_id)
            return
        job.status = JobStatus.RUNNING
        job.started_at = utcnow()
        # Honour registry enable/disable decisions made since this worker started.
        weights.set_disabled(set(session.execute(
            select(ModelRegistryEntry.name).where(ModelRegistryEntry.enabled.is_(False))).scalars()))
        audit.record(
            session, _actor(session, job), "analysis.started", "evidence", job.evidence_id,
            {"job_id": str(job.id), "module_id": job.module_id},
        )

    try:
        module = get_module(job.module_id)
        availability = module.availability()
        if not availability.available:
            raise ModuleUnavailable(availability.reason)
        Path(settings.work_dir).mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=settings.work_dir, prefix="job-") as tmp:
            _run_in_dir(job_id, module, store, Path(tmp))
    except (ModuleUnavailable, WeightsError) as exc:
        _finish(job_id, JobStatus.UNAVAILABLE, str(exc), "analysis.unavailable")
    except IntegrityFailure as exc:
        _finish(job_id, JobStatus.FAILED, str(exc), "analysis.integrity_failure")
    except Exception as exc:
        log.exception("job %s failed", job_id)
        _finish(job_id, JobStatus.FAILED, f"{exc.__class__.__name__}: {exc}", "analysis.failed")


def _run_in_dir(job_id: uuid.UUID, module: AnalysisModule, store: ObjectStore, tmp: Path) -> None:
    settings = get_settings()
    with session_scope() as session:
        job = session.get(Job, job_id)
        assert job is not None
        evidence = session.get(EvidenceItem, job.evidence_id)
        assert evidence is not None
        item = fetch_working_copy(session, store, evidence, tmp / "item")
        refs: list[WorkingCopy] = []
        for i, ref_id in enumerate(job.reference_ids):
            ref = session.get(EvidenceItem, uuid.UUID(ref_id))
            if ref is None or ref.case_id != evidence.case_id:
                raise IntegrityFailure(f"reference {ref_id} not found in this case")
            refs.append(fetch_working_copy(session, store, ref, tmp / f"ref{i}"))
        params: dict[str, Any] = dict(job.params)
        case_id = evidence.case_id

    determinism = set_deterministic(settings.seed)
    started = utcnow()
    t0 = time.perf_counter()
    finding: Finding = module.run(item, refs, params)
    runtime_s = time.perf_counter() - t0
    finished = utcnow()

    finding_id = uuid.uuid4()
    artefacts: list[dict[str, Any]] = []
    for art in finding.artefacts:
        key = artefact_key(case_id, item.evidence_id, finding_id, art.name)
        data = art.path.read_bytes()
        store.put_bytes(settings.bucket_artefacts, key, data, art.content_type)
        artefacts.append({
            "name": art.name, "key": key, "kind": art.kind.value,
            "description": art.description, "content_type": art.content_type,
            "sha256": hash_file(art.path).sha256,
        })

    provenance = {
        **finding.provenance,
        "module_id": module.id,
        "module_version": module.version,
        "params": {**module.default_params, **params},
        "environment": static_environment(),
        "determinism": determinism,
        "started_at": iso(started),
        "finished_at": iso(finished),
        "runtime_seconds": round(runtime_s, 3),
        "input": {"evidence_id": item.evidence_id, "sha256": item.sha256},
        "references": [{"evidence_id": r.evidence_id, "sha256": r.sha256} for r in refs],
    }
    provenance.setdefault("weights", {})

    with session_scope() as session:
        job = session.get(Job, job_id, with_for_update=True)
        assert job is not None
        row = FindingRow(
            id=finding_id,
            job_id=job.id,
            evidence_id=job.evidence_id,
            module_id=module.id,
            module_version=module.version,
            family=module.family.value,
            tier=module.tier,
            scores=normalise([s.to_json() for s in finding.scores]),
            summary=finding.summary,
            details=normalise(finding.details),
            artefacts=artefacts,
            limitations=finding.limitations,
            provenance=normalise(provenance),
        )
        session.add(row)
        job.status = JobStatus.SUCCEEDED
        job.finished_at = finished
        session.flush()
        audit.record(
            session, _actor(session, job), "analysis.completed", "evidence", job.evidence_id,
            {
                "job_id": str(job.id), "finding_id": str(finding_id), "module_id": module.id,
                "module_version": module.version,
                "artefact_sha256": {a["name"]: a["sha256"] for a in artefacts},
            },
        )
        evidence_id = job.evidence_id
    schedule_purge(evidence_id)
