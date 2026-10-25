"""arq worker entry point (ADR-014). Run with:

    arq app.workers.main.WorkerSettings

One worker class for all queues at this scale (ADR-001: deploy units are api + worker).
Task functions live in app/workers/tasks.py and are registered here by name — the API
enqueues by string (app/core/queue.py), so names are part of the internal contract.
"""

from typing import Any, ClassVar

from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.db import create_db_engine, create_session_factory
from app.core.logging import configure_logging
from app.modules.records.storage import S3ObjectStorage
from app.workers.tasks import MAX_TRIES, record_uploaded


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_db_engine(settings)
    ctx["engine"] = engine
    ctx["session_factory"] = create_session_factory(engine)
    ctx["storage"] = S3ObjectStorage(settings)


async def shutdown(ctx: dict[str, Any]) -> None:
    engine = ctx.get("engine")
    if engine is not None:
        await engine.dispose()


class WorkerSettings:
    """arq configuration object (arq reads class attributes, not instances)."""

    functions: ClassVar = [record_uploaded]
    redis_settings: ClassVar[RedisSettings] = RedisSettings.from_dsn(get_settings().redis_url)
    on_startup = startup
    on_shutdown = shutdown
    # Fail fast and retry with arq's default backoff; jobs are idempotent by design.
    max_tries: ClassVar[int] = MAX_TRIES
