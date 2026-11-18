"""Module availability comes from what the workers report, not the API image."""

from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.modules import status
from app.modules.registry import get_module


@pytest.fixture
def live_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "celery_eager", False)


def test_worker_report_decides_tool_availability(live_mode: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(status, "_reports", lambda: {
        "image.metadata": {"available": True, "reason": ""},
        "image.c2pa": {"available": False, "reason": "c2patool missing"},
    })
    mods = [get_module("image.metadata"), get_module("image.c2pa"), get_module("image.ela")]
    eff = status.effective(mods)
    assert eff["image.metadata"].availability.available
    assert not eff["image.c2pa"].availability.available and eff["image.c2pa"].known
    assert not eff["image.ela"].availability.available and not eff["image.ela"].known


def test_missing_weights_override_worker_report(live_mode: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(status, "_reports", lambda: {"image.aigen.npr": {"available": True, "reason": ""}})
    eff = status.effective([get_module("image.aigen.npr")])["image.aigen.npr"]
    assert not eff.availability.available and "registry" in eff.availability.reason


def test_triage_queues_unknown_but_skips_reported_unavailable(live_mode: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.db.models import EvidenceItem
    from app.services.analysis import triage_module_ids

    monkeypatch.setattr(status, "_reports", lambda: {"image.c2pa": {"available": False, "reason": "x"}})
    item = EvidenceItem(kind="questioned", media_type="image")
    run, skipped = triage_module_ids(item)
    assert "image.c2pa" in skipped and "image.metadata" in run and "image.ela" in run
