from __future__ import annotations

from celery import Celery
from api.config import settings

# API uses Celery only as a producer (enqueue tasks).
# Worker consumes tasks and defines task implementations.

celery_app = Celery(
    "fgos_api",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

