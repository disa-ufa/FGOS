from __future__ import annotations

import logging
import os

from worker.observability.request_id import get_request_id


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.request_id = get_request_id()
        except Exception:
            record.request_id = "-"
        return True


def setup_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()

    base = logging.getLogger("fgos")
    if base.handlers:
        return

    handler = logging.StreamHandler()
    fmt = "%(asctime)s %(levelname)s %(name)s [req=%(request_id)s] %(message)s"
    handler.setFormatter(logging.Formatter(fmt))
    handler.addFilter(RequestIdFilter())

    base.addHandler(handler)
    base.setLevel(level)
    base.propagate = False

