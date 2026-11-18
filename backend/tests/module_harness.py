"""Run a module directly on a fixture file, as the worker would."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from app.core.environment import set_deterministic
from app.core.hashing import hash_file
from app.modules.base import AnalysisModule, Finding, MediaType, WorkingCopy

GOLDEN = Path(__file__).parent / "golden"
TOLERANCE = 1e-6


def working_copy(src: Path, tmp: Path, evidence_id: str = "fixture") -> WorkingCopy:
    d = tmp / evidence_id
    (d / "out").mkdir(parents=True, exist_ok=True)
    dest = d / f"item{src.suffix}"
    shutil.copyfile(src, dest)
    digests = hash_file(dest)
    return WorkingCopy(evidence_id, dest, digests.sha256, digests.md5, MediaType.IMAGE, src.name,
                       "questioned", digests.sha256, digests.md5, d / "out")


def run(module: AnalysisModule, src: Path, tmp: Path, refs: list[Path] | None = None,
        params: dict[str, Any] | None = None) -> Finding:
    set_deterministic(0)
    item = working_copy(src, tmp, "q")
    ref_items = [working_copy(r, tmp, f"r{i}") for i, r in enumerate(refs or [])]
    return module.run(item, ref_items, params or {})


def score_map(finding: Finding) -> dict[str, float | None]:
    return {s.name: s.value for s in finding.scores}


def check_golden(name: str, finding: Finding) -> None:
    """Compare scores with tests/golden/<name>.json (write it if SAFEFACE_UPDATE_GOLDENS=1)."""
    path = GOLDEN / f"{name}.json"
    scores = score_map(finding)
    if os.environ.get("SAFEFACE_UPDATE_GOLDENS") == "1":
        GOLDEN.mkdir(exist_ok=True)
        path.write_text(json.dumps(scores, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return
    assert path.exists(), f"missing golden {path}; run with SAFEFACE_UPDATE_GOLDENS=1 and review"
    expected = json.loads(path.read_text(encoding="utf-8"))
    assert set(expected) == set(scores), (expected.keys(), scores.keys())
    for k, v in expected.items():
        got = scores[k]
        if v is None or got is None:
            assert v == got, (k, v, got)
        else:
            assert abs(got - v) <= TOLERANCE, f"{name}.{k}: expected {v}, got {got}"
