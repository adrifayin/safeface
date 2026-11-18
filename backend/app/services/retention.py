"""Short retention of derived working files (agreed with the user).

Kept permanently (court evidence): the sealed original in object-locked storage,
its hashes, every finding's scores and provenance, the audit chain, and reports.

Purged ``work_retention_seconds`` (7 minutes) after the last analysis of an item:
working copies, and figures/heatmaps derived from them. When a working copy is
needed again it is re-created from the sealed original and hash-checked first.
Every purge and restore is written to the audit chain.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.config import get_settings
from app.core.hashing import hash_chunks
from app.core.storage import ObjectStore
from app.core.timeutil import utcnow
from app.db.models import EvidenceItem, FindingRow, Job, JobStatus, WorkingCopyRow


class RestoreFailedError(Exception):
    """The re-created working copy does not match the ingest hash."""


def restore_working_copy(session: Session, store: ObjectStore, item: EvidenceItem, actor: str) -> WorkingCopyRow:
    """Ensure the working copy object exists; re-create it from the sealed original if it was purged."""
    s = get_settings()
    wc = session.execute(
        select(WorkingCopyRow).where(WorkingCopyRow.evidence_id == item.id, WorkingCopyRow.derived_from.is_(None))
        .order_by(WorkingCopyRow.created_at.desc()).limit(1)
    ).scalar_one()
    if store.exists(s.bucket_working, wc.storage_key):
        return wc
    store.copy(s.bucket_originals, item.storage_key, s.bucket_working, wc.storage_key)
    digest = hash_chunks(store.iter_object(s.bucket_working, wc.storage_key)).sha256
    if digest != item.sha256:
        store.delete(s.bucket_working, wc.storage_key)
        raise RestoreFailedError(f"restored working copy hash {digest} differs from ingest {item.sha256}")
    audit.record(session, actor, "evidence.working_copy_restored", "evidence", item.id,
                 {"working_copy_id": str(wc.id), "sha256": digest, "from": "sealed original"})
    return wc


def purge_delay(session: Session, evidence_id: uuid.UUID) -> float | None:
    """Seconds still to wait before purging, or None if the item can be purged now."""
    jobs = session.execute(select(Job).where(Job.evidence_id == evidence_id)).scalars().all()
    if any(j.status in (JobStatus.QUEUED, JobStatus.RUNNING) for j in jobs):
        return float(get_settings().work_retention_seconds)
    last = max((j.finished_at for j in jobs if j.finished_at), default=None)
    if last is None:
        return None
    remaining = (last + timedelta(seconds=get_settings().work_retention_seconds) - utcnow()).total_seconds()
    return remaining if remaining > 1 else None


def purge_work_files(session: Session, store: ObjectStore, item: EvidenceItem, actor: str) -> list[str]:
    s = get_settings()
    removed: list[str] = []
    for wc in session.execute(select(WorkingCopyRow).where(WorkingCopyRow.evidence_id == item.id)).scalars():
        if store.exists(s.bucket_working, wc.storage_key):
            store.delete(s.bucket_working, wc.storage_key)
            removed.append(f"working/{wc.storage_key}")
    for f in session.execute(select(FindingRow).where(FindingRow.evidence_id == item.id)).scalars():
        for art in f.artefacts:
            if store.exists(s.bucket_artefacts, art["key"]):
                store.delete(s.bucket_artefacts, art["key"])
                removed.append(f"artefacts/{art['key']}")
    if removed:
        audit.record(session, actor, "evidence.work_files_purged", "evidence", item.id, {
            "removed": removed, "retention_seconds": s.work_retention_seconds,
            "kept": "sealed original, hashes, findings (scores, provenance), audit log, reports",
        })
    return removed


def schedule_purge(evidence_id: uuid.UUID, delay: float | None = None) -> None:
    seconds = get_settings().work_retention_seconds
    if seconds <= 0:
        return
    from app.workers.tasks import purge_task

    purge_task.apply_async(args=[str(evidence_id)], countdown=int(delay if delay is not None else seconds),
                           queue="cpu")
