"""image.c2pa: C2PA Content Credentials (manifest presence and signature validity).

Uses the official ``c2patool`` CLI (Content Authenticity Initiative). Runs
offline: certificate trust is checked only against trust anchors installed
locally; without them a valid signature is reported as cryptographically
valid but "untrusted signer".
"""

from __future__ import annotations

import json
import shutil
from typing import Any

from app.modules._common.imaging import run_tool
from app.modules.base import Availability, Family, Finding, ModuleBase, Score, WorkingCopy

NO_MANIFEST_MARKERS = ("no claim found", "manifestnotfound", "no manifest", "jumbfnotfound",
                       "manifest not found", "no c2pa")
TRUST_CODES = ("signingcredential.untrusted", "signingcredential.ocsp")
AI_SOURCE = "trainedalgorithmicmedia"


def _failures(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect validation failures from both old and new c2patool report formats."""
    failures: list[dict[str, Any]] = list(report.get("validation_status") or [])
    results = report.get("validation_results") or {}
    active = results.get("activeManifest") or {}
    failures += list(active.get("failure") or [])
    for ingredient in results.get("ingredientDeltas") or []:
        failures += list((ingredient.get("validationDeltas") or {}).get("failure") or [])
    return failures


def _find_ai_declaration(obj: Any) -> bool:
    if isinstance(obj, dict):
        return any(_find_ai_declaration(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_find_ai_declaration(v) for v in obj)
    return isinstance(obj, str) and AI_SOURCE in obj.lower()


class C2PA(ModuleBase):
    id = "image.c2pa"
    version = "1.0.0"
    name = "C2PA Content Credentials"
    description = (
        "c2patool reads any embedded C2PA manifest store, validates the claim signature and "
        "assertion hashes, and reports the claim generator, signer and declared actions."
    )
    family = Family.PROVENANCE
    tier = 1
    limitations = (
        "Most image tools, and almost all abusive or 'nudify' tools, add no C2PA provenance, and "
        "platforms usually strip it, so absence of a manifest says nothing about authenticity. A "
        "valid manifest shows who signed the claims and that the file has not changed since "
        "signing; it does not prove the claims are true. Signer trust is evaluated only against "
        "locally installed trust anchors (the system is offline). Invisible watermarks (e.g. "
        "SynthID) are not checked: no offline decoder is available."
    )

    def availability(self) -> Availability:
        if shutil.which("c2patool") is None:
            return Availability(False, "c2patool is not installed in the worker image")
        return Availability(True)

    def run(self, item: WorkingCopy, refs: list[WorkingCopy], params: dict[str, Any]) -> Finding:
        self.merged_params(params)
        version = run_tool(["c2patool", "--version"], timeout=10).stdout.decode().strip()
        res = run_tool(["c2patool", str(item.path)], timeout=120, cwd=item.workdir)
        stdout = res.stdout.decode("utf-8", errors="replace")
        stderr = res.stderr.decode("utf-8", errors="replace")
        provenance = {"tools": {"c2patool": version}}

        report: dict[str, Any] | None = None
        if stdout.strip().startswith("{"):
            try:
                report = json.loads(stdout)
            except json.JSONDecodeError:
                report = None
        if report is None or not report.get("manifests"):
            text = (stdout + stderr).lower().replace(" ", "")
            if any(m.replace(" ", "") in text for m in NO_MANIFEST_MARKERS) or res.returncode == 0:
                return Finding(
                    scores=[
                        Score("manifest_present", 0.0, (0, 1), "1 = a C2PA manifest is embedded."),
                        Score("signature_valid", None, (0, 1), "Not applicable: no manifest."),
                        Score("signer_trusted", None, (0, 1), "Not applicable: no manifest."),
                        Score("ai_generation_declared", None, (0, 1), "Not applicable: no manifest."),
                    ],
                    summary="No C2PA manifest found. (Absence is normal and is not evidence either way.)",
                    limitations=self.limitations, details={"tool_output": stderr[:2000]},
                    provenance=provenance,
                )
            raise RuntimeError(f"c2patool failed (exit {res.returncode}): {stderr[:300]}")

        failures = _failures(report)
        codes = [str(f.get("code", "")).lower() for f in failures]
        integrity_failures = [c for c in codes if not c.startswith(TRUST_CODES)]
        untrusted = any(c.startswith(TRUST_CODES) for c in codes)
        state = str(report.get("validation_state", "")).lower()
        active_label = report.get("active_manifest")
        active = (report.get("manifests") or {}).get(active_label, {}) if active_label else {}
        sig = active.get("signature_info") or {}
        ai_declared = _find_ai_declaration(active.get("assertions") or [])
        sig_valid = 0.0 if integrity_failures else 1.0
        if state:  # newer c2patool: "invalid" | "valid" | "trusted"
            trusted = 1.0 if state == "trusted" else 0.0
        else:      # older c2patool lists only failures
            trusted = 0.0 if (untrusted or integrity_failures) else 1.0

        summary = (f"C2PA manifest present (generator: {active.get('claim_generator') or 'unknown'}; "
                   f"signer: {sig.get('issuer') or sig.get('common_name') or 'unknown'}). Signature and "
                   f"hashes {'VALID' if sig_valid else 'INVALID: ' + ', '.join(integrity_failures)}; "
                   f"signer {'trusted' if trusted else 'not in the local trust list'}."
                   + (" The manifest declares AI-generated content." if ai_declared else ""))
        return Finding(
            scores=[
                Score("manifest_present", 1.0, (0, 1), "1 = a C2PA manifest is embedded."),
                Score("signature_valid", sig_valid, (0, 1),
                      "1 = claim signature and content hashes validate (file unchanged since signing)."),
                Score("signer_trusted", trusted, (0, 1),
                      "1 = the signing certificate chains to a locally installed trust anchor."),
                Score("ai_generation_declared", 1.0 if ai_declared else 0.0, (0, 1),
                      "1 = an assertion declares digitalSourceType trainedAlgorithmicMedia (AI)."),
            ],
            summary=summary, limitations=self.limitations,
            details={"active_manifest": active_label, "validation_failures": failures,
                     "validation_state": report.get("validation_state"),
                     "signature_info": sig, "claim_generator": active.get("claim_generator"),
                     "manifest_store": report},
            provenance=provenance,
        )


MODULE = C2PA()
