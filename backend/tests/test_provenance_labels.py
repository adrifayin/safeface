"""AI labels written by generators: AIGC implicit label (MiniMax/Hailuo, Kling) and C2PA declarations."""

from __future__ import annotations

import json

from app.modules.video_container import aigc_label


def test_aigc_label_minimax() -> None:
    tag = json.dumps({"Label": "1", "ContentProducer": "MiniMax", "ProduceID": "07364ce2", "ReservedCode1": "{}"})
    assert aigc_label({"AIGC": tag}) == {"producer": "MiniMax", "produce_id": "07364ce2"}
    assert aigc_label({"aigc": tag})  # tag names are case-insensitive


def test_aigc_label_absent_or_not_ai() -> None:
    assert aigc_label({}) is None
    assert aigc_label({"AIGC": json.dumps({"Label": "0", "ContentProducer": "X"})}) is None
    assert aigc_label({"AIGC": "not json"}) == {"producer": "unknown (unparsable AIGC tag)", "produce_id": ""}
