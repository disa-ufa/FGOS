from __future__ import annotations

import os
import time
import sys

from sqlalchemy import create_engine, text, inspect
from alembic.config import Config
from alembic import command


def _alembic_config() -> Config:
    cfg = Config("/app/api/alembic.ini")
    # Alembic env.py will pull DATABASE_URL/settings, but set here too
    url = os.getenv("DATABASE_URL")
    if url:
        cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def wait_for_db(url: str, timeout_s: int = 60) -> None:
    deadline = time.time() + timeout_s
    last_err = None
    while time.time() < deadline:
        try:
            engine = create_engine(url, pool_pre_ping=True)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception as e:
            last_err = e
            time.sleep(2)
    raise RuntimeError(f"DB is not ready after {timeout_s}s: {last_err}")


def main() -> None:
    url = os.getenv("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        sys.exit(1)

    wait_for_db(url, timeout_s=60)

    engine = create_engine(url, pool_pre_ping=True)
    insp = inspect(engine)
    has_alembic = insp.has_table("alembic_version")
    has_users = insp.has_table("users")

    cfg = _alembic_config()

    if not has_alembic:
        if has_users:
            # Existing DB created via create_all. Assume schema matches initial migration and just stamp.
            print("alembic_version missing but tables exist -> stamping head")
            command.stamp(cfg, "head")
        else:
            print("Fresh DB -> running alembic upgrade head")
            command.upgrade(cfg, "head")
    else:
        print("alembic_version exists -> running alembic upgrade head")
        command.upgrade(cfg, "head")


if __name__ == "__main__":
    main()
