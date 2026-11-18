"""Golden-output and determinism tests for the non-ML modules."""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.modules.registry import all_modules, get_module
from tests.conftest import FIXTURES
from tests.module_harness import check_golden, run, score_map

ORIGINAL = FIXTURES / "scene_original.jpg"
EDITED = FIXTURES / "scene_edited.jpg"
REFERENCE = FIXTURES / "scene_reference.jpg"
MASK = FIXTURES / "scene_edited_mask.png"
needs_tools = pytest.mark.skipif(shutil.which("exiftool") is None, reason="ExifTool not installed")


def test_registry_discovers_all_phase1_modules() -> None:
    expected = {"integrity.hash", "image.metadata", "image.c2pa", "image.ela", "image.noise",
                "image.trufor", "image.aigen.univfd", "image.aigen.npr", "image.source_match"}
    assert expected <= set(all_modules())
    for m in all_modules().values():
        assert m.limitations and len(m.limitations) > 40, m.id
        assert m.tier in (1, 2)


def test_ai_detectors_are_labelled_triage_indicators() -> None:
    for mid in ("image.aigen.univfd", "image.aigen.npr"):
        m = get_module(mid)
        assert m.triage_indicator and "TRIAGE INDICATOR" in m.limitations


@pytest.mark.parametrize("fixture", ["scene_original.jpg", "scene_edited.jpg"])
@pytest.mark.parametrize("module_id", ["integrity.hash", "image.ela", "image.noise"])
def test_golden(module_id: str, fixture: str, tmp_path: Path) -> None:
    finding = run(get_module(module_id), FIXTURES / fixture, tmp_path)
    check_golden(f"{module_id}__{Path(fixture).stem}", finding)
    for art in finding.artefacts:
        assert art.path.exists() and art.path.stat().st_size > 0
        if art.kind.value == "heatmap":
            with Image.open(art.path) as im:
                assert im.size == Image.open(FIXTURES / fixture).size


@pytest.mark.parametrize("module_id", ["integrity.hash", "image.ela", "image.noise", "image.source_match"])
def test_deterministic_reruns(module_id: str, tmp_path: Path) -> None:
    refs = [REFERENCE] if module_id == "image.source_match" else None
    a = score_map(run(get_module(module_id), EDITED, tmp_path / "a", refs))
    b = score_map(run(get_module(module_id), EDITED, tmp_path / "b", refs))
    for k in a:
        if a[k] is None:
            assert b[k] is None
        else:
            assert abs(a[k] - b[k]) <= 1e-6, k  # type: ignore[operator]


def test_noise_map_flags_smoothed_regions(tmp_path: Path) -> None:
    edited = score_map(run(get_module("image.noise"), EDITED, tmp_path / "e"))
    original = score_map(run(get_module("image.noise"), ORIGINAL, tmp_path / "o"))
    # The pasted object and the inpainted area carry no sensor noise.
    assert edited["low_noise_fraction"] > original["low_noise_fraction"]  # type: ignore[operator]


def test_source_match_localises_the_edit(tmp_path: Path) -> None:
    finding = run(get_module("image.source_match"), EDITED, tmp_path, refs=[REFERENCE])
    check_golden("image.source_match__scene_edited", finding)
    s = score_map(finding)
    assert s["inlier_count"] >= 50  # type: ignore[operator]
    diff = finding.artefacts[0]
    assert diff.name == "aligned_difference.png"
    heat = np.asarray(Image.open(diff.path).convert("L"), dtype=np.float64)
    mask = np.asarray(Image.open(MASK)) > 0
    # The difference is far stronger inside the edited regions than outside them.
    assert heat[mask].mean() > 3 * heat[~mask].mean()


def test_source_match_rejects_unrelated_reference(tmp_path: Path) -> None:
    noise = tmp_path / "unrelated.png"
    rng = np.random.default_rng(1)
    Image.fromarray(rng.integers(0, 255, (480, 640, 3), dtype=np.uint8)).save(noise)
    s = score_map(run(get_module("image.source_match"), EDITED, tmp_path / "x", refs=[noise]))
    assert s["mean_aligned_difference"] is None and s["inlier_count"] < 15  # type: ignore[operator]


@needs_tools
def test_metadata_detects_editing_software(tmp_path: Path) -> None:
    finding = run(get_module("image.metadata"), EDITED, tmp_path)
    check_golden("image.metadata__scene_edited", finding)
    s = score_map(finding)
    assert s["editing_software_tag"] == 1.0
    assert s["missing_camera_fields"] == 7.0
    checks = {a["check"] for a in finding.details["anomalies"]}
    assert {"editing_software", "missing_camera_fields"} <= checks
    assert finding.details["quantization"]["luma_quality"] == 85


@needs_tools
def test_metadata_camera_original(tmp_path: Path) -> None:
    finding = run(get_module("image.metadata"), ORIGINAL, tmp_path)
    check_golden("image.metadata__scene_original", finding)
    s = score_map(finding)
    assert s["editing_software_tag"] == 0.0 and s["missing_camera_fields"] == 0.0
    assert finding.details["quantization"]["luma_quality"] == 92
    assert finding.details["quantization"]["standard_ijg"] is True


@pytest.mark.skipif(shutil.which("c2patool") is None, reason="c2patool not installed")
def test_c2pa_reports_absence(tmp_path: Path) -> None:
    finding = run(get_module("image.c2pa"), ORIGINAL, tmp_path)
    s = score_map(finding)
    assert s["manifest_present"] == 0.0 and s["signature_valid"] is None
    assert "not evidence either way" in finding.summary


def test_unknown_params_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown parameters"):
        run(get_module("image.ela"), ORIGINAL, tmp_path, params={"qualty": 80})
