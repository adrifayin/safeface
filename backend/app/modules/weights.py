"""Local model weights: lookup in ``models/registry.yaml`` and SHA-256 check.

Weights are NEVER downloaded at runtime. A weights file is usable only if:
- it is listed in the registry with a SHA-256;
- the file exists under ``SAFEFACE_MODELS_DIR``; and
- its SHA-256 matches the registry (checked every time it is loaded).

A missing ``sha256`` in the registry means "not yet verified by an admin"
and the file is refused, never trusted on first use.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.core.config import get_settings
from app.core.hashing import sha256_file
from app.modules.base import Availability

FETCH_HELP = "see scripts/fetch_models.md for offline installation"


class WeightsError(Exception):
    """Weights missing, unverified or modified. The module must not run."""


@dataclass(frozen=True)
class WeightsEntry:
    name: str
    module_id: str
    version: str
    path: str
    sha256: str | None
    licence: str
    source: str | None
    validation: dict[str, Any]

    def file(self) -> Path:
        root = Path(get_settings().models_dir).resolve()
        resolved = (root / self.path).resolve()
        if root not in resolved.parents and resolved != root:
            raise WeightsError(f"{self.name}: path escapes the models directory")
        return resolved


def registry_path() -> Path:
    return Path(get_settings().models_dir) / "registry.yaml"


@lru_cache
def load_registry() -> dict[str, WeightsEntry]:
    path = registry_path()
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries: dict[str, WeightsEntry] = {}
    for item in raw.get("weights", []):
        entry = WeightsEntry(
            name=str(item["name"]),
            module_id=str(item["module_id"]),
            version=str(item["version"]),
            path=str(item["path"]),
            sha256=(str(item["sha256"]).lower() if item.get("sha256") else None),
            licence=str(item.get("licence", "unknown")),
            source=item.get("source"),
            validation=dict(item.get("validation") or {}),
        )
        entries[entry.name] = entry
    return entries


# Disabled names are pushed in from the database (model_registry.enabled) by
# the API/worker at startup and after an approved change.
_disabled: set[str] = set()
_verified: dict[tuple[str, int, int], str] = {}
_lock = threading.Lock()


def set_disabled(names: set[str]) -> None:
    global _disabled
    _disabled = set(names)


def _check(name: str, verify_hash: bool) -> WeightsEntry:
    entry = load_registry().get(name)
    if entry is None:
        raise WeightsError(f"weights '{name}' are not listed in models/registry.yaml; {FETCH_HELP}")
    if name in _disabled:
        raise WeightsError(f"weights '{name}' are disabled in the model registry")
    if not entry.sha256:
        raise WeightsError(
            f"weights '{name}' have no SHA-256 in the registry; refusing unverified weights"
        )
    path = entry.file()
    if not path.is_file():
        raise WeightsError(f"weights '{name}' not installed at models/{entry.path}; {FETCH_HELP}")
    if verify_hash:
        stat = path.stat()
        cache_key = (str(path), stat.st_size, stat.st_mtime_ns)
        with _lock:
            actual = _verified.get(cache_key) or sha256_file(path)
            if actual != entry.sha256:
                raise WeightsError(
                    f"REFUSED: weights '{name}' SHA-256 {actual} does not match registry "
                    f"{entry.sha256} (modified or wrong file)"
                )
            _verified[cache_key] = actual
    return entry


def weights_availability(names: list[str]) -> Availability:
    """Cheap check (no hashing) used to list modules as available/unavailable."""
    for name in names:
        try:
            _check(name, verify_hash=False)
        except WeightsError as exc:
            return Availability(False, str(exc))
    return Availability(True)


def resolve(name: str) -> tuple[Path, str]:
    """Return (path, sha256) after a full checksum verification."""
    entry = _check(name, verify_hash=True)
    assert entry.sha256 is not None
    return entry.file(), entry.sha256
