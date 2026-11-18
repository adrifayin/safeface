"""The runtime DB role cannot alter evidence hashes or the audit log (data-model requirement)."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from tests.conftest import new_case, owner_engine, upload


@pytest.fixture(scope="module")
def evidence_id(client: TestClient, jpeg_bytes_module: bytes) -> str:
    case = new_case(client)
    r = upload(client, case["id"], jpeg_bytes_module)
    assert r.status_code == 201, r.text
    return str(r.json()["evidence"]["id"])


@pytest.fixture(scope="module")
def jpeg_bytes_module() -> bytes:
    from tests.conftest import FIXTURES

    return (FIXTURES / "scene_original.jpg").read_bytes()


def app_engine():  # type: ignore[no-untyped-def]
    return create_engine(os.environ["SAFEFACE_DATABASE_URL"])


@pytest.mark.parametrize("sql", [
    "UPDATE audit_log SET actor = 'x' WHERE seq = 1",
    "DELETE FROM audit_log WHERE seq = 1",
    "TRUNCATE audit_log",
    "UPDATE evidence_items SET sha256 = repeat('0', 64) WHERE id = :e",
    "UPDATE evidence_items SET md5 = repeat('0', 32) WHERE id = :e",
    "DELETE FROM evidence_items WHERE id = :e",
    "UPDATE findings SET scores = '[]'::jsonb",
    "DELETE FROM hash_verifications",
])
def test_app_role_cannot_modify(evidence_id: str, sql: str) -> None:
    eng = app_engine()
    with pytest.raises(DBAPIError) as exc, eng.begin() as conn:
        conn.execute(text(sql), {"e": evidence_id})
    assert "permission denied" in str(exc.value).lower()
    eng.dispose()


@pytest.mark.parametrize("sql", [
    "UPDATE audit_log SET actor = 'x' WHERE seq = 1",
    "DELETE FROM audit_log WHERE seq = 1",
    "UPDATE evidence_items SET sha256 = repeat('0', 64) WHERE id = :e",
    "DELETE FROM evidence_items WHERE id = :e",
])
def test_trigger_blocks_even_the_owner(evidence_id: str, sql: str) -> None:
    eng = owner_engine()
    with pytest.raises(DBAPIError) as exc, eng.begin() as conn:
        conn.execute(text(sql), {"e": evidence_id})
    assert "append-only" in str(exc.value)
    eng.dispose()


def test_app_role_can_append_audit(client: TestClient) -> None:
    from app.core import audit
    from app.db.session import session_scope

    with session_scope() as s:
        row = audit.record(s, "test", "test.append", "test", "x", {"ok": True})
        assert row.seq > 0
