from __future__ import annotations

import logging
import os

from api.observability.request_id import get_request_id


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Inject request_id field so formatters can include it.
        try:
            record.request_id = get_request_id()
        except Exception:
            record.request_id = "-"
        return True


def setup_logging() -> None:
    """Configure a dedicated project logger ('fgos').

    We keep it isolated from uvicorn/celery logging to avoid breaking defaults,
    but all our code should log via 'fgos.*' to get request_id correlation.
    """
    level = os.getenv("LOG_LEVEL", "INFO").upper()

    base = logging.getLogger("fgos")
    if base.handlers:
        # Already configured (avoid duplicate handlers on reload)
        return

    handler = logging.StreamHandler()
    fmt = "%(asctime)s %(levelname)s %(name)s [req=%(request_id)s] %(message)s"
    handler.setFormatter(logging.Formatter(fmt))
    handler.addFilter(RequestIdFilter())

    base.addHandler(handler)
    base.setLevel(level)
    base.propagate = False
