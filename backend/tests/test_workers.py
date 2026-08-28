"""Worker-skeleton tests (M2): registry wiring and the no-op upload task."""

import asyncio
import logging

import pytest
from app.workers.main import WorkerSettings, startup
from app.workers.tasks import record_uploaded


def test_worker_settings_register_the_upload_task() -> None:
    names = {fn.__name__ for fn in WorkerSettings.functions}
    assert names == {"record_uploaded"}
    assert WorkerSettings.max_tries == 5


def test_record_uploaded_logs_only_the_opaque_id(caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> None:
        with caplog.at_level(logging.INFO, logger="app.workers.tasks"):
            await record_uploaded({}, record_id="11111111-2222-3333-4444-555555555555")
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.record_id == "11111111-2222-3333-4444-555555555555"  # type: ignore[attr-defined]

    asyncio.run(scenario())


def test_worker_startup_configures_logging() -> None:
    async def scenario() -> None:
        await startup({})  # must not raise; idempotent logging setup

    asyncio.run(scenario())
