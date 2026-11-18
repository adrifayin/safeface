"""OIDC bearer-token validation against Keycloak.

Tokens are RS256-signed by the Keycloak realm. We verify signature, issuer,
audience and expiry locally using the realm's JWKS, fetched from Keycloak over
the internal Docker network (never the internet) and cached in memory.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jwt
from jwt import PyJWK, PyJWKSet

from app.core.config import Settings
from app.core.policy import Role

ALLOWED_ALGORITHMS = ["RS256"]
_MIN_REFRESH_INTERVAL_S = 30.0


class AuthError(Exception):
    """Token missing, malformed, expired or not issued for this API."""


@dataclass(frozen=True)
class Principal:
    sub: str
    username: str
    display_name: str
    roles: frozenset[Role]
    session_id: str | None

    @property
    def actor(self) -> str:
        """How this user appears in the audit log."""
        return f"{self.username} ({self.sub})"


class JWKSCache:
    """Caches the realm signing keys; refreshes when an unknown ``kid`` appears."""

    def __init__(self, url: str, file: str = "") -> None:
        self._url = url
        self._file = file
        self._keys: dict[str, PyJWK] = {}
        self._fetched_at = 0.0
        self._lock = threading.Lock()

    def _load(self) -> dict[str, Any]:
        if self._file:
            data: dict[str, Any] = json.loads(Path(self._file).read_text(encoding="utf-8"))
            return data
        # Internal service URL only (http://keycloak:8080/...). nosec: not user-controlled.
        with urllib.request.urlopen(self._url, timeout=5) as resp:  # noqa: S310
            loaded: dict[str, Any] = json.loads(resp.read())
            return loaded

    def _refresh(self) -> None:
        jwks = PyJWKSet.from_dict(self._load())
        self._keys = {k.key_id: k for k in jwks.keys if k.key_id}
        self._fetched_at = time.monotonic()

    def get(self, kid: str) -> PyJWK:
        with self._lock:
            if kid not in self._keys and (
                time.monotonic() - self._fetched_at > _MIN_REFRESH_INTERVAL_S or not self._keys
            ):
                self._refresh()
            if kid not in self._keys:
                raise AuthError("unknown signing key")
            return self._keys[kid]


def decode_token(token: str, settings: Settings, jwks: JWKSCache) -> Principal:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise AuthError("malformed token") from exc
    if header.get("alg") not in ALLOWED_ALGORITHMS:
        raise AuthError("unsupported token algorithm")
    key = jwks.get(str(header.get("kid", "")))
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            key=key.key,
            algorithms=ALLOWED_ALGORITHMS,
            audience=settings.oidc_audience,
            issuer=settings.oidc_issuer,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
            leeway=10,
        )
    except jwt.PyJWTError as exc:
        raise AuthError(f"invalid token: {exc.__class__.__name__}") from exc

    if settings.require_amr_otp and "otp" not in (claims.get("amr") or []):
        raise AuthError("second factor (OTP) not present in token")

    raw_roles = (claims.get("realm_access") or {}).get("roles") or []
    roles = frozenset(Role(r) for r in raw_roles if r in Role._value2member_map_)
    if not roles:
        raise AuthError("user has no SafeFace role")
    username = str(claims.get("preferred_username") or claims["sub"])
    return Principal(
        sub=str(claims["sub"]),
        username=username,
        display_name=str(claims.get("name") or username),
        roles=roles,
        session_id=claims.get("sid"),
    )
