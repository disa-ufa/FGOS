from __future__ import annotations

import time

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request
from starlette.responses import Response

from api.observability.logging import setup_logging
from api.observability.request_id import (
    generate_request_id,
    reset_request_id,
    sanitize_request_id,
    set_request_id,
)
from api.observability.sentry import init_sentry
from api.observability.metrics import observe_http_request

from api.routers.health import router as health_router
from api.routers.documents import router as documents_router
from api.routers.jobs import router as jobs_router
from api.routers.artifacts import router as artifacts_router
from api.routers.bot_delivery import router as bot_router
from api.routers.metrics import router as metrics_router


class UTF8JSONResponse(JSONResponse):
    """Force explicit UTF-8 charset for JSON responses.

    PowerShell (especially on Windows) may decode JSON as ANSI if charset is not
    present in the Content-Type header, producing mojibake for Cyrillic.
    """

    media_type = "application/json; charset=utf-8"


# Logging should be configured once at import time.
setup_logging()

app = FastAPI(
    title="FGOS Helper API",
    version="0.1.0",
    default_response_class=UTF8JSONResponse,
)

# Sentry (optional, enabled only if SENTRY_DSN is set)
init_sentry(app)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    # Prefer caller-provided request id (if safe), else generate.
    incoming = request.headers.get("X-Request-ID")
    rid = sanitize_request_id(incoming) or generate_request_id()
    token = set_request_id(rid)
    try:
        response: Response = await call_next(request)
    finally:
        reset_request_id(token)
    response.headers["X-Request-ID"] = rid
    return response


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    started = time.perf_counter()
    response: Response | None = None
    try:
        response = await call_next(request)
        return response
    finally:
        duration = time.perf_counter() - started
        try:
            observe_http_request(request=request, response=response, duration_seconds=duration)
        except Exception:
            # Never break request flow on metrics errors.
            pass


app.include_router(health_router)
app.include_router(documents_router)
app.include_router(jobs_router)
app.include_router(artifacts_router)
app.include_router(bot_router)

# Prometheus metrics endpoint (P0)
app.include_router(metrics_router)
