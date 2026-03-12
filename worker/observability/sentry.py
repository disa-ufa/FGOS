from __future__ import annotations

import os

import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration


def init_sentry() -> None:
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        return

    environment = os.getenv("SENTRY_ENV", "local")
    traces_sample_rate = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0") or "0")

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        traces_sample_rate=traces_sample_rate,
        integrations=[CeleryIntegration()],
        send_default_pii=False,
    )
