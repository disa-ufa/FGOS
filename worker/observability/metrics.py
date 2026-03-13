"""Worker processing metrics.

Optional Prometheus metrics for worker stages and job outcomes.
If `prometheus_client` is unavailable, all functions become no-ops.
"""

from __future__ import annotations

try:
    from prometheus_client import Counter, Histogram

    _PROM_AVAILABLE = True
except Exception:
    Counter = Histogram = None  # type: ignore
    _PROM_AVAILABLE = False


if _PROM_AVAILABLE:
    fgos_worker_jobs_total = Counter(
        "fgos_worker_jobs_total",
        "Total number of worker jobs by final status",
        ["status"],
    )

    fgos_worker_stage_runs_total = Counter(
        "fgos_worker_stage_runs_total",
        "Total number of worker stage executions",
        ["stage"],
    )

    fgos_worker_stage_duration_seconds = Histogram(
        "fgos_worker_stage_duration_seconds",
        "Worker stage duration in seconds",
        ["stage"],
    )

    fgos_worker_job_duration_seconds = Histogram(
        "fgos_worker_job_duration_seconds",
        "Total worker job duration in seconds by final status",
        ["status"],
    )


def inc_job_status(status: str) -> None:
    if not _PROM_AVAILABLE:
        return
    fgos_worker_jobs_total.labels(status=str(status)).inc()


def observe_stage(stage: str, duration_s: float) -> None:
    if not _PROM_AVAILABLE:
        return
    stage = str(stage)
    fgos_worker_stage_runs_total.labels(stage=stage).inc()
    fgos_worker_stage_duration_seconds.labels(stage=stage).observe(duration_s)


def observe_job_duration(status: str, duration_s: float) -> None:
    if not _PROM_AVAILABLE:
        return
    fgos_worker_job_duration_seconds.labels(status=str(status)).observe(duration_s)
