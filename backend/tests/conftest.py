"""Test configuration.

Tests run against a real PostgreSQL 16 (infra/docker-compose.test.yml) so the
grants and immutability triggers are exercised for real. Object storage uses
the in-memory store (which, unlike MinIO with object lock, can be tampered
with — that is what the tamper tests need). Celery runs eagerly. Keycloak is
replaced by a locally generated RSA key whose JWKS the API is pointed at.
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

TEST_ROOT = Path(__file__).parent
FIXTURES = TEST_ROOT / "fixtures"
_tmp = Path(tempfile.mkdtemp(prefix="safeface-test-"))

ISSUER = "https://safeface.test/auth/realms/safeface"
os.environ.update({
    "SAFEFACE_ENV": "test",
    "SAFEFACE_STORAGE_BACKEND": "memory",
    "SAFEFACE_CELERY_EAGER": "true",
    "SAFEFACE_OIDC_ISSUER": ISSUER,
    "SAFEFACE_OIDC_JWKS_FILE": str(_tmp / "jwks.json"),
    "SAFEFACE_MODELS_DIR": os.environ.get("SAFEFACE_TEST_MODELS_DIR", str(FIXTURES / "models")),
    "SAFEFACE_WORK_DIR": str(_tmp / "work"),
    "SAFEFACE_IMAGE_DIGEST": "sha256:test",
})
os.environ.setdefault(
    "SAFEFACE_DATABASE_URL", "postgresql+psycopg://safeface_app:test@localhost:5432/safeface"
)
os.environ.setdefault(
    "SAFEFACE_DATABASE_OWNER_URL",
    "postgresql+psycopg://safeface_owner:test@localhost:5432/safeface",
)

import jwt  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from jwt.algorithms import RSAAlgorithm  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_jwk = json.loads(RSAAlgorithm.to_jwk(_KEY.public_key()))
_jwk.update({"kid": "test-key", "alg": "RS256", "use": "sig"})
(_tmp / "jwks.json").write_text(json.dumps({"keys": [_jwk]}), encoding="utf-8")


USERS: dict[str, list[str]] = {
    "ivan": ["investigator"],
    "esha": ["examiner"],
    "emil": ["examiner"],
    "suku": ["supervisor"],
    "sara": ["supervisor"],
    "adam": ["admin"],
    "audrey": ["auditor"],
}


def make_token(username: str, roles: list[str] | None = None, **overrides: Any) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": ISSUER, "aud": ["safeface-api", "account"], "sub": f"sub-{username}",
        "preferred_username": username, "name": username.title(), "iat": now, "exp": now + 600,
        "realm_access": {"roles": roles if roles is not None else USERS[username]},
        "sid": f"session-{username}",
    }
    claims.update(overrides)
    return jwt.encode(claims, _KEY, algorithm="RS256", headers={"kid": "test-key"})


def auth(username: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(username)}"}


def owner_engine():  # type: ignore[no-untyped-def]
    return create_engine(os.environ["SAFEFACE_DATABASE_OWNER_URL"])


@pytest.fixture(scope="session", autouse=True)
def database() -> Iterator[None]:
    """Fresh schema for the test session, migrated as the owner role."""
    eng = owner_engine()
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("REVOKE CREATE ON SCHEMA public FROM PUBLIC"))
        conn.execute(text("GRANT USAGE ON SCHEMA public TO safeface_app"))
    eng.dispose()
    from app.bootstrap import migrate

    migrate()
    yield


@pytest.fixture(scope="session")
def client(database: None) -> Iterator[TestClient]:
    from app.main import app

    with TestClient(app) as c:
        for user in USERS:  # make every test user known to the API
            assert c.get("/api/v1/me", headers=auth(user)).status_code == 200
        yield c


def user_id(client: TestClient, username: str) -> str:
    return str(client.get("/api/v1/me", headers=auth(username)).json()["user"]["id"])


def meta_header(**meta: Any) -> str:
    return base64.urlsafe_b64encode(json.dumps(meta).encode()).decode().rstrip("=")


def upload(client: TestClient, case_id: str, data: bytes, username: str = "ivan",
           **meta: Any) -> Any:
    meta.setdefault("filename", "questioned.jpg")
    return client.post(
        f"/api/v1/cases/{case_id}/evidence", content=data,
        headers={**auth(username), "X-SafeFace-Metadata": meta_header(**meta),
                 "Content-Type": "application/octet-stream"},
    )


def new_case(client: TestClient, username: str = "ivan", examiner: str | None = "esha",
             supervisor: str | None = "suku") -> dict[str, Any]:
    body: dict[str, Any] = {
        "case_no": f"TEST/{uuid.uuid4().hex[:10]}", "crime_head": "IT Act s.66E",
        "investigating_officer": "SI Test", "fir_no": "FIR-1/2026",
    }
    if examiner:
        body["assigned_examiner_id"] = user_id(client, examiner)
    r = client.post("/api/v1/cases", json=body, headers=auth(username))
    assert r.status_code == 201, r.text
    case = r.json()
    if supervisor:
        r = client.post(f"/api/v1/cases/{case['id']}/members", headers=auth(supervisor),
                        json={"user_id": user_id(client, supervisor), "permission": "approve"})
        assert r.status_code == 201, r.text
    return dict(case)


@pytest.fixture
def jpeg_bytes() -> bytes:
    return (FIXTURES / "scene_original.jpg").read_bytes()


@pytest.fixture
def edited_bytes() -> bytes:
    return (FIXTURES / "scene_edited.jpg").read_bytes()
