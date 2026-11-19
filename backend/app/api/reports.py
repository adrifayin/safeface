"""Report generation/export and BSA s.63(4) Part A data (FR-5.6, FR-5.7)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import __version__
from app.api.deps import DB, CurrentUser, Me, load_case, load_evidence
from app.api.schemas import PerItemReportsOut, ReportOut
from app.core import audit
from app.core.config import get_settings
from app.core.policy import Action
from app.core.storage import get_store
from app.core.timeutil import iso
from app.db.models import Case, EvidenceItem, EvidenceKind, Report
from app.db.session import session_scope
from app.reports import builder
from app.services.verification import latest_verification

router = APIRouter(tags=["reports"])


def _verify(
    case_id: uuid.UUID, actor: str, only: set[uuid.UUID] | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Re-hash in a separate, always-committed transaction so failures are recorded."""
    with session_scope() as s:
        case = s.get(Case, case_id)
        assert case is not None
        hashes, failures = builder.verify_case(s, get_store(), case, actor, only)
        if failures:
            audit.record(s, actor, "report.refused", "case", case_id, {
                "reason": "hash verification failed",
                "failed_evidence": [f["evidence_id"] for f in failures],
                **({"scope_evidence": sorted(str(i) for i in only)} if only is not None else {}),
            })
    return hashes, failures


def _refusal(failures: list[dict[str, Any]]) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, {
        "message": "Hash verification failed; report refused. The stored original no longer "
                   "matches its ingest hash.",
        "failed_evidence": failures,
    })


def _store_report(db: Session, me: CurrentUser, case: Case, subject: EvidenceItem | None,
                  hashes: list[dict[str, Any]]) -> Report:
    """Render, store and register one report. Caller holds the case row lock."""
    scope = Report.evidence_id.is_(None) if subject is None else Report.evidence_id == subject.id
    version = (db.execute(select(func.max(Report.version)).where(Report.case_id == case.id, scope))
               .scalar_one() or 0) + 1
    context = builder.collect(db, get_store(), case, me.actor, version, hashes, subject)
    built = builder.render(context, pdf=True)
    assert built.pdf is not None
    digest = builder.pdf_sha256(built.pdf)
    report_id = uuid.uuid4()
    prefix = f"cases/{case.id}/reports" if subject is None else f"cases/{case.id}/reports/items/{subject.id}"
    key = f"{prefix}/v{version}-{report_id}.pdf"
    get_store().put_bytes(get_settings().bucket_reports, key, built.pdf, "application/pdf")
    row = Report(id=report_id, case_id=case.id, evidence_id=subject.id if subject else None,
                 version=version, status=built.status, pdf_storage_key=key, pdf_sha256=digest,
                 evidence_hashes=built.evidence_hashes, generated_by_id=me.id, signed_by=built.signed_by)
    db.add(row)
    db.flush()
    audit.record(db, me.actor, "report.generated", "case", case.id, {
        "report_id": str(report_id), "version": version, "status": built.status,
        "scope": "case" if subject is None else "item",
        **({"evidence_id": str(subject.id)} if subject else {}),
        "pdf_sha256": digest,
        "evidence_sha256": {h["evidence_id"]: h["sha256"] for h in built.evidence_hashes},
    })
    return row


def _questioned(item: EvidenceItem) -> EvidenceItem:
    if item.kind != EvidenceKind.QUESTIONED:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "reports are made for questioned items; a reference item is included "
                            "in the report of each questioned item it is linked to")
    return item


def _lock(db: Session, case: Case) -> None:
    db.execute(select(Case.id).where(Case.id == case.id).with_for_update())


@router.post("/cases/{case_id}/reports", response_model=ReportOut,
             status_code=status.HTTP_201_CREATED)
def generate_report(case_id: uuid.UUID, db: DB, me: Me) -> ReportOut:
    """One combined report for the whole case."""
    case = load_case(db, me, case_id, Action.REPORT_GENERATE)
    hashes, failures = _verify(case.id, me.actor, None)
    if failures:
        raise _refusal(failures)
    _lock(db, case)
    return ReportOut.model_validate(_store_report(db, me, case, None, hashes))


@router.post("/evidence/{evidence_id}/reports", response_model=ReportOut,
             status_code=status.HTTP_201_CREATED)
def generate_item_report(evidence_id: uuid.UUID, db: DB, me: Me) -> ReportOut:
    """A separate report for one questioned item (plus its linked references)."""
    item = _questioned(load_evidence(db, me, evidence_id, Action.REPORT_GENERATE))
    case = db.get(Case, item.case_id)
    assert case is not None
    hashes, failures = _verify(case.id, me.actor, builder.scope_ids(db, item))
    if failures:
        raise _refusal(failures)
    _lock(db, case)
    return ReportOut.model_validate(_store_report(db, me, case, item, hashes))


@router.post("/cases/{case_id}/reports/per-item", response_model=PerItemReportsOut,
             status_code=status.HTTP_201_CREATED)
def generate_all_item_reports(case_id: uuid.UUID, db: DB, me: Me) -> PerItemReportsOut:
    """A separate report for every questioned item in the case.

    Each item is re-verified on its own: an item whose hash check fails is refused and
    listed, and does not stop the reports of the other items.
    """
    case = load_case(db, me, case_id, Action.REPORT_GENERATE)
    items = list(db.execute(select(EvidenceItem).where(
        EvidenceItem.case_id == case.id, EvidenceItem.kind == EvidenceKind.QUESTIONED)
        .order_by(EvidenceItem.ingested_at)).scalars())
    if not items:
        raise HTTPException(status.HTTP_409_CONFLICT, "the case has no questioned items to report on")
    checked = [(item, *_verify(case.id, me.actor, builder.scope_ids(db, item))) for item in items]
    _lock(db, case)
    generated: list[ReportOut] = []
    refused: list[dict[str, Any]] = []
    for item, hashes, failures in checked:
        if failures:
            refused.append({"evidence_id": str(item.id), "filename": item.original_filename,
                            "failed_evidence": [f["evidence_id"] for f in failures]})
        else:
            generated.append(ReportOut.model_validate(_store_report(db, me, case, item, hashes)))
    return PerItemReportsOut(generated=generated, refused=refused)


@router.get("/cases/{case_id}/reports", response_model=list[ReportOut])
def list_reports(case_id: uuid.UUID, db: DB, me: Me) -> list[ReportOut]:
    """Every report of the case: whole-case reports and single-item reports."""
    case = load_case(db, me, case_id, Action.REPORT_VIEW)
    rows = db.execute(select(Report).where(Report.case_id == case.id)
                      .order_by(Report.evidence_id.nulls_first(), Report.version))
    return [ReportOut.model_validate(r) for r in rows.scalars()]


def _unverified_hashes(db: Session, items: list[EvidenceItem]) -> list[dict[str, Any]]:
    out = []
    for item in items:
        last = latest_verification(db, item.id)
        out.append(builder.hash_entry(item, iso(last.verified_at) if last else "not yet verified",
                                      bool(last and last.ok)))
    return out


def _preview_response(html: str) -> HTMLResponse:
    return HTMLResponse(html, headers={
        "Content-Security-Policy": "default-src 'none'; img-src data:; style-src 'unsafe-inline'",
    })


@router.get("/cases/{case_id}/report-preview", response_class=HTMLResponse)
def preview(case_id: uuid.UUID, db: DB, me: Me) -> HTMLResponse:
    """HTML preview of the next whole-case report (no re-verification, nothing stored)."""
    case = load_case(db, me, case_id, Action.REPORT_GENERATE)
    items = list(db.execute(select(EvidenceItem).where(EvidenceItem.case_id == case.id)
                            .order_by(EvidenceItem.ingested_at)).scalars())
    context = builder.collect(db, get_store(), case, me.actor, 0, _unverified_hashes(db, items))
    context["preview"] = True
    audit.record(db, me.actor, "report.previewed", "case", case.id)
    return _preview_response(builder.render(context, pdf=False).html)


@router.get("/evidence/{evidence_id}/report-preview", response_class=HTMLResponse)
def preview_item(evidence_id: uuid.UUID, db: DB, me: Me) -> HTMLResponse:
    """HTML preview of the next single-item report for one questioned item."""
    item = _questioned(load_evidence(db, me, evidence_id, Action.REPORT_GENERATE))
    case = db.get(Case, item.case_id)
    assert case is not None
    ids = builder.scope_ids(db, item)
    items = list(db.execute(select(EvidenceItem).where(EvidenceItem.id.in_(ids))
                            .order_by(EvidenceItem.ingested_at)).scalars())
    context = builder.collect(db, get_store(), case, me.actor, 0, _unverified_hashes(db, items), item)
    context["preview"] = True
    audit.record(db, me.actor, "report.previewed", "case", case.id, {"evidence_id": str(item.id)})
    return _preview_response(builder.render(context, pdf=False).html)


def _pdf_name(db: Session, row: Report) -> str:
    if row.evidence_id is None:
        return f"safeface-report-v{row.version}.pdf"
    item = db.get(EvidenceItem, row.evidence_id)
    stem = item.original_filename.rsplit(".", 1)[0] if item else str(row.evidence_id)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in stem)[:60] or "item"
    return f"safeface-report-{safe}-v{row.version}.pdf"


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
        "Content-Disposition": f'attachment; filename="{_pdf_name(db, row)}"',
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
