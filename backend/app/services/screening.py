"""Preliminary automated screening (agreed with the user, Phase 2 plan).

Purpose: tell police quickly whether any automated check raised a DOUBT that
an item may be AI-generated or tampered, so it is referred to an examiner.

It is deliberately NOT a verdict:
- it never says "fake", "real", "authentic" or "genuine";
- each flag names the check and the threshold that triggered it;
- thresholds are uncalibrated defaults until Phase 4 validation;
- the fixed caveat travels with the result everywhere it is shown;
- in the PDF it appears only as a preliminary appendix, never as the
  conclusion, which remains the examiner's, approved by a supervisor.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import EvidenceItem, FindingRow, Job, JobStatus
from app.modules.base import MediaType
from app.modules.registry import all_modules

DOUBT = "doubt_raised"
NO_DOUBT = "no_doubt_raised"
INCOMPLETE = "incomplete"

HEADLINES = {
    DOUBT: "Doubt raised — refer to an examiner",
    NO_DOUBT: "No doubt raised by the automated checks that ran",
    INCOMPLETE: "Screening incomplete — the main detectors have not produced a result",
}

CAVEAT = (
    "PRELIMINARY AUTOMATED SCREENING — NOT A FINDING. These checks are independent research tools "
    "with known accuracy problems: on real-world media their accuracy can drop by about half, they "
    "raise false alarms on genuine images and miss many manipulated ones, and messaging-app "
    "compression weakens them further. Thresholds are uncalibrated defaults. Use this only to decide "
    "whether to refer the item to a trained examiner; never as evidence or to accuse anyone."
)


def screen_item(session: Session, item: EvidenceItem) -> dict[str, Any]:
    modules = all_modules()
    findings = session.execute(select(FindingRow).where(FindingRow.evidence_id == item.id)
                               .order_by(FindingRow.created_at)).scalars()
    latest: dict[str, FindingRow] = {}
    for f in findings:
        latest[f.module_id] = f
    jobs = session.execute(select(Job).where(Job.evidence_id == item.id)).scalars().all()
    pending = sorted({j.module_id for j in jobs if j.status in (JobStatus.QUEUED, JobStatus.RUNNING)})

    flags: list[dict[str, str]] = []
    checked: list[str] = []
    checks: list[dict[str, Any]] = []
    for module_id, f in latest.items():
        module = modules.get(module_id)
        if module is None:
            continue
        checked.append(module.name)
        scores = {s["name"]: s["value"] for s in f.scores}
        reason = module.screen(scores, f.details)
        if reason:
            flags.append({"module_id": module_id, "check": module.name, "reason": reason,
                          "finding_id": str(f.id)})
        head = getattr(module, "headline", None)
        score = next((s for s in f.scores if head and s["name"] == head[0]), None)
        checks.append({
            "module_id": module_id, "check": module.name, "family": module.family.value,
            "plain": getattr(module, "plain", ""), "triage_indicator": module.triage_indicator,
            "score_name": score["name"] if score else None, "value": score["value"] if score else None,
            "range": score["range"] if score else None, "meaning": score["meaning"] if score else "",
            "threshold": head[1] if head else None, "flagged": bool(reason), "reason": reason or "",
            "summary": f.summary,
        })
    order = {fam: i for i, fam in enumerate(["INTEGRITY", "PROVENANCE", "COMPARISON", "CLASSICAL", "AI_DETECTOR",
                                             "AV", "AUDIO"])}
    checks.sort(key=lambda c: (order.get(c["family"], 9), c["check"]))

    core = [m for m in modules.values() if m.screening_core and MediaType(item.media_type) in m.media_types]
    core_done = [m for m in core if m.id in latest]
    core_missing = [m.name for m in core if m.id not in latest]
    if flags:
        status = DOUBT
    elif core and not core_done:
        status = INCOMPLETE
    else:
        status = NO_DOUBT
    return {
        "evidence_id": str(item.id),
        "status": status,
        "headline": HEADLINES[status],
        "flags": flags,
        "checks_run": sorted(checked),
        "checks": checks,
        "detectors_without_result": core_missing,
        "pending": pending,
        "caveat": CAVEAT,
    }
