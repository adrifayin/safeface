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
    DOUBT: "Signs of AI manipulation found — refer to an examiner",
    NO_DOUBT: "No signs of AI manipulation found by the automated checks",
    INCOMPLETE: "Not enough results yet — the main checks have not finished",
}

QUESTIONS = [
    ("ai_generated", "Was it made by AI?", "AI-generated"),
    ("edited", "Has it been edited or tampered with?", "edited / tampered"),
    ("face_swap", "Is a face swapped or faked (deepfake)?", "face swap / deepfake"),
    ("voice", "Is the voice synthetic or cloned?", "synthetic voice"),
]
# Detector scores that estimate a likelihood (0-1) for each question, main detector first.
LIKELIHOOD: dict[str, list[tuple[str, str, str]]] = {
    "ai_generated": [("video.aigen.cakelens", "ai_likelihood", "CakeLens AI-video detector"),
                     ("image.aigen.commfor", "ai_likelihood", "Community Forensics"),
                     ("video.aigen", "ai_likelihood", "Community Forensics (frames)"),
                     ("image.aigen.univfd", "probability_generated", "UnivFD"),
                     ("image.aigen.npr", "probability_generated", "NPR"),
                     ("video.aigen", "univfd_mean", "UnivFD (frames)"),
                     ("video.aigen", "npr_mean", "NPR (frames)")],
    "edited": [("image.trufor", "integrity_score", "TruFor")],
    "face_swap": [("video.face_frame_scores", "mean_frame_score", "SBI face-swap")],
    "voice": [("audio.spoof", "mean_spoof_score", "AASIST")],
}


def provenance_declaration(latest: dict[str, Any]) -> dict[str, Any] | None:
    """An AI-generation label written into the file by the generating service, if present.

    Signed C2PA Content Credentials (Google Veo/Gemini, OpenAI, Adobe Firefly, ...) or the AIGC
    implicit label (MiniMax/Hailuo, Kling, ...). These are the producer's own statements, so they
    outrank pixel detectors; they disappear when a platform re-encodes the file (e.g. WhatsApp)."""
    def val(mid: str, name: str) -> Any:
        f = latest.get(mid)
        return next((s["value"] for s in f.scores if s["name"] == name), None) if f else None

    if val("image.c2pa", "ai_generation_declared") == 1:
        f = latest["image.c2pa"]
        sig = (f.details or {}).get("signature_info") or {}
        valid = val("image.c2pa", "signature_valid") == 1
        return {"detector": f"Signed AI label in the file (C2PA, {sig.get('issuer') or 'unknown issuer'}"
                            f"{'' if valid else ', signature NOT valid'})",
                "module_id": "image.c2pa", "likelihood": 0.99 if valid else 0.9}
    if val("video.container", "aigc_label") == 1:
        f = latest["video.container"]
        who = ((f.details or {}).get("aigc_label") or {}).get("producer", "AI service")
        return {"detector": f"AI label in the file (AIGC tag, {who})", "module_id": "video.container",
                "likelihood": 0.97}
    return None


def band(p: float) -> str:
    return "high" if p >= 0.7 else "medium" if p >= 0.4 else "low"


APPLIES = {"ai_generated": {"image", "video"}, "edited": {"image", "video", "audio"},
           "face_swap": {"video", "image"}, "voice": {"audio", "video"}}

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
        q = module.question_for(reason) if reason else module.question
        if reason:
            flags.append({"module_id": module_id, "check": module.name, "reason": reason,
                          "finding_id": str(f.id), "question": q})
        head = getattr(module, "headline", None)
        score = next((s for s in f.scores if head and s["name"] == head[0]), None)
        checks.append({
            "module_id": module_id, "check": module.name, "family": module.family.value,
            "plain": getattr(module, "plain", ""), "triage_indicator": module.triage_indicator,
            "score_name": score["name"] if score else None, "value": score["value"] if score else None,
            "range": score["range"] if score else None, "meaning": score["meaning"] if score else "",
            "threshold": head[1] if head else None, "flagged": bool(reason), "reason": reason or "",
            "summary": f.summary, "question": q, "core": module.screening_core or module.id == "image.source_match",
        })
    order = {fam: i for i, fam in enumerate(["INTEGRITY", "PROVENANCE", "COMPARISON", "CLASSICAL", "AI_DETECTOR",
                                             "AV", "AUDIO"])}
    checks.sort(key=lambda c: (order.get(c["family"], 9), c["check"]))

    core = [m for m in modules.values() if m.screening_core and MediaType(item.media_type) in m.media_types]
    core_done = [m for m in core if m.id in latest]
    core_missing = [m.name for m in core if m.id not in latest]
    questions = []
    for key, text, short in QUESTIONS:
        if item.media_type not in APPLIES[key]:
            continue
        ran = [c for c in checks if c["question"] == key]
        hits = [c for c in ran if c["flagged"]]
        if hits:
            answer = "signs_found"
        elif any(c["core"] for c in ran):
            answer = "no_signs"  # the main detector for this question ran and found nothing
        elif ran:
            answer = "partly_checked"  # only supporting checks ran
        else:
            answer = "not_checked"
        values = []
        for mid, score_name, label in LIKELIHOOD[key]:
            f = latest.get(mid)
            v = next((s["value"] for s in f.scores if s["name"] == score_name), None) if f else None
            if v is not None:
                values.append({"detector": label, "module_id": mid, "likelihood": round(float(v), 4)})
        if key == "ai_generated":
            declared = provenance_declaration(latest)
            if declared:
                values.insert(0, declared)
        main = values[0]["likelihood"] if values else None
        questions.append({
            "key": key, "question": text, "short": short, "answer": answer,
            "likelihood": main, "likelihood_band": band(main) if main is not None else None,
            "likelihood_source": values[0]["detector"] if values else None, "detector_scores": values,
            "checks_run": len(ran), "checks_flagged": len(hits),
            "reasons": [c["reason"] for c in hits],
            "checks": [c["check"] for c in ran],
        })
    found = [str(q["short"]) for q in questions if q["answer"] == "signs_found"]
    rated = [q for q in questions if q["likelihood"] is not None]
    top = max(rated, key=lambda q: float(q["likelihood"])) if rated else None  # type: ignore[arg-type]

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
        "answer_line": (f"Signs found: {', '.join(found)}." if found else
                        "No signs found by the checks that ran." if status == NO_DOUBT else
                        "Some checks are still running or unavailable."),
        "questions": questions,
        "overall_likelihood": top["likelihood"] if top else None,
        "overall_band": top["likelihood_band"] if top else None,
        "overall_question": top["short"] if top else None,
        "flags": flags,
        "checks_run": sorted(checked),
        "checks": checks,
        "detectors_without_result": core_missing,
        "pending": pending,
        "caveat": CAVEAT,
    }
