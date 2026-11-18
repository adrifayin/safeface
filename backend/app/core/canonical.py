"""Canonical JSON encoding used for hashing (audit chain, provenance).

Rules: UTF-8, keys sorted, no insignificant whitespace, NaN/Infinity refused.
Two equal Python values always encode to identical bytes.
"""

from __future__ import annotations

import json
from typing import Any


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def normalise(value: Any) -> Any:
    """Round-trip through canonical JSON so stored values equal hashed values."""
    return json.loads(canonical_json(value))
