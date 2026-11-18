"""Audit-chain tamper detection (NFR-S5, SRS acceptance criterion)."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.audit import GENESIS_HASH, compute_entry_hash, entry_payload, verify_rows
from tests.conftest import auth, owner_engine


@dataclass
class Row:
    seq: int
    ts: datetime
    actor: str
    action: str
    target_type: str
    target_id: str
    details: dict[str, Any]
    prev_hash: str
    entry_hash: str


def build_chain(n: int) -> list[Row]:
    rows, prev = [], GENESIS_HASH
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(1, n + 1):
        ts = t0 + timedelta(seconds=i)
        details = {"i": i, "note": "ünïcode ok"}
        h = compute_entry_hash(prev, entry_payload(i, ts, "tester", "x.y", "case", "c1", details))
        rows.append(Row(i, ts, "tester", "x.y", "case", "c1", details, prev, h))
        prev = h
    return rows


def test_intact_chain_verifies() -> None:
    result = verify_rows(build_chain(10))
    assert result.ok and result.entries_checked == 10 and result.head_seq == 10


def test_modified_details_detected() -> None:
    rows = build_chain(10)
    rows[4].details = {"i": 5, "note": "changed"}
    result = verify_rows(rows)
    assert not result.ok and result.first_bad_seq == 5


def test_modified_actor_and_time_detected() -> None:
    rows = build_chain(5)
    rows[2].actor = "someone-else"
    assert verify_rows(rows).first_bad_seq == 3
    rows = build_chain(5)
    rows[3].ts = rows[3].ts + timedelta(microseconds=1)
    assert verify_rows(rows).first_bad_seq == 4


def test_deleted_entry_detected() -> None:
    rows = build_chain(10)
    del rows[6]
    result = verify_rows(rows)
    assert not result.ok and "gap" in (result.problem or "")


def test_deleted_tail_cannot_hide_if_head_known() -> None:
    rows = build_chain(10)
    head = verify_rows(rows).head_hash
    truncated = verify_rows(rows[:8])
    assert truncated.ok  # a truncated chain is self-consistent...
    assert truncated.head_hash != head  # ...but no longer matches the exported head.


def test_recomputed_entry_breaks_successor() -> None:
    rows = build_chain(6)
    forged = copy.copy(rows[2])
    forged.details = {"forged": True}
    forged.entry_hash = compute_entry_hash(forged.prev_hash, entry_payload(
        forged.seq, forged.ts, forged.actor, forged.action, forged.target_type,
        forged.target_id, forged.details))
    rows[2] = forged
    result = verify_rows(rows)
    assert not result.ok and result.first_bad_seq == 4


def test_database_tamper_detected_by_api(client: TestClient) -> None:
    """Simulate a DBA who disables the trigger and edits a row directly."""
    r = client.get("/api/v1/audit/verify", headers=auth("audrey"))
    assert r.status_code == 200 and r.json()["ok"], r.text

    eng = owner_engine()
    with eng.begin() as conn:
        seq, actor = conn.execute(text("SELECT seq, actor FROM audit_log ORDER BY seq LIMIT 1")).one()
        conn.execute(text("ALTER TABLE audit_log DISABLE TRIGGER audit_log_append_only"))
        conn.execute(text("UPDATE audit_log SET actor = 'mallory' WHERE seq = :s"), {"s": seq})
        conn.execute(text("ALTER TABLE audit_log ENABLE TRIGGER audit_log_append_only"))
    try:
        r = client.get("/api/v1/audit/verify", headers=auth("audrey"))
        body = r.json()
        assert r.status_code == 200
        assert body["ok"] is False and body["first_bad_seq"] == seq
    finally:
        # Restore the original value so later tests see an intact chain.
        with eng.begin() as conn:
            conn.execute(text("ALTER TABLE audit_log DISABLE TRIGGER audit_log_append_only"))
            conn.execute(text("UPDATE audit_log SET actor = :a WHERE seq = :s"), {"a": actor, "s": seq})
            conn.execute(text("ALTER TABLE audit_log ENABLE TRIGGER audit_log_append_only"))
        eng.dispose()
    assert client.get("/api/v1/audit/verify", headers=auth("audrey")).json()["ok"]
