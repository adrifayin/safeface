"""Module discovery.

Every sub-package of ``app.modules`` that defines ``MODULE`` is registered.
Packages starting with ``_`` are ignored (shared helpers live there).
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from functools import lru_cache

import app.modules as modules_pkg
from app.modules.base import AnalysisModule

log = logging.getLogger(__name__)


@lru_cache
def all_modules() -> dict[str, AnalysisModule]:
    found: dict[str, AnalysisModule] = {}
    for info in sorted(pkgutil.iter_modules(modules_pkg.__path__), key=lambda i: i.name):
        if not info.ispkg or info.name.startswith("_"):
            continue
        package = importlib.import_module(f"{modules_pkg.__name__}.{info.name}")
        module = getattr(package, "MODULE", None)
        if module is None:
            continue
        if not isinstance(module, AnalysisModule):
            raise TypeError(f"{info.name}.MODULE does not satisfy the AnalysisModule contract")
        if module.id in found:
            raise ValueError(f"duplicate module id {module.id}")
        found[module.id] = module
    log.info("registered analysis modules: %s", ", ".join(found))
    return found


def get_module(module_id: str) -> AnalysisModule:
    try:
        return all_modules()[module_id]
    except KeyError as exc:
        raise KeyError(f"unknown module {module_id}") from exc
