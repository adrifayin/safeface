"""Report generation/export and BSA s.63(4) Part A data (FR-5.6, FR-5.7)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import func, select

from app import __version__
from app.api.deps import DB, Me, load_case
from app.api.schemas import ReportOut
from app.core import audit
from app.core.config import get_settings
from app.core.policy import Action
from app.core.storage import get_store
from app.core.timeutil import iso
from app.db.models import Case, EvidenceItem, Report
from app.db.session import session_scope
from app.reports import builder
from app.services.verification import latest_verification

router = APIRouter(tags=["reports"])


def _verify_or_refuse(case_id: uuid.UUID, actor: str) -> list[dict[str, Any]]:
    """Re-hash in a separate, always-committed transaction so failures are recorded."""
    with session_scope() as s:
        case = s.get(Case, case_id)
        assert case is not None
        hashes, failures = builder.verify_case(s, get_store(), case, actor)
        if failures:
            audit.record(s, actor, "report.refused", "case", case_id, {
                "reason": "hash verification failed",
                "failed_evidence": [f["evidence_id"] for f in failures],
            })
    if failures:
        raise HTTPException(status.HTTP_409_CONFLICT, {
            "message": "Hash verification failed; report refused. The stored original no longer "
                       "matches its ingest hash.",
            "failed_evidence": failures,
        })
    return hashes


@router.post("/cases/{case_id}/reports", response_model=ReportOut,
             status_code=status.HTTP_201_CREATED)
def generate_report(case_id: uuid.UUID, db: DB, me: Me) -> ReportOut:
    case = load_case(db, me, case_id, Action.REPORT_GENERATE)
    hashes = _verify_or_refuse(case.id, me.actor)
    db.execute(select(Case.id).where(Case.id == case.id).with_for_update())
    version = (db.execute(select(func.max(Report.version)).where(Report.case_id == case.id))
               .scalar_one() or 0) + 1
    context = builder.collect(db, get_store(), case, me.actor, version, hashes)
    built = builder.render(context, pdf=True)
    assert built.pdf is not None
    digest = builder.pdf_sha256(built.pdf)
    report_id = uuid.uuid4()
    key = f"cases/{case.id}/reports/v{version}-{report_id}.pdf"
    get_store().put_bytes(get_settings().bucket_reports, key, built.pdf, "application/pdf")
    row = Report(id=report_id, case_id=case.id, version=version, status=built.status,
                 pdf_storage_key=key, pdf_sha256=digest, evidence_hashes=built.evidence_hashes,
                 generated_by_id=me.id, signed_by=built.signed_by)
    db.add(row)
    db.flush()
    audit.record(db, me.actor, "report.generated", "case", case.id, {
        "report_id": str(report_id), "version": version, "status": built.status,
        "pdf_sha256": digest,
        "evidence_sha256": {h["evidence_id"]: h["sha256"] for h in built.evidence_hashes},
    })
    return ReportOut.model_validate(row)


@router.get("/cases/{case_id}/reports", response_model=list[ReportOut])
def list_reports(case_id: uuid.UUID, db: DB, me: Me) -> list[ReportOut]:
    case = load_case(db, me, case_id, Action.REPORT_VIEW)
    rows = db.execute(select(Report).where(Report.case_id == case.id).order_by(Report.version))
    return [ReportOut.model_validate(r) for r in rows.scalars()]


@router.get("/cases/{case_id}/report-preview", response_class=HTMLResponse)
def preview(case_id: uuid.UUID, db: DB, me: Me) -> HTMLResponse:
    """HTML preview of the next report (no re-verification, nothing stored)."""
    case = load_case(db, me, case_id, Action.REPORT_GENERATE)
    items = db.execute(select(EvidenceItem).where(EvidenceItem.case_id == case.id)).scalars()
    hashes = []
    for item in items:
        last = latest_verification(db, item.id)
        hashes.append({
            "evidence_id": str(item.id), "filename": item.original_filename, "kind": item.kind,
            "media_type": item.media_type, "detected_mime": item.detected_mime,
            "size_bytes": item.size_bytes, "sha256": item.sha256, "md5": item.md5,
            "verified_at": iso(last.verified_at) if last else "not yet verified",
            "verified_ok": bool(last and last.ok), "ingested_at": iso(item.ingested_at),
            "source_url": item.source_url, "source_platform": item.source_platform,
            "source_device": item.source_device, "complainant": item.complainant,
            "collected_by": item.collected_by,
            "collected_at": iso(item.collected_at) if item.collected_at else None,
            "upload_method": item.upload_method,
        })
    context = builder.collect(db, get_store(), case, me.actor, 0, hashes)
    context["preview"] = True
    audit.record(db, me.actor, "report.previewed", "case", case.id)
    return HTMLResponse(builder.render(context, pdf=False).html, headers={
        "Content-Security-Policy": "default-src 'none'; img-src data:; style-src 'unsafe-inline'",
    })


@router.get("/reports/{report_id}/pdf")
def download(report_id: uuid.UUID, db: DB, me: Me) -> Response:
    row = db.get(Report, report_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "report not found")
    load_case(db, me, row.case_id, Action.REPORT_VIEW)
    data = get_store().get_bytes(get_settings().bucket_reports, row.pdf_storage_key)
    actual = builder.pdf_sha256(data)
    audit.record(db, me.actor, "report.exported", "case", row.case_id, {
        "report_id": str(row.id), "version": row.version, "pdf_sha256": actual,
        "matches_recorded": actual == row.pdf_sha256,
    })
    if actual != row.pdf_sha256:
        db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, "stored PDF does not match its recorded hash")
    return Response(data, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="safeface-report-v{row.version}.pdf"',
        "X-SafeFace-PDF-SHA256": actual,
    })


@router.get("/cases/{case_id}/s63-data")
def s63_data(case_id: uuid.UUID, db: DB, me: Me) -> dict[str, Any]:
    """Pre-fill data for the BSA 2023 s.63(4) certificate, Part A (FR-5.7, NFR-L1).

    Part A is completed and signed by the party producing the electronic record;
    this endpoint only gathers the device, file and hash facts SafeFace holds.
    Fields SafeFace cannot know are returned as ``null`` for manual completion.
    """
    case = load_case(db, me, case_id, Action.S63_VIEW)
    settings = get_settings()
    items = db.execute(select(EvidenceItem).where(EvidenceItem.case_id == case.id)
                       .order_by(EvidenceItem.ingested_at)).scalars()
    records = []
    for item in items:
        last = latest_verification(db, item.id)
        records.append({
            "evidence_id": str(item.id),
            "kind": item.kind,
            "file_name": item.original_filename,
            "file_type": item.detected_mime,
            "file_size_bytes": item.size_bytes,
            "hash_values": [
                {"algorithm": "SHA-256", "value": item.sha256},
                {"algorithm": "MD5", "value": item.md5},
            ],
            "hash_computed_at": iso(item.ingested_at),
            "last_verified_at": iso(last.verified_at) if last else None,
            "last_verification_ok": bool(last and last.ok),
            "source_device": item.source_device,
            "source_platform": item.source_platform,
            "source_url": item.source_url,
            "collected_by": item.collected_by,
            "collected_at": iso(item.collected_at) if item.collected_at else None,
            "upload_method": item.upload_method,
            "device_make_model": None,
            "device_serial_or_imei": None,
            "device_owner_or_custodian": None,
        })
    audit.record(db, me.actor, "s63.viewed", "case", case.id)
    return {
        "certificate": "Bharatiya Sakshya Adhiniyam, 2023 — Section 63(4), Schedule Part A",
        "note": "Pre-filled from SafeFace records. Part A must be completed and signed by the "
                "person in charge of the device/record; Part B by the expert. Null fields "
                "require manual completion.",
        "case": {"case_no": case.case_no, "fir_no": case.fir_no, "crime_head": case.crime_head,
                 "investigating_officer": case.investigating_officer},
        "processing_system": {
            "name": "SafeFace Forensic Workbench", "version": __version__,
            "deployment": settings.deployment_name, "image_digest": settings.image_digest,
        },
        "records": records,
    }
