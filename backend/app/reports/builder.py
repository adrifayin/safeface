"""Build a report: either the whole case, or one questioned item.

A single-item report covers that questioned item plus the reference items
linked to it (their hashes appear in the integrity table; references have no
findings of their own).

Before anything is rendered, every evidence item the report covers is re-hashed
from storage (FR-1.6). If any hash fails, no report is produced.

The report is FINAL only when every questioned item it covers has a latest
conclusion approved by a supervisor; otherwise it is watermarked DRAFT.

WeasyPrint is given a URL fetcher that refuses everything except inline
``data:`` URIs, so rendering can never reach the network.
"""

from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import __version__
from app.core.config import get_settings
from app.core.hashing import sha256_bytes
from app.core.storage import ObjectStore
from app.core.timeutil import iso, utcnow
from app.db.models import (
    CONCLUSION_LABELS,
    Case,
    Conclusion,
    EvidenceItem,
    EvidenceKind,
    EvidenceReference,
    ExaminerNote,
    FindingRow,
    User,
)
from app.modules.base import FAMILY_LABELS, FAMILY_ORDER, Family
from app.modules.registry import all_modules
from app.modules.weights import all_validation, validation_summary
from app.services.screening import screen_item
from app.services.verification import verify_item

TEMPLATES = Path(__file__).parent / "templates"

INDICATOR_STATEMENT = (
    "Automated scores in this report are indicators, not determinations. Each analysis module is "
    "an independent test with stated limitations; no module, and no combination of modules, "
    "establishes on its own whether an item is authentic or manipulated. The conclusion is the "
    "examiner's professional opinion, recorded on a fixed scale and approved by a supervisor."
)


@dataclass
class BuiltReport:
    html: str
    pdf: bytes | None
    status: str
    evidence_hashes: list[dict[str, Any]]
    signed_by: list[dict[str, Any]]


def _refuse_network(url: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
    if not url.startswith("data:"):
        raise ValueError(f"report rendering may not fetch external resources: {url[:60]}")
    from weasyprint import default_url_fetcher

    result: dict[str, Any] = default_url_fetcher(url)
    return result


def _env() -> Environment:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html", "j2"]))
    env.filters["iso"] = lambda d: iso(d) if d else ""
    return env


def _fmt_score(value: Any) -> str:
    if value is None:
        return "not computed"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _user_name(db: Session, user_id: uuid.UUID | None) -> str:
    if user_id is None:
        return ""
    u = db.get(User, user_id)
    return f"{u.display_name} ({u.username})" if u else str(user_id)


def scope_ids(db: Session, item: EvidenceItem) -> set[uuid.UUID]:
    """The items a single-item report covers: the questioned item and its references."""
    refs = db.execute(select(EvidenceReference.reference_id).where(
        EvidenceReference.questioned_id == item.id)).scalars()
    return {item.id, *refs}


def _items(db: Session, case: Case, only: set[uuid.UUID] | None) -> list[EvidenceItem]:
    q = select(EvidenceItem).where(EvidenceItem.case_id == case.id)
    if only is not None:
        q = q.where(EvidenceItem.id.in_(only))
    return list(db.execute(q.order_by(EvidenceItem.ingested_at)).scalars())


def hash_entry(item: EvidenceItem, verified_at: str, verified_ok: bool) -> dict[str, Any]:
    return {
        "evidence_id": str(item.id), "filename": item.original_filename, "kind": item.kind,
        "media_type": item.media_type, "detected_mime": item.detected_mime,
        "size_bytes": item.size_bytes, "sha256": item.sha256, "md5": item.md5,
        "verified_at": verified_at, "verified_ok": verified_ok,
        "ingested_at": iso(item.ingested_at), "source_url": item.source_url,
        "source_platform": item.source_platform, "source_device": item.source_device,
        "complainant": item.complainant, "collected_by": item.collected_by,
        "collected_at": iso(item.collected_at) if item.collected_at else None,
        "upload_method": item.upload_method,
    }


def verify_case(
    db: Session, store: ObjectStore, case: Case, actor: str, only: set[uuid.UUID] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Re-hash every item in the case (or only ``only``). Returns (evidence_hashes, failures)."""
    items = _items(db, case, only)
    evidence_hashes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for item in items:
        rows = verify_item(db, store, item, actor, "pre-report")
        original = next(r for r in rows if r.target == "original")
        entry = hash_entry(item, iso(original.verified_at), all(r.ok for r in rows))
        evidence_hashes.append(entry)
        if not entry["verified_ok"]:
            failures.append(entry)
    return evidence_hashes, failures


def collect(
    db: Session, store: ObjectStore, case: Case, actor: str, version: int,
    evidence_hashes: list[dict[str, Any]], subject: EvidenceItem | None = None,
) -> dict[str, Any]:
    """Gather everything the template needs. Call only after :func:`verify_case` passed.

    With ``subject`` the report covers that one questioned item (and its references).
    """
    settings = get_settings()
    items = _items(db, case, scope_ids(db, subject) if subject is not None else None)

    modules = all_modules()
    benchmarks = all_validation(db)
    sections = []
    environments: dict[str, dict[str, Any]] = {}
    all_final = True
    signed_by: list[dict[str, Any]] = []

    for item in items:
        if item.kind != EvidenceKind.QUESTIONED:
            continue
        findings = list(db.execute(select(FindingRow).where(FindingRow.evidence_id == item.id)
                                   .order_by(FindingRow.created_at)).scalars())
        # Latest finding per module (re-runs are listed in provenance, not repeated).
        latest: dict[str, FindingRow] = {}
        for f in findings:
            latest[f.module_id] = f
        groups = []
        for family in FAMILY_ORDER:
            fam = [f for f in latest.values() if f.family == family.value]
            if not fam:
                continue
            rendered = []
            for f in fam:
                env_key = f"{f.provenance.get('environment', {}).get('host', '?')}|" \
                          f"{f.provenance.get('environment', {}).get('container_image_digest', '?')}"
                environments[env_key] = f.provenance.get("environment", {})
                figures = []
                for art in f.artefacts:
                    if art["content_type"] == "image/png":
                        if not store.exists(settings.bucket_artefacts, art["key"]):
                            figures.append({"name": art["name"], "description": art["description"],
                                            "sha256": art["sha256"], "src": None})
                            continue
                        data = store.get_bytes(settings.bucket_artefacts, art["key"])
                        figures.append({
                            "name": art["name"], "description": art["description"],
                            "sha256": art["sha256"],
                            "src": "data:image/png;base64," + base64.b64encode(data).decode(),
                        })
                notes = db.execute(select(ExaminerNote).where(ExaminerNote.finding_id == f.id)
                                   .order_by(ExaminerNote.created_at)).scalars()
                m = modules.get(f.module_id)
                rendered.append({
                    "id": f.id, "module_id": f.module_id, "module_version": f.module_version,
                    "name": m.name if m else f.module_id,
                    "method": m.description if m else "",
                    "triage_indicator": bool(m and m.triage_indicator),
                    "tier": f.tier, "summary": f.summary, "limitations": f.limitations,
                    "params": f.provenance.get("params", {}),
                    "weights": f.provenance.get("weights", {}),
                    "runtime": f.provenance.get("runtime_seconds"),
                    "finished_at": f.provenance.get("finished_at"),
                    "scores": [{**s, "display": _fmt_score(s["value"])} for s in f.scores],
                    "figures": figures,
                    "validation": (validation_summary(benchmarks[f.module_id][-1]) if benchmarks.get(f.module_id)
                                   else "Not yet validated on the SafeFace test set (Phase 4 benchmark pending)."),
                    "notes": [{"author": _user_name(db, n.author_id), "text": n.text,
                               "created_at": n.created_at} for n in notes],
                })
            groups.append({"label": FAMILY_LABELS[Family(family)], "findings": rendered})

        general_notes = db.execute(select(ExaminerNote).where(
            ExaminerNote.evidence_id == item.id, ExaminerNote.finding_id.is_(None))
            .order_by(ExaminerNote.created_at)).scalars()
        conclusion = db.execute(select(Conclusion).where(Conclusion.evidence_id == item.id)
                                .order_by(Conclusion.created_at.desc()).limit(1)).scalar_one_or_none()
        if conclusion is None or conclusion.approved_at is None:
            all_final = False
        else:
            signed_by.append({
                "evidence_id": str(item.id),
                "examiner": _user_name(db, conclusion.author_id),
                "supervisor": _user_name(db, conclusion.approved_by_id),
                "approved_at": iso(conclusion.approved_at),
            })
        refs = list(db.execute(select(EvidenceReference.reference_id).where(
            EvidenceReference.questioned_id == item.id)).scalars())
        sections.append({
            "item": item,
            "screening": screen_item(db, item),
            "references": [str(r) for r in refs],
            "groups": groups,
            "general_notes": [{"author": _user_name(db, n.author_id), "text": n.text,
                               "created_at": n.created_at} for n in general_notes],
            "conclusion": None if conclusion is None else {
                "label": CONCLUSION_LABELS.get(conclusion.scale_value, conclusion.scale_value),
                "rationale": conclusion.rationale,
                "author": _user_name(db, conclusion.author_id),
                "created_at": conclusion.created_at,
                "approved_by": _user_name(db, conclusion.approved_by_id),
                "approved_at": conclusion.approved_at,
                "approval_comment": conclusion.approval_comment,
            },
        })

    if not sections:
        all_final = False

    return {
        "case": case,
        "subject": subject,
        "investigator": _user_name(db, case.created_by_id),
        "examiner": _user_name(db, case.assigned_examiner_id),
        "version": version,
        "status": "final" if all_final else "draft",
        "generated_at": iso(utcnow()),
        "generated_by": actor,
        "app_version": __version__,
        "deployment": settings.deployment_name,
        "api_image_digest": settings.image_digest,
        "environments": list(environments.values()),
        "evidence": evidence_hashes,
        "sections": sections,
        "indicator_statement": INDICATOR_STATEMENT,
        "signed_by": signed_by,
        "scale": list(CONCLUSION_LABELS.values()),
    }


def render(context: dict[str, Any], pdf: bool = True) -> BuiltReport:
    html = _env().get_template("report.html.j2").render(**context)
    pdf_bytes = None
    if pdf:
        from weasyprint import HTML

        pdf_bytes = HTML(string=html, url_fetcher=_refuse_network, base_url=None).write_pdf()
    return BuiltReport(html, pdf_bytes, context["status"], context["evidence"], context["signed_by"])


def pdf_sha256(data: bytes) -> str:
    return sha256_bytes(data)
