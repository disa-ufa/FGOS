import logging
import os
from pathlib import Path

from celery import Celery
from celery.signals import worker_process_shutdown, worker_ready

from worker.config import settings
from worker.observability.sentry import init_sentry

logger = logging.getLogger(__name__)

# Sentry (optional)
init_sentry()

_PROM_DIR = Path(os.environ.get("PROMETHEUS_MULTIPROC_DIR", "")).expanduser() if os.environ.get("PROMETHEUS_MULTIPROC_DIR") else None


def _prepare_prometheus_dir() -> None:
    if not _PROM_DIR:
        return
    _PROM_DIR.mkdir(parents=True, exist_ok=True)
    for path in _PROM_DIR.glob("*.db"):
        try:
            path.unlink()
        except Exception:
            logger.warning("worker metrics: failed to remove stale file %s", path)


# Important: clear stale multiprocess metric files before worker pool starts.
_prepare_prometheus_dir()

celery_app = Celery(
    "fgos_worker",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["worker.tasks.process"],
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


@worker_ready.connect
def start_metrics_server(**kwargs):
    if not settings.worker_metrics_enabled:
        logger.info("worker metrics: disabled")
        return

    try:
        from prometheus_client import CollectorRegistry, start_http_server
        from prometheus_client import multiprocess

        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)

        start_http_server(
            settings.worker_metrics_port,
            addr=settings.worker_metrics_host,
            registry=registry,
        )
        logger.info(
            "worker metrics: listening on http://%s:%s (multiprocess=%s)",
            settings.worker_metrics_host,
            settings.worker_metrics_port,
            bool(_PROM_DIR),
        )
    except Exception:
        logger.exception("worker metrics: failed to start")


@worker_process_shutdown.connect
def mark_worker_process_dead(pid=None, **kwargs):
    if not _PROM_DIR or pid is None:
        return
    try:
        from prometheus_client import multiprocess

        multiprocess.mark_process_dead(pid)
    except Exception:
        logger.exception("worker metrics: failed to mark process dead pid=%s", pid)