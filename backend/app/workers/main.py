"""arq worker entry point (ADR-014). Run with:

    arq app.workers.main.WorkerSettings

One worker class for all queues at this scale (ADR-001: deploy units are api + worker).
Task functions live in app/workers/tasks.py and are registered here by name — the API
enqueues by string (app/core/queue.py), so names are part of the internal contract.
"""

from typing import Any, ClassVar

from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.workers.tasks import record_uploaded


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging(get_settings().log_level)


class WorkerSettings:
    """arq configuration object (arq reads class attributes, not instances)."""

    functions: ClassVar = [record_uploaded]
    redis_settings: ClassVar[RedisSettings] = RedisSettings.from_dsn(get_settings().redis_url)
    on_startup = startup
    # Fail fast and retry with arq's default backoff; jobs are idempotent by design.
    max_tries: ClassVar[int] = 5
