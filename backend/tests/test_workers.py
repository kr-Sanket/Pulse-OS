"""Worker wiring tests: registry, retry budget, and startup/shutdown resources.

The indexing behaviour of ``record_uploaded`` is pinned in tests/test_upload_indexing.py.
"""

import asyncio
from typing import Any

from app.workers.main import WorkerSettings, shutdown, startup
from app.workers.tasks import MAX_TRIES


def test_worker_settings_register_the_upload_task() -> None:
    names = {fn.__name__ for fn in WorkerSettings.functions}
    assert names == {"record_uploaded"}
    assert WorkerSettings.max_tries == MAX_TRIES == 5


def test_worker_startup_builds_resources_and_shutdown_disposes_them() -> None:
    async def scenario() -> None:
        ctx: dict[str, Any] = {}
        await startup(ctx)  # builds lazily — no database or S3 connection is opened here
        assert {"engine", "session_factory", "storage"} <= ctx.keys()
        await shutdown(ctx)
        await shutdown({})  # tolerates a context startup never filled

    asyncio.run(scenario())
