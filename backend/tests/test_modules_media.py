"""Video and audio modules on synthetic fixtures (no people, nothing explicit)."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.core.hashing import hash_file, sha256_file
from app.modules import weights
from app.modules.base import MediaType, WorkingCopy
from app.modules.registry import get_module
from tests.conftest import FIXTURES
from tests.module_harness import check_golden, score_map

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None or not (FIXTURES / "scene_video.mp4").exists(),
                                reason="ffmpeg / video fixture not available")
torch = pytest.importorskip("torch")
VIDEO = FIXTURES / "scene_video.mp4"
AUDIO = FIXTURES / "tone.wav"


def media_copy(src: Path, tmp: Path, media: MediaType) -> WorkingCopy:
    (tmp / "out").mkdir(parents=True, exist_ok=True)
    dest = tmp / f"item{src.suffix}"
    shutil.copyfile(src, dest)
    d = hash_file(dest)
    return WorkingCopy("m", dest, d.sha256, d.md5, media, src.name, "questioned", d.sha256, d.md5, tmp / "out")


def run(module_id: str, src: Path, tmp: Path, media: MediaType):  # type: ignore[no-untyped-def]
    from app.core.environment import set_deterministic

    set_deterministic(0)
    return get_module(module_id).run(media_copy(src, tmp, media), [], {})


@pytest.fixture
def models_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    import yaml

    from app.modules._vendor.npr_resnet import NPRNet
    from app.modules.audio_spoof import AASIST_CONFIG

    root = tmp_path / "models"
    (root / "w").mkdir(parents=True)
    torch.manual_seed(0)
    torch.save(NPRNet().state_dict(), root / "w" / "npr.pth")
    from app.modules._vendor.aasist import Model

    torch.save(Model(AASIST_CONFIG).state_dict(), root / "w" / "aasist.pth")
    entries = [{"name": n, "module_id": "x", "version": "t", "path": f"w/{f}", "sha256": sha256_file(root / "w" / f),
                "licence": "test"} for n, f in (("npr", "npr.pth"), ("aasist", "aasist.pth"))]
    (root / "registry.yaml").write_text(yaml.safe_dump({"weights": entries}))
    monkeypatch.setattr(get_settings(), "models_dir", str(root))
    weights.load_registry.cache_clear()
    yield root
    weights.load_registry.cache_clear()


def test_video_container(tmp_path: Path) -> None:
    f = run("video.container", VIDEO, tmp_path, MediaType.VIDEO)
    s = score_map(f)
    assert s["reencode_indicator"] == 1.0  # written by libx264/Lavf
    assert s["ai_tool_tag"] == 0.0
    assert any(st["codec_type"] == "audio" for st in f.details["streams"])


def test_video_aigen_timeline_and_determinism(models_dir: Path, tmp_path: Path) -> None:
    a = run("video.aigen", VIDEO, tmp_path / "a", MediaType.VIDEO)
    b = run("video.aigen", VIDEO, tmp_path / "b", MediaType.VIDEO)
    sa, sb = score_map(a), score_map(b)
    assert sa["frames_analysed"] >= 4
    assert sa["univfd_max"] is None  # UnivFD weights not installed in this test: reported, not invented
    assert abs(sa["npr_max"] - sb["npr_max"]) <= 1e-6  # type: ignore[operator]
    names = {x.name for x in a.artefacts}
    assert {"frame_timeline.json", "top_frames.png"} <= names


def test_audio_spoof_on_audio_and_video(models_dir: Path, tmp_path: Path) -> None:
    fa = run("audio.spoof", AUDIO, tmp_path / "a", MediaType.AUDIO)
    fb = run("audio.spoof", AUDIO, tmp_path / "b", MediaType.AUDIO)
    assert score_map(fa)["segments_analysed"] >= 1
    assert abs(score_map(fa)["max_spoof_score"] - score_map(fb)["max_spoof_score"]) <= 1e-6  # type: ignore[operator]
    fv = run("audio.spoof", VIDEO, tmp_path / "v", MediaType.VIDEO)
    assert score_map(fv)["segments_analysed"] >= 1


def test_audio_spectrogram_golden(tmp_path: Path) -> None:
    f = run("audio.spectrogram", AUDIO, tmp_path, MediaType.AUDIO)
    check_golden("audio.spectrogram__tone", f)
    assert f.artefacts[0].path.stat().st_size > 1000


def test_face_modules_unavailable_without_weights() -> None:
    for mid in ("video.face_track", "video.face_frame_scores"):
        a = get_module(mid).availability()
        assert not a.available and "registry" in a.reason


def test_screening_rules_for_media_modules() -> None:
    assert get_module("video.aigen").screen({"npr_frames_above_threshold": 0.4}, {})
    assert get_module("video.aigen").screen({"npr_frames_above_threshold": 0.1}, {}) is None
    assert get_module("audio.spoof").screen({"segments_above_threshold": 0.5}, {})
    assert get_module("video.face_frame_scores").screen({"frames_above_threshold": 0.3}, {})
