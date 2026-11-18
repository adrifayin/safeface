"""Analysis jobs, findings, artefacts and re-run reproducibility (FR-5.1, 5.2, 5.8)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import select

from app.api.deps import DB, Me, load_case, load_evidence
from app.api.schemas import AnalysisRequest, FamilyGroup, FindingsResponse, JobOut
from app.api.serialise import finding_out
from app.core import audit
from app.core.config import get_settings
from app.core.policy import Action, is_allowed
from app.core.storage import get_store
from app.db.models import EvidenceItem, FindingRow, Job
from app.modules.base import FAMILY_LABELS, FAMILY_ORDER
from app.services.analysis import create_jobs
from app.services.screening import CAVEAT, screen_item

router = APIRouter(tags=["analyses"])

NO_VERDICT_NOTICE = (
    "Each finding below is an independent test with its own limitations. Automated scores are "
    "indicators, not determinations. SafeFace never combines them into a real/fake verdict; "
    "only the examiner records a conclusion, which a supervisor must approve."
)
REPRODUCIBILITY_TOLERANCE = 1e-6


@router.post("/evidence/{evidence_id}/analyses", response_model=list[JobOut],
             status_code=status.HTTP_202_ACCEPTED)
def queue_analyses(evidence_id: uuid.UUID, body: AnalysisRequest, db: DB, me: Me) -> list[JobOut]:
    item = load_evidence(db, me, evidence_id, Action.ANALYSIS_TIER1)
    tiers = {1}
    if is_allowed(me.principal.roles, Action.ANALYSIS_TIER2, "analyse"):
        tiers.add(2)
    jobs = create_jobs(db, me.actor, me.id, item, body.module_ids, body.params,
                       body.reference_ids, tiers)
    return [JobOut.model_validate(j) for j in jobs]


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: uuid.UUID, db: DB, me: Me) -> JobOut:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    load_evidence(db, me, job.evidence_id, Action.CASE_VIEW)
    return JobOut.model_validate(job)


@router.get("/evidence/{evidence_id}/jobs", response_model=list[JobOut])
def list_jobs(evidence_id: uuid.UUID, db: DB, me: Me) -> list[JobOut]:
    item = load_evidence(db, me, evidence_id, Action.CASE_VIEW)
    jobs = db.execute(select(Job).where(Job.evidence_id == item.id).order_by(Job.queued_at)).scalars()
    return [JobOut.model_validate(j) for j in jobs]


@router.get("/evidence/{evidence_id}/findings", response_model=FindingsResponse)
def get_findings(evidence_id: uuid.UUID, db: DB, me: Me) -> FindingsResponse:
    item = load_evidence(db, me, evidence_id, Action.EVIDENCE_VIEW)
    rows = db.execute(
        select(FindingRow).where(FindingRow.evidence_id == item.id).order_by(FindingRow.created_at)
    ).scalars().all()
    jobs = db.execute(select(Job).where(Job.evidence_id == item.id).order_by(Job.queued_at)).scalars()
    audit.record(db, me.actor, "evidence.findings_viewed", "evidence", item.id,
                 {"finding_ids": [str(r.id) for r in rows]})
    groups = []
    for family in FAMILY_ORDER:
        members = [finding_out(r) for r in rows if r.family == family.value]
        if members:
            groups.append(FamilyGroup(family=family.value, label=FAMILY_LABELS[family],
                                      findings=members))
    return FindingsResponse(evidence_id=item.id, groups=groups,
                            jobs=[JobOut.model_validate(j) for j in jobs],
                            notice=NO_VERDICT_NOTICE)


@router.get("/evidence/{evidence_id}/screening")
def get_screening(evidence_id: uuid.UUID, db: DB, me: Me) -> dict[str, Any]:
    """Preliminary automated screening for one item (see services/screening.py)."""
    item = load_evidence(db, me, evidence_id, Action.EVIDENCE_VIEW)
    result = screen_item(db, item)
    audit.record(db, me.actor, "evidence.screening_viewed", "evidence", item.id,
                 {"status": result["status"], "flags": [f["module_id"] for f in result["flags"]]})
    return result


@router.get("/cases/{case_id}/screening")
def case_screening(case_id: uuid.UUID, db: DB, me: Me) -> dict[str, Any]:
    """Screening status of every questioned item in a case (for badges on the case page)."""
    case = load_case(db, me, case_id, Action.EVIDENCE_VIEW)
    items = db.execute(select(EvidenceItem).where(EvidenceItem.case_id == case.id,
                                                  EvidenceItem.kind == "questioned")).scalars()
    out = {str(i.id): screen_item(db, i) for i in items}
    audit.record(db, me.actor, "case.screening_viewed", "case", case.id,
                 {k: v["status"] for k, v in out.items()})
    return {"items": out, "caveat": CAVEAT}


@router.get("/artefacts/{key:path}")
def get_artefact(key: str, db: DB, me: Me) -> Response:
    """Serve one artefact after checking the caller may view its evidence item."""
    parts = key.split("/")
    if len(parts) != 4:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "artefact not found")
    try:
        case_id, evidence_id, finding_id = (uuid.UUID(p) for p in parts[:3])
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "artefact not found") from exc
    item = load_evidence(db, me, evidence_id, Action.EVIDENCE_VIEW)
    finding = db.get(FindingRow, finding_id)
    if item.case_id != case_id or finding is None or finding.evidence_id != item.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "artefact not found")
    meta = next((a for a in finding.artefacts if a["key"] == key), None)
    if meta is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "artefact not found")
    store = get_store()
    if not store.exists(get_settings().bucket_artefacts, key):
        raise HTTPException(status.HTTP_410_GONE, "figure purged after the 7-minute retention period; its SHA-256 "
                                                  "is kept in the finding. Re-run the analysis to regenerate it.")
    data = store.get_bytes(get_settings().bucket_artefacts, key)
    audit.record(db, me.actor, "evidence.artefact_viewed", "evidence", item.id,
                 {"finding_id": str(finding_id), "artefact": meta["name"]})
    return Response(data, media_type=meta["content_type"], headers={
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
    })


@router.post("/findings/{finding_id}/rerun", response_model=JobOut,
             status_code=status.HTTP_202_ACCEPTED)
def rerun_finding(finding_id: uuid.UUID, db: DB, me: Me) -> JobOut:
    """Re-run a past analysis with the same module version and parameters (FR-5.8)."""
    finding = db.get(FindingRow, finding_id)
    if finding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "finding not found")
    item = load_evidence(db, me, finding.evidence_id, Action.ANALYSIS_TIER1)
    job = db.get(Job, finding.job_id)
    assert job is not None
    from app.modules.registry import get_module

    if get_module(job.module_id).version != job.module_version:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "installed module version differs from the recorded version")
    tiers = {1, 2} if is_allowed(me.principal.roles, Action.ANALYSIS_TIER2, "analyse") else {1}
    (new_job,) = create_jobs(db, me.actor, me.id, item, [job.module_id], {job.module_id: job.params},
                             [uuid.UUID(r) for r in job.reference_ids], tiers, rerun_of=finding.id)
    return JobOut.model_validate(new_job)


@router.get("/findings/{finding_id}/reproducibility")
def reproducibility(finding_id: uuid.UUID, db: DB, me: Me) -> dict[str, Any]:
    """Compare a finding's scores with every re-run of it."""
    finding = db.get(FindingRow, finding_id)
    if finding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "finding not found")
    load_evidence(db, me, finding.evidence_id, Action.EVIDENCE_VIEW)
    reruns = db.execute(
        select(FindingRow).join(Job, Job.id == FindingRow.job_id)
        .where(Job.rerun_of_finding_id == finding.id)
    ).scalars().all()
    return {
        "finding_id": str(finding.id),
        "tolerance": REPRODUCIBILITY_TOLERANCE,
        "reruns": [compare_scores(finding, r) for r in reruns],
    }


def compare_scores(a: FindingRow, b: FindingRow) -> dict[str, Any]:
    va = {s["name"]: s["value"] for s in a.scores}
    vb = {s["name"]: s["value"] for s in b.scores}
    diffs: dict[str, float | None] = {}
    for name in sorted(set(va) | set(vb)):
        x, y = va.get(name), vb.get(name)
        diffs[name] = abs(x - y) if isinstance(x, int | float) and isinstance(y, int | float) else (
            0.0 if x == y else None)
    worst = max((d for d in diffs.values() if d is not None), default=0.0)
    reproduced = all(d is not None and d <= REPRODUCIBILITY_TOLERANCE for d in diffs.values())
    return {"rerun_finding_id": str(b.id), "max_abs_diff": worst, "diffs": diffs,
            "reproduced": reproduced}

