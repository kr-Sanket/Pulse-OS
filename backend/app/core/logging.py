"""Structured JSON logging.

Hard rule (docs/SECURITY.md §Logging hygiene): no PHI in logs — no names, phone numbers,
health-profile content, filenames, or request/response bodies. Log opaque IDs only.

Every record carries the current request id (set by RequestContextMiddleware via a
contextvar), so any log line emitted while handling a request is correlatable with the
``X-Request-Id`` the client saw.
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, Final

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# logging.LogRecord attributes that are not user-supplied ``extra`` fields.
_RESERVED_RECORD_ATTRS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


class JsonFormatter(logging.Formatter):
    """One JSON object per line: timestamp, level, logger, message, request_id, extras."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = request_id_var.get()
        if request_id is not None:
            payload["request_id"] = request_id
        for key, value in record.__dict__.items():
            if key not in _RESERVED_RECORD_ATTRS and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


#: Loggers that can emit SQL parameters or document bytes; never below WARNING.
PHI_BEARING_LOGGERS: Final = (
    "sqlalchemy.engine",
    "sqlalchemy.pool",
    "aiosqlite",
    "asyncpg",
    "pypdf",
)


def configure_logging(level: str) -> None:
    """Route all logging (including uvicorn's) through one JSON handler on stdout."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [handler]

    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
    # RequestContextMiddleware emits the access log; uvicorn's would be a duplicate.
    logging.getLogger("uvicorn.access").disabled = True
    # Database drivers log statements *with bound parameters* at INFO/DEBUG — patient names,
    # extracted document text. They inherit the root level, so PULSEOS_LOG_LEVEL=DEBUG would
    # otherwise write PHI to the log. Pinned to WARNING whatever the root level (SECURITY.md).
    for name in PHI_BEARING_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
