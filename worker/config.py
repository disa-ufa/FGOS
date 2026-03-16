from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    storage_dir: str = "/data"
    celery_broker_url: str
    celery_result_backend: str

    worker_metrics_enabled: bool = True
    worker_metrics_host: str = "0.0.0.0"
    worker_metrics_port: int = 9108

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()