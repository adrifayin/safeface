"""Model-weights verification (NFR-S6) and ML module plumbing/determinism.

No real research checkpoints are committed (licences). The ML modules are
exercised with small randomly initialised weights written to a temporary
models directory: this tests loading, checksum enforcement, preprocessing and
determinism — NOT detection accuracy, which is a Phase 4 validation task.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.core.hashing import sha256_file
from app.modules import weights
from app.modules.registry import get_module
from tests.conftest import FIXTURES
from tests.module_harness import run, score_map

torch = pytest.importorskip("torch")


@pytest.fixture
def models_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setattr(get_settings(), "models_dir", str(tmp_path))
    weights.load_registry.cache_clear()
    yield tmp_path
    weights.load_registry.cache_clear()
    weights.set_disabled(set())


def write_registry(root: Path, entries: list[dict[str, object]]) -> None:
    import yaml

    (root / "registry.yaml").write_text(yaml.safe_dump({"weights": entries}), encoding="utf-8")
    weights.load_registry.cache_clear()


def entry(name: str, module_id: str, path: str, sha: str | None) -> dict[str, object]:
    return {"name": name, "module_id": module_id, "version": "test", "path": path, "sha256": sha,
            "licence": "test-only"}


def tiny_npr(root: Path) -> str:
    from app.modules._vendor.npr_resnet import NPRNet

    torch.manual_seed(0)
    (root / "npr").mkdir()
    torch.save(NPRNet().state_dict(), root / "npr" / "NPR.pth")
    return sha256_file(root / "npr" / "NPR.pth")


def test_missing_weights_make_module_unavailable(models_dir: Path) -> None:
    write_registry(models_dir, [])
    a = get_module("image.aigen.npr").availability()
    assert not a.available and "fetch_models.md" in a.reason


def test_unverified_weights_refused(models_dir: Path) -> None:
    tiny_npr(models_dir)
    write_registry(models_dir, [entry("npr", "image.aigen.npr", "npr/NPR.pth", None)])
    a = get_module("image.aigen.npr").availability()
    assert not a.available and "refusing unverified" in a.reason


def test_modified_weights_refused(models_dir: Path) -> None:
    tiny_npr(models_dir)
    write_registry(models_dir, [entry("npr", "image.aigen.npr", "npr/NPR.pth", "0" * 64)])
    with pytest.raises(weights.WeightsError, match="REFUSED"):
        weights.resolve("npr")


def test_path_traversal_refused(models_dir: Path) -> None:
    write_registry(models_dir, [entry("x", "image.aigen.npr", "../../etc/passwd", "0" * 64)])
    with pytest.raises(weights.WeightsError, match="escapes"):
        weights.resolve("x")


def test_disabled_weights_unavailable(models_dir: Path) -> None:
    sha = tiny_npr(models_dir)
    write_registry(models_dir, [entry("npr", "image.aigen.npr", "npr/NPR.pth", sha)])
    assert get_module("image.aigen.npr").availability().available
    weights.set_disabled({"npr"})
    assert not get_module("image.aigen.npr").availability().available


def test_npr_runs_deterministically(models_dir: Path, tmp_path: Path) -> None:
    sha = tiny_npr(models_dir)
    write_registry(models_dir, [entry("npr", "image.aigen.npr", "npr/NPR.pth", sha)])
    f1 = run(get_module("image.aigen.npr"), FIXTURES / "scene_edited.jpg", tmp_path / "a")
    f2 = run(get_module("image.aigen.npr"), FIXTURES / "scene_edited.jpg", tmp_path / "b")
    s1, s2 = score_map(f1), score_map(f2)
    assert 0.0 <= s1["probability_generated"] <= 1.0  # type: ignore[operator]
    assert abs(s1["logit"] - s2["logit"]) <= 1e-6  # type: ignore[operator]
    assert f1.provenance["weights"] == {"npr": sha}


def test_modified_weights_after_load_are_refused(models_dir: Path, tmp_path: Path) -> None:
    sha = tiny_npr(models_dir)
    write_registry(models_dir, [entry("npr", "image.aigen.npr", "npr/NPR.pth", sha)])
    run(get_module("image.aigen.npr"), FIXTURES / "scene_original.jpg", tmp_path / "a")
    with (models_dir / "npr" / "NPR.pth").open("ab") as fh:
        fh.write(b"tamper")
    os.utime(models_dir / "npr" / "NPR.pth", None)
    with pytest.raises(weights.WeightsError, match="REFUSED"):
        run(get_module("image.aigen.npr"), FIXTURES / "scene_original.jpg", tmp_path / "b")


def test_univfd_runs_deterministically(models_dir: Path, tmp_path: Path) -> None:
    from app.modules._vendor.clip_visual import VisionTransformer

    torch.manual_seed(0)
    vit = VisionTransformer(224, 14, 64, 2, 1, 32)
    (models_dir / "clip").mkdir()
    torch.save({f"visual.{k}": v for k, v in vit.state_dict().items()}, models_dir / "clip" / "tiny.pth")
    torch.save(torch.nn.Linear(32, 1).state_dict(), models_dir / "clip" / "fc.pth")
    write_registry(models_dir, [
        entry("clip-vit-l14", "image.aigen.univfd", "clip/tiny.pth", sha256_file(models_dir / "clip" / "tiny.pth")),
        entry("univfd-fc", "image.aigen.univfd", "clip/fc.pth", sha256_file(models_dir / "clip" / "fc.pth")),
    ])
    s1 = score_map(run(get_module("image.aigen.univfd"), FIXTURES / "scene_edited.jpg", tmp_path / "a"))
    s2 = score_map(run(get_module("image.aigen.univfd"), FIXTURES / "scene_edited.jpg", tmp_path / "b"))
    assert abs(s1["logit"] - s2["logit"]) <= 1e-6  # type: ignore[operator]


def test_pickle_checkpoint_refused_by_default(models_dir: Path) -> None:
    import pickle

    from app.modules._common.torchutil import load_checkpoint

    class Evil:
        def __reduce__(self):  # type: ignore[no-untyped-def]
            return (print, ("this must never execute",))

    (models_dir / "evil.pth").write_bytes(pickle.dumps(Evil()))
    write_registry(models_dir, [entry("evil", "image.aigen.npr", "evil.pth",
                                      sha256_file(models_dir / "evil.pth"))])
    with pytest.raises(RuntimeError, match="Refusing to unpickle"):
        load_checkpoint("evil")


def test_cfgnode_shim_matches_yacs_semantics(tmp_path: Path) -> None:
    from app.modules._vendor.shims import CfgNode

    c = CfgNode()
    c.MODEL = CfgNode()
    c.MODEL.NAME = "x"
    c.MODEL.EXTRA = CfgNode(new_allowed=True)
    (tmp_path / "c.yaml").write_text("MODEL:\n  MODS: ('RGB','NP++')\n  EXTRA:\n    BN_EPS: 0.001\n")
    c.MODEL.MODS = None
    c.merge_from_file(tmp_path / "c.yaml")
    assert c.MODEL.MODS == ("RGB", "NP++") and c.MODEL.EXTRA.BN_EPS == 0.001
    assert "BN_EPS" in c.MODEL.EXTRA
    c.freeze()
    with pytest.raises(AttributeError):
        c.MODEL.NAME = "y"
    with pytest.raises(KeyError):
        CfgNode({"A": 1}).merge_from_file(tmp_path / "c.yaml")


@pytest.mark.skipif(not os.environ.get("SAFEFACE_REAL_NPR"), reason="set SAFEFACE_REAL_NPR=/path/NPR.pth")
def test_real_npr_checkpoint_loads_strictly() -> None:
    from app.modules._vendor.npr_resnet import NPRNet
    from app.modules.image_aigen_npr import unwrap_state

    state = torch.load(os.environ["SAFEFACE_REAL_NPR"], map_location="cpu", weights_only=True)
    NPRNet().load_state_dict(unwrap_state(state), strict=True)
