"""Benchmark metrics (scripts/benchmark.py) against hand-computed values."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "benchmark.py"
if not SCRIPT.exists():
    pytest.skip("scripts not mounted", allow_module_level=True)
spec = importlib.util.spec_from_file_location("benchmark", SCRIPT)
bench = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
spec.loader.exec_module(bench)  # type: ignore[union-attr]


def test_auc_extremes_and_known_value() -> None:
    y = np.array([0, 0, 1, 1])
    assert bench.auc(np.array([0.1, 0.2, 0.8, 0.9]), y) == pytest.approx(1.0)
    assert bench.auc(np.array([0.9, 0.8, 0.2, 0.1]), y) == pytest.approx(0.0)
    # one of four positive/negative pairs mis-ordered -> 0.75
    assert bench.auc(np.array([0.1, 0.6, 0.5, 0.9]), y) == pytest.approx(0.75)


def test_tpr_at_fpr() -> None:
    s = np.array([0.95, 0.9, 0.85, 0.3, 0.2, 0.1, 0.05, 0.04, 0.03, 0.02])
    y = np.array([1, 1, 0, 1, 0, 0, 0, 0, 0, 0])
    assert bench.tpr_at(s, y, 0.0) == pytest.approx(2 / 3)
    assert bench.tpr_at(s, y, 1 / 7) == pytest.approx(1.0)


def test_f1_iou_and_ece() -> None:
    pred = np.zeros((4, 4), bool)
    pred[:2] = True
    mask = np.zeros((4, 4), bool)
    mask[1:3] = True
    f1, iou = bench.f1_iou(pred, mask)
    assert f1 == pytest.approx(0.5) and iou == pytest.approx(1 / 3)
    assert bench.ece(np.array([0.0, 1.0]), np.array([0, 1])) == pytest.approx(0.0)
