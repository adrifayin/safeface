"""Preliminary screening: raises doubts with reasons, never a verdict."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from app.modules.registry import all_modules, get_module
from app.services import screening
from tests.conftest import auth, new_case, upload

VERDICT_WORDS = re.compile(r"\b(fake|real|authentic|genuine|deepfake detected)\b", re.IGNORECASE)


def test_fixed_texts_contain_no_verdict_words() -> None:
    for text in [*screening.HEADLINES.values()]:
        assert not VERDICT_WORDS.search(text), text
    assert "NOT A FINDING" in screening.CAVEAT and "accuracy" in screening.CAVEAT


def test_rules_name_check_and_threshold() -> None:
    npr = get_module("image.aigen.npr")
    reason = npr.screen({"probability_generated": 0.91}, {})
    assert reason and "0.50" in reason and npr.name in reason and not VERDICT_WORDS.search(reason)
    assert npr.screen({"probability_generated": 0.2}, {}) is None
    assert get_module("image.ela").screen({"mean_error": 99.0}, {}) is None  # ELA never flags alone
    for m in all_modules().values():
        assert m.screen({}, {}) is None  # no scores -> no flag


def test_screening_endpoint(client: TestClient, edited_bytes: bytes) -> None:
    case = new_case(client)
    ev = upload(client, case["id"], edited_bytes).json()["evidence"]
    r = client.get(f"/api/v1/evidence/{ev['id']}/screening", headers=auth("esha"))
    assert r.status_code == 200, r.text
    body = r.json()
    # The fixture was written by "GIMP": metadata raises a doubt; detectors have no weights in tests.
    assert body["status"] == "doubt_raised"
    assert any("image-editing software" in f["reason"] for f in body["flags"])
    assert "UnivFD AI-generation indicator" in body["detectors_without_result"]
    assert body["caveat"] == screening.CAVEAT
    whole = client.get(f"/api/v1/cases/{case['id']}/screening", headers=auth("ivan")).json()
    assert whole["items"][ev["id"]]["status"] == "doubt_raised"
    assert client.get(f"/api/v1/evidence/{ev['id']}/screening", headers=auth("adam")).status_code == 404


def test_plain_questions(client: TestClient, edited_bytes: bytes) -> None:
    case = new_case(client)
    ev = upload(client, case["id"], edited_bytes).json()["evidence"]
    body = client.get(f"/api/v1/evidence/{ev['id']}/screening", headers=auth("esha")).json()
    qs = {q["key"]: q for q in body["questions"]}
    assert set(qs) == {"ai_generated", "edited", "face_swap"}  # no voice question for a photo
    # "GIMP" software tag -> signs of editing; detectors not installed in tests -> not fully checked
    assert qs["edited"]["answer"] == "signs_found" and qs["edited"]["reasons"]
    assert qs["ai_generated"]["answer"] in ("not_checked", "partly_checked")
    assert body["answer_line"].startswith("Signs found: edited")
    for q in body["questions"]:
        assert not VERDICT_WORDS.search(q["question"] + q["short"])


def test_likelihood_and_missing_checks(client: TestClient, edited_bytes: bytes) -> None:
    case = new_case(client)
    ev = upload(client, case["id"], edited_bytes).json()["evidence"]
    body = client.get(f"/api/v1/evidence/{ev['id']}/screening", headers=auth("esha")).json()
    for q in body["questions"]:
        assert "likelihood" in q and "detector_scores" in q
        if q["likelihood"] is not None:
            assert 0.0 <= q["likelihood"] <= 1.0 and q["likelihood_band"] in ("low", "medium", "high")
    assert "overall_likelihood" in body
    # everything that could run on ingest already ran: nothing missing, the endpoint queues nothing
    assert body["missing_checks"] == []
    r = client.post(f"/api/v1/evidence/{ev['id']}/analyses/missing", headers=auth("esha"))
    assert r.status_code == 202 and r.json() == []
