from __future__ import annotations

import hashlib
import hmac
import time
from fastapi import HTTPException, Request

from api.config import settings


HEADER_TS = "X-Service-Timestamp"
HEADER_SIG = "X-Service-Signature"

# How much clock skew / replay window we allow (seconds).
MAX_SKEW_SECONDS = 300


def _signature(secret: str, ts: int, method: str, path_qs: str) -> str:
    """Compute request signature.

    We intentionally sign only (timestamp, method, path+query) to keep it stable
    for multipart/form-data uploads.
    """
    msg = f"{ts}.{method.upper()}.{path_qs}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


async def require_service_auth(request: Request) -> None:
    """FastAPI dependency: require valid service signature."""
    secret = getattr(settings, "service_secret", None)
    if not secret:
        # Misconfiguration - do not silently allow.
        raise HTTPException(status_code=500, detail="SERVICE_SECRET is not configured")

    ts_raw = request.headers.get(HEADER_TS)
    sig = request.headers.get(HEADER_SIG)
    if not ts_raw or not sig:
        raise HTTPException(status_code=401, detail="Missing service authentication headers")

    try:
        ts = int(ts_raw)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid service timestamp")

    now = int(time.time())
    if abs(now - ts) > MAX_SKEW_SECONDS:
        raise HTTPException(status_code=401, detail="Service signature expired")

    path_qs = request.url.path
    if request.url.query:
        path_qs += f"?{request.url.query}"

    expected = _signature(secret, ts, request.method, path_qs)
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(status_code=401, detail="Invalid service signature")