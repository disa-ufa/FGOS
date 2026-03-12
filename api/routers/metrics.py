"""Prometheus metrics endpoint.

The service should be able to start even if optional observability
dependencies are not installed. If `prometheus_client` is missing,
`/metrics` will return 503 instead of crashing the API.
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from fastapi.responses import PlainTextResponse

try:
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    _PROM_AVAILABLE = True
except Exception:
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"
    generate_latest = None
    _PROM_AVAILABLE = False


router = APIRouter(tags=["metrics"])


@router.get("/metrics")
def metrics():
    if not _PROM_AVAILABLE or generate_latest is None:
        return PlainTextResponse(
            "prometheus_client is not installed; /metrics is disabled",
            status_code=503,
        )
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
