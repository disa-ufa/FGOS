from __future__ import annotations

import contextvars
import re
import uuid
from typing import Optional

# Correlation ID stored in a contextvar to be available in logs across awaits.
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

_ALLOWED = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def sanitize_request_id(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = value.strip()
    if not v:
        return None
    if _ALLOWED.match(v):
        return v
    return None


def generate_request_id() -> str:
    # compact & URL-safe
    return uuid.uuid4().hex


def set_request_id(request_id: str):
    return request_id_var.set(request_id)


def reset_request_id(token) -> None:
    request_id_var.reset(token)


def get_request_id() -> str:
    return request_id_var.get()
