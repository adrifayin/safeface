"""Evidence upload, reference linking, verification and chain of custody."""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.api.deps import DB, Me, load_case, load_evidence
from app.api.schemas import (
    CustodyEntry,
    EvidenceMetadata,
    EvidenceOut,
    ReferenceLink,
    UploadResult,
    VerificationOut,
)
from app.api.serialise import evidence_out
from app.core import audit
from app.core.config import get_settings
from app.core.policy import Action
from app.core.storage import get_store, working_key
from app.db.models import (
    AuditLog,
    EvidenceItem,
    EvidenceKind,
    EvidenceReference,
    HashVerification,
    WorkingCopyRow,
)
from app.db.session import session_scope
from app.services.analysis import create_jobs, triage_module_ids
from app.services.ingest import store_original_stream
from app.services.verification import verify_item

router = APIRouter(tags=["evidence"])


def _parse_metadata(header: str) -> EvidenceMetadata:
    try:
        padded = header + "=" * (-len(header) % 4)
        raw = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        return EvidenceMetadata.model_validate(raw)
    except (binascii.Error, UnicodeError, ValueError, ValidationError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"bad metadata header: {exc}") from exc


@router.post(
    "/cases/{case_id}/evidence", response_model=UploadResult, status_code=status.HTTP_201_CREATED
)
async def upload_evidence(
    case_id: uuid.UUID,
    request: Request,
    db: DB,
    me: Me,
    x_safeface_metadata: Annotated[str, Header()],
) -> UploadResult:
    """Stream an original into evidence storage. Body = raw file bytes.

    Metadata (filename, provenance) travels base64url-JSON in ``X-SafeFace-Metadata``
    so the body can be streamed without multipart parsing or temporary files.
    """
    meta = _parse_metadata(x_safeface_metadata)
    case = await run_in_threadpool(load_case, db, me, case_id, Action.EVIDENCE_UPLOAD)
    declared = request.headers.get("content-length")
    if declared and int(declared) > get_settings().max_upload_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "file exceeds the 4 GiB limit")

    # Validate everything we can BEFORE anything reaches write-once storage.
    await run_in_threadpool(_check_reference_for, db, case.id, meta)

    store = get_store()
    stored = await store_original_stream(store, case.id, request.stream())
    try:
        return await run_in_threadpool(_record_ingest, db, me, case.id, meta, stored, store)
    except BaseException as exc:
        # The original is already object-locked and cannot be removed. Record the
        # orphan in its own committed transaction so it is never unaccounted for.
        await run_in_threadpool(_record_aborted_ingest, me.actor, case.id, meta, stored, exc)
        raise


def _check_reference_for(db, case_id: uuid.UUID, meta: EvidenceMetadata) -> None:  # type: ignore[no-untyped-def]
    for qid in meta.reference_for:
        q = db.get(EvidenceItem, qid)
        if q is None or q.case_id != case_id or q.kind != EvidenceKind.QUESTIONED:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"bad reference_for {qid}")


def _record_aborted_ingest(actor, case_id, meta, stored, exc) -> None:  # type: ignore[no-untyped-def]
    with session_scope() as s:
        audit.record(s, actor, "evidence.ingest_aborted", "case", case_id, {
            "filename": meta.filename, "storage_key": stored.storage_key,
            "storage_version_id": stored.version_id, "sha256": stored.digests.sha256,
            "md5": stored.digests.md5, "size_bytes": stored.digests.size,
            "reason": f"{exc.__class__.__name__}: {str(exc)[:300]}",
        })


def _record_ingest(db, me, case_id, meta, stored, store) -> UploadResult:  # type: ignore[no-untyped-def]
    settings = get_settings()
    _check_reference_for(db, case_id, meta)
    item = EvidenceItem(
        id=stored.evidence_id, case_id=case_id, kind=meta.kind.value,
        media_type=stored.detected.media_type.value, detected_mime=stored.detected.mime,
        original_filename=meta.filename, size_bytes=stored.digests.size,
        sha256=stored.digests.sha256, md5=stored.digests.md5, storage_key=stored.storage_key,
        storage_version_id=stored.version_id,
        source_url=str(meta.source_url) if meta.source_url else None,
        source_platform=meta.source_platform, source_device=meta.source_device,
        complainant=meta.complainant, collected_by=meta.collected_by,
        collected_at=meta.collected_at, upload_method=meta.upload_method, uploaded_by_id=me.id,
    )
    db.add(item)
    db.flush()
    audit.record(db, me.actor, "evidence.ingested", "evidence", item.id, {
        "case_id": str(case_id), "filename": meta.filename, "kind": item.kind,
        "detected_type": stored.detected.label, "size_bytes": item.size_bytes,
        "sha256": item.sha256, "md5": item.md5, "storage_version_id": item.storage_version_id,
        "provenance": meta.model_dump(mode="json", exclude={"filename", "kind"}),
    })

    copy_id = uuid.uuid4()
    wkey = working_key(case_id, item.id, copy_id)
    store.copy(settings.bucket_originals, item.storage_key, settings.bucket_working, wkey)
    db.add(WorkingCopyRow(id=copy_id, evidence_id=item.id, storage_key=wkey,
                          sha256=item.sha256, md5=item.md5))
    db.flush()
    audit.record(db, me.actor, "evidence.working_copy_created", "evidence", item.id,
                 {"working_copy_id": str(copy_id)})

    # Read back what is actually stored and confirm the hashes.
    results = verify_item(db, store, item, me.actor, "ingest")
    if not all(r.ok for r in results):
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                            "stored copy does not match the received bytes; ingest aborted")

    for qid in meta.reference_for:
        db.add(EvidenceReference(questioned_id=qid, reference_id=item.id, linked_by_id=me.id))
        audit.record(db, me.actor, "evidence.reference_linked", "evidence", qid,
                     {"reference_id": str(item.id)})
    db.flush()

    to_run, skipped = triage_module_ids(item)
    jobs = create_jobs(db, f"system (auto-triage) for {me.principal.username}", me.id, item,
                       to_run, {}, [], allowed_tiers={1})
    audit.record(db, me.actor, "evidence.triage_queued", "evidence", item.id,
                 {"modules": to_run, "skipped_unavailable": skipped})
    return UploadResult(
        evidence=evidence_out(db, item), sha256=item.sha256, md5=item.md5,
        size_bytes=item.size_bytes, triage_job_ids=[j.id for j in jobs],
    )


@router.get("/evidence/{evidence_id}", response_model=EvidenceOut)
def get_evidence(evidence_id: uuid.UUID, db: DB, me: Me) -> EvidenceOut:
    item = load_evidence(db, me, evidence_id, Action.CASE_VIEW)
    return evidence_out(db, item)


@router.post("/evidence/{evidence_id}/references", response_model=EvidenceOut)
def link_references(evidence_id: uuid.UUID, body: ReferenceLink, db: DB, me: Me) -> EvidenceOut:
    item = load_evidence(db, me, evidence_id, Action.EVIDENCE_UPLOAD)
    if item.kind != EvidenceKind.QUESTIONED:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "references attach to questioned items")
    for ref_id in body.reference_ids:
        ref = db.get(EvidenceItem, ref_id)
        if ref is None or ref.case_id != item.case_id or ref.id == item.id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"bad reference {ref_id}")
        if db.get(EvidenceReference, (item.id, ref_id)) is None:
            db.add(EvidenceReference(questioned_id=item.id, reference_id=ref_id, linked_by_id=me.id))
            audit.record(db, me.actor, "evidence.reference_linked", "evidence", item.id,
                         {"reference_id": str(ref_id)})
    db.flush()
    return evidence_out(db, item)


@router.get("/evidence/{evidence_id}/content")
def get_content(evidence_id: uuid.UUID, db: DB, me: Me) -> StreamingResponse:
    """Stream the working copy for display (the browser blurs it until revealed)."""
    item = load_evidence(db, me, evidence_id, Action.EVIDENCE_VIEW)
    wc = db.execute(
        select(WorkingCopyRow).where(WorkingCopyRow.evidence_id == item.id,
                                     WorkingCopyRow.derived_from.is_(None))
        .order_by(WorkingCopyRow.created_at.desc()).limit(1)
    ).scalar_one()
    audit.record(db, me.actor, "evidence.viewed", "evidence", item.id, {"what": "content"})
    db.commit()
    stream = get_store().iter_object(get_settings().bucket_working, wc.storage_key)
    return StreamingResponse(stream, media_type=item.detected_mime, headers={
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        "Content-Disposition": "inline",
    })


@router.post("/evidence/{evidence_id}/verify", response_model=list[VerificationOut])
def verify(evidence_id: uuid.UUID, db: DB, me: Me) -> list[VerificationOut]:
    item = load_evidence(db, me, evidence_id, Action.EVIDENCE_VERIFY)
    rows = verify_item(db, get_store(), item, me.actor, "on-demand")
    return [VerificationOut.model_validate(r) for r in rows]


@router.get("/evidence/{evidence_id}/verifications", response_model=list[VerificationOut])
def verifications(evidence_id: uuid.UUID, db: DB, me: Me) -> list[VerificationOut]:
    item = load_evidence(db, me, evidence_id, Action.CASE_VIEW)
    rows = db.execute(select(HashVerification).where(HashVerification.evidence_id == item.id)
                      .order_by(HashVerification.verified_at)).scalars()
    return [VerificationOut.model_validate(r) for r in rows]


@router.get("/evidence/{evidence_id}/custody", response_model=list[CustodyEntry])
def custody(evidence_id: uuid.UUID, db: DB, me: Me) -> list[CustodyEntry]:
    """Chain-of-custody: every audited action on this item, oldest first (FR-1.5)."""
    item = load_evidence(db, me, evidence_id, Action.CASE_VIEW)
    audit.record(db, me.actor, "evidence.custody_viewed", "evidence", item.id)
    rows = db.execute(
        select(AuditLog).where(AuditLog.target_type == "evidence",
                               AuditLog.target_id == str(item.id)).order_by(AuditLog.seq)
    ).scalars()
    return [CustodyEntry(seq=r.seq, ts=r.ts, actor=r.actor, action=r.action,
                         details=r.details, entry_hash=r.entry_hash) for r in rows]
