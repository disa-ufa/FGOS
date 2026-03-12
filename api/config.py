from __future__ import annotations
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    storage_dir: str = "/data"
    celery_broker_url: str
    celery_result_backend: str

    # Shared secret used to authenticate bot/service calls to the API.
    # Must be the same value in bot and api containers.
    service_secret: str

    # Upload limits (P0)
    max_upload_mb: int = 25

    class Config:
        env_file = ".env"
        case_sensitive = False

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb) * 1024 * 1024

settings = Settings()