"""Phase 4: benchmark run from the API, stored in the database, shown with the module."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from tests.conftest import FIXTURES, auth


@pytest.fixture
def datasets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "datasets"
    for sub in ("tiny/real", "tiny/fake", "tiny/masks"):
        (root / sub).mkdir(parents=True)
    shutil.copy(FIXTURES / "scene_original.jpg", root / "tiny/real/a.jpg")
    shutil.copy(FIXTURES / "scene_reference.jpg", root / "tiny/real/b.jpg")
    shutil.copy(FIXTURES / "scene_edited.jpg", root / "tiny/fake/c.jpg")
    shutil.copy(FIXTURES / "scene_edited_mask.png", root / "tiny/masks/c.png")
    monkeypatch.setattr(get_settings(), "datasets_dir", str(root))
    return root


def test_benchmark_run_and_results(client: TestClient, datasets: Path) -> None:
    listing = client.get("/api/v1/admin/datasets", headers=auth("adam")).json()
    assert listing["datasets"] == [{"name": "tiny", "items": 3, "fake": 1, "masks": True}]
    assert client.post("/api/v1/admin/benchmarks", headers=auth("esha"),
                       json={"module_id": "image.jpeg_ghost", "dataset": "tiny"}).status_code == 403
    assert client.post("/api/v1/admin/benchmarks", headers=auth("adam"),
                       json={"module_id": "image.jpeg_ghost", "dataset": "../etc"}).status_code == 422
    r = client.post("/api/v1/admin/benchmarks", headers=auth("adam"),
                    json={"module_id": "image.jpeg_ghost", "dataset": "tiny", "robustness": True})
    assert r.status_code == 202, r.text
    run = next(x for x in client.get("/api/v1/admin/benchmarks", headers=auth("adam")).json() if x["id"] == r.json()["id"])
    assert run["status"] == "succeeded", run
    clean = run["results"]["clean"]
    assert clean["n"] == 3 and clean["n_fake"] == 1 and 0.0 <= clean["auc"] <= 1.0
    assert "jpeg70" in run["results"] and "messaging" in run["results"]
    mod = next(m for m in client.get("/api/v1/modules", headers=auth("esha")).json() if m["id"] == "image.jpeg_ghost")
    assert any("Benchmark: tiny" in str(v.get("status")) for v in mod["validation"])
