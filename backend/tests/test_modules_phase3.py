"""Phase 3 forensics: JPEG ghosts, FFT, PRNU, geometry (synthetic data only)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.modules.registry import all_modules, get_module
from tests.conftest import FIXTURES
from tests.module_harness import check_golden, run, score_map

EDITED = FIXTURES / "scene_edited.jpg"


def test_all_planned_modules_registered() -> None:
    expected = {"image.jpeg_ghost", "image.fft", "image.prnu", "image.geometry", "video.container", "video.aigen",
                "video.face_track", "video.face_frame_scores", "video.temporal", "video.av_sync",
                "video.phoneme_viseme", "video.rppg", "audio.spoof", "audio.spectrogram"}
    assert expected <= set(all_modules())
    assert "EXPERIMENTAL" in get_module("video.rppg").limitations


@pytest.mark.parametrize("module_id", ["image.jpeg_ghost", "image.fft"])
def test_golden(module_id: str, tmp_path: Path) -> None:
    f = run(get_module(module_id), EDITED, tmp_path)
    check_golden(f"{module_id}__scene_edited", f)


def test_jpeg_ghost_reports_dominant_quality(tmp_path: Path) -> None:
    s = score_map(run(get_module("image.jpeg_ghost"), EDITED, tmp_path))
    assert 80 <= s["dominant_quality"] <= 90  # fixture was last saved at quality 85  # type: ignore[operator]


def test_prnu_detects_fingerprint_and_missing_region(tmp_path: Path) -> None:
    rng = np.random.default_rng(7)
    h, w = 256, 256
    k = rng.normal(0, 0.03, (h, w))                     # synthetic sensor fingerprint
    refs = []
    for i in range(20):
        base = np.clip(120 + 60 * rng.random((h, w)), 0, 255)
        scene = np.clip(base * (1 + k) + rng.normal(0, 1, (h, w)), 0, 255).astype(np.uint8)
        p = tmp_path / f"ref{i}.png"
        Image.fromarray(np.stack([scene] * 3, -1)).save(p)
        refs.append(p)
    q = np.clip(np.full((h, w), 140.0) * (1 + k) + rng.normal(0, 1, (h, w)), 0, 255)
    q[64:192, 64:192] = np.clip(140 + rng.normal(0, 1, (128, 128)), 0, 255)  # pasted patch: no fingerprint
    qp = tmp_path / "q.png"
    Image.fromarray(np.stack([q.astype(np.uint8)] * 3, -1)).save(qp)
    f = run(get_module("image.prnu"), qp, tmp_path / "run", refs=refs, params={"block": 64})
    s = score_map(f)
    assert s["pce"] > 60  # type: ignore[operator]
    assert s["low_correlation_fraction"] >= 0.2  # the pasted quarter lacks the fingerprint  # type: ignore[operator]
    with pytest.raises(ValueError, match="at least 20"):
        run(get_module("image.prnu"), qp, tmp_path / "few", refs=refs[:5])


def test_geometry_flags_the_inconsistent_line(tmp_path: Path) -> None:
    vp = (320.0, -200.0)
    lines = []
    for x in (50, 150, 450, 600):  # lines through the vanishing point
        lines.append([x, 470, x + (vp[0] - x) * 0.5, 470 + (vp[1] - 470) * 0.5])
    lines.append([300, 470, 420, 260])  # does not pass through the vanishing point
    f = run(get_module("image.geometry"), EDITED, tmp_path, params={"lines": lines})
    s = score_map(f)
    assert s["inconsistent_lines"] == 1.0
    assert f.details["line_errors_deg"][-1] > 2.0 and max(f.details["line_errors_deg"][:4]) < 0.5
    assert get_module("image.geometry").screen(s, f.details)


def test_geometry_needs_lines(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least 3"):
        run(get_module("image.geometry"), EDITED, tmp_path, params={"lines": [[0, 0, 1, 1]]})


def test_speech_and_face_modules_unavailable_without_weights() -> None:
    for mid in ("video.av_sync", "video.phoneme_viseme", "video.temporal", "video.rppg"):
        assert not get_module(mid).availability().available, mid
