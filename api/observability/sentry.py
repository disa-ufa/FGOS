from __future__ import annotations

import os
from starlette.applications import Starlette

# Sentry is optional in local/dev runs.
try:
    import sentry_sdk  # type: ignore
    from sentry_sdk.integrations.asgi import SentryAsgiMiddleware  # type: ignore
except Exception:  # ImportError and any packaging edge cases
    sentry_sdk = None  # type: ignore
    SentryAsgiMiddleware = None  # type: ignore


def init_sentry(app: Starlette) -> None:
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        return

    # Dependency missing -> keep API running without instrumentation
    if sentry_sdk is None or SentryAsgiMiddleware is None:
        return

    environment = os.getenv("SENTRY_ENV", "local")
    traces_sample_rate = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0") or "0")

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        traces_sample_rate=traces_sample_rate,
        send_default_pii=False,
    )

    app.add_middleware(SentryAsgiMiddleware)
