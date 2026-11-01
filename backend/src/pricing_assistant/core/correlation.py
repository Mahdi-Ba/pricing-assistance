"""Correlation IDs: one ID follows a request through the outbox, workers, logs and audit."""

import re
import uuid
from contextvars import ContextVar

import structlog

HEADER = "X-Correlation-ID"
_VALID = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
_current: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def new_correlation_id() -> str:
    return str(uuid.uuid4())


def sanitize(candidate: str | None) -> str:
    """Accept a caller-supplied ID only if it is well-formed; otherwise generate one."""
    if candidate and _VALID.fullmatch(candidate):
        return candidate
    return new_correlation_id()


def set_correlation_id(value: str) -> None:
    _current.set(value)
    structlog.contextvars.bind_contextvars(correlation_id=value)


def get_correlation_id() -> str:
    """Return the current ID, creating and binding one if none is set."""
    value = _current.get()
    if value is None:
        value = new_correlation_id()
        set_correlation_id(value)
    return value
