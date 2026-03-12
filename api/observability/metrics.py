"""HTTP request metrics.

Metrics are optional for this project. If `prometheus_client` is not
installed, this module should not prevent the API from starting.
"""

from __future__ import annotations

from typing import Any

try:
    from prometheus_client import Counter, Histogram

    _PROM_AVAILABLE = True
except Exception:
    Counter = Histogram = None  # type: ignore
    _PROM_AVAILABLE = False


if _PROM_AVAILABLE:
    fgos_http_requests_total = Counter(
        "fgos_http_requests_total",
        "Total number of HTTP requests",
        ["method", "path", "status"],
    )
    fgos_http_request_duration_seconds = Histogram(
        "fgos_http_request_duration_seconds",
        "HTTP request latency in seconds",
        ["method", "path"],
    )


def observe_http_request(request: Any, response: Any, duration_s: float) -> None:
    """Record one HTTP request observation (no-op if metrics are disabled)."""

    if not _PROM_AVAILABLE:
        return

    # Best-effort: tolerate missing attrs
    method = getattr(request, "method", "") or ""
    url = getattr(request, "url", None)
    path = getattr(url, "path", "") if url is not None else ""
    status = str(getattr(response, "status_code", ""))

    fgos_http_requests_total.labels(method=method, path=path, status=status).inc()
    fgos_http_request_duration_seconds.labels(method=method, path=path).observe(duration_s)
