"""Helpers that build response models needing extra queries."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import ConclusionOut, EvidenceOut, FindingOut
from app.db.models import (
    CONCLUSION_LABELS,
    Conclusion,
    EvidenceItem,
    EvidenceReference,
    FindingRow,
)
from app.modules.registry import all_modules
from app.services.verification import latest_verification


def evidence_out(db: Session, item: EvidenceItem) -> EvidenceOut:
    out = EvidenceOut.model_validate(item)
    out.reference_ids = list(db.execute(
        select(EvidenceReference.reference_id).where(EvidenceReference.questioned_id == item.id)
    ).scalars())
    out.questioned_ids = list(db.execute(
        select(EvidenceReference.questioned_id).where(EvidenceReference.reference_id == item.id)
    ).scalars())
    last = latest_verification(db, item.id)
    if last:
        out.last_verification = {
            "ok": last.ok, "verified_at": last.verified_at.isoformat(), "reason": last.reason,
        }
    return out


def finding_out(row: FindingRow) -> FindingOut:
    out = FindingOut.model_validate(row)
    module = all_modules().get(row.module_id)
    if module:
        out.module_name = module.name
        out.triage_indicator = module.triage_indicator
    return out


def conclusion_out(db: Session, row: Conclusion) -> ConclusionOut:
    out = ConclusionOut.model_validate(row)
    out.scale_label = CONCLUSION_LABELS.get(row.scale_value, row.scale_value)
    out.author_name = row.author.display_name
    out.approved_by_name = row.approved_by.display_name if row.approved_by else None
    item = db.get(EvidenceItem, row.evidence_id)
    if item:
        out.case_id = item.case_id
        out.case_no = item.case.case_no
        out.evidence_filename = item.original_filename
    return out
