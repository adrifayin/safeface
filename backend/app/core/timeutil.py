"""Time helpers. All stored times are UTC with microsecond precision."""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(ts: datetime) -> str:
    """Fixed ISO-8601 rendering used inside hashes: ``YYYY-MM-DDTHH:MM:SS.ffffffZ``."""
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
