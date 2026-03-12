from celery import Celery

from worker.config import settings
from worker.observability.sentry import init_sentry

# Sentry (optional)
init_sentry()

celery_app = Celery(
    "fgos_worker",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["worker.tasks.process"],   # <-- ВАЖНО
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,

    # Reliability / safety (P0)
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,

    # Limits (seconds)
    task_soft_time_limit=150,
    task_time_limit=180,

    # Retry defaults
    task_default_retry_delay=10,
    task_annotations={
        "process_document": {"max_retries": 3},
    },
)
