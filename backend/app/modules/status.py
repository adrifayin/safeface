"""Which modules can actually run, as reported by the analysis workers.

Availability depends on the *worker* image (ExifTool, c2patool, PyTorch live
there, not in the API image), so each worker reports, when it starts, the
availability of the modules on its queue to a Redis hash. The API combines
that report with its own weights checks (which also reflect registry
enable/disable decisions). In eager/test mode the check runs locally.
"""

from __future__ import annotations

import json
import logging
import socket
from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings
from app.core.timeutil import iso, utcnow
from app.modules.base import AnalysisModule, Availability
from app.modules.registry import all_modules
from app.modules.weights import weights_availability

log = logging.getLogger(__name__)
KEY = "safeface:module_status"


def module_queue(module: AnalysisModule) -> str:
    return "gpu" if module.requires_gpu else "cpu"


def _redis() -> Any:
    import redis

    return redis.Redis.from_url(get_settings().redis_url, socket_timeout=2, socket_connect_timeout=2)


def report_worker_status(queue: str) -> None:
    """Called by a worker at start-up for the modules it serves."""
    host = socket.gethostname()
    values = {}
    for module in all_modules().values():
        if module_queue(module) != queue:
            continue
        avail = module.availability()
        values[module.id] = json.dumps({"available": avail.available, "reason": avail.reason,
                                        "worker": f"{queue}@{host}", "reported_at": iso(utcnow())})
    if values:
        _redis().hset(KEY, mapping=values)
        log.info("reported availability of %d modules for queue %s", len(values), queue)


def _reports() -> dict[str, dict[str, Any]]:
    try:
        raw = _redis().hgetall(KEY)
    except Exception:  # noqa: BLE001 - status display must not break the API
        log.warning("could not read module status from Redis", exc_info=True)
        return {}
    return {k.decode(): json.loads(v) for k, v in raw.items()}


@dataclass(frozen=True)
class EffectiveAvailability:
    availability: Availability
    known: bool  # False = no worker has reported yet


def effective(modules: list[AnalysisModule]) -> dict[str, EffectiveAvailability]:
    if get_settings().celery_eager:
        return {m.id: EffectiveAvailability(m.availability(), True) for m in modules}
    reports = _reports()
    out: dict[str, EffectiveAvailability] = {}
    for m in modules:
        weights = weights_availability(m.required_weights)
        if not weights.available:
            out[m.id] = EffectiveAvailability(weights, True)
            continue
        rep = reports.get(m.id)
        if rep is None:
            out[m.id] = EffectiveAvailability(Availability(
                False, f"no {module_queue(m)} worker has reported yet (is it running?)"), False)
        else:
            out[m.id] = EffectiveAvailability(Availability(bool(rep["available"]), str(rep["reason"])), True)
    return out
