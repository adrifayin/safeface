"""FastAPI application.

Swagger UI and ReDoc are disabled: they load JavaScript from a public CDN,
which would break the air-gap. The OpenAPI JSON is still served (internally)
for tooling.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from app import __version__
from app.api import (
    admin,
    analyses,
    disposals,
    audit_routes,
    cases,
    evidence,
    examiner,
    modules_routes,
    reports,
    session_routes,
)
from app.core.audit import SYSTEM_ACTOR
from app.db.session import session_scope

log = logging.getLogger("safeface")
API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    try:
        with session_scope() as db:
            admin.sync_registry(db, SYSTEM_ACTOR)
    except Exception:
        log.exception("model registry sync failed at startup")
    yield


app = FastAPI(
    title="SafeFace Forensic Workbench API",
    version=__version__,
    docs_url=None,
    redoc_url=None,
    openapi_url=f"{API_PREFIX}/openapi.json",
    lifespan=lifespan,
)


@app.middleware("http")
async def security_headers(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Cache-Control", "no-store")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


@app.get(f"{API_PREFIX}/health", include_in_schema=False)
def health() -> dict[str, str]:
    return {"status": "ok"}


for router in (
    session_routes.router, cases.router, evidence.router, analyses.router, examiner.router,
    reports.router, audit_routes.router, modules_routes.router, admin.router, disposals.router,
):
    app.include_router(router, prefix=API_PREFIX)
