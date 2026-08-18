"""Structured logging.

Logs are emitted as one JSON object per line. Machine-readable logs matter more
here than usual: a single analysis run produces events across the API, the queue
and the workers, and correlating them by request id is the only practical way to
follow one submission through the system.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

#: Correlation id for the in-flight request. Set by the API middleware, read by
#: every log record emitted while handling that request.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_RESERVED = frozenset(
    {
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "module", "msecs",
        "message", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "thread", "threadName", "taskName",
    }
)


class JsonFormatter(logging.Formatter):
    """Render a log record as a single JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
        }

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        # Anything passed via `extra=` lands on the record; forward it verbatim.
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value

        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON formatter on the root logger.

    Safe to call more than once; existing handlers are replaced rather than
    accumulated, which matters because the test suite builds many app instances.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())


def get_logger(name: str) -> logging.Logger:
    """Return a named logger."""
    return logging.getLogger(name)


def set_request_id(request_id: str | None) -> None:
    """Bind a correlation id to the current context."""
    request_id_var.set(request_id)
