from __future__ import annotations
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    bot_token: str
    api_url: str = "http://api:8000"
    service_secret: str

    # Telegram Bot API может отказать в getFile/download для больших файлов.
    # Делаем ограничение на стороне бота (в МБ), чтобы не падать.
    tg_max_file_mb: int = 19  # env: TG_MAX_FILE_MB

    class Config:
        env_file = ".env"
        case_sensitive = False

    @property
    def tg_max_file_bytes(self) -> int:
        return int(self.tg_max_file_mb) * 1024 * 1024

settings = Settings()