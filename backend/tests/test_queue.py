"""Job-queue port tests: the in-memory fake and the arq adapter (Redis fully mocked)."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from app.core.queue import ArqJobQueue, InMemoryJobQueue, QueueUnavailableError


def test_in_memory_queue_records_jobs_in_order() -> None:
    async def scenario() -> None:
        queue = InMemoryJobQueue()
        await queue.enqueue("record_uploaded", record_id="abc")
        await queue.enqueue("record_uploaded", record_id="def")
        assert queue.jobs == [
            ("record_uploaded", {"record_id": "abc"}),
            ("record_uploaded", {"record_id": "def"}),
        ]

    asyncio.run(scenario())


def test_in_memory_queue_failure_injection() -> None:
    async def scenario() -> None:
        queue = InMemoryJobQueue()
        queue.enqueue_error = QueueUnavailableError()
        with pytest.raises(QueueUnavailableError):
            await queue.enqueue("record_uploaded", record_id="abc")
        assert queue.jobs == []

    asyncio.run(scenario())


def test_arq_queue_creates_pool_lazily_and_enqueues() -> None:
    async def scenario() -> None:
        pool = AsyncMock()
        with patch("app.core.queue.create_pool", AsyncMock(return_value=pool)) as create:
            queue = ArqJobQueue("redis://localhost:6379/0")
            create.assert_not_awaited()  # constructing the queue must not connect

            await queue.enqueue("record_uploaded", record_id="abc")
            await queue.enqueue("record_uploaded", record_id="def")

            create.assert_awaited_once()  # pool is reused across enqueues
            assert pool.enqueue_job.await_count == 2
            pool.enqueue_job.assert_awaited_with("record_uploaded", record_id="def")

            await queue.aclose()
            pool.aclose.assert_awaited_once()

    asyncio.run(scenario())


@pytest.mark.parametrize("raised", [ConnectionRefusedError(), RuntimeError("redis auth")])
def test_arq_queue_maps_all_failures_to_domain_error(raised: Exception) -> None:
    async def scenario() -> None:
        with patch("app.core.queue.create_pool", AsyncMock(side_effect=raised)):
            queue = ArqJobQueue("redis://localhost:6379/0")
            with pytest.raises(QueueUnavailableError):
                await queue.enqueue("record_uploaded", record_id="abc")

    asyncio.run(scenario())


def test_arq_queue_aclose_without_pool_is_a_noop() -> None:
    async def scenario() -> None:
        queue = ArqJobQueue("redis://localhost:6379/0")
        await queue.aclose()  # must not raise or connect

    asyncio.run(scenario())


def test_worker_registry_matches_the_enqueued_task_name() -> None:
    """The API enqueues by string; the worker registers by function name — pin the pair."""
    from app.modules.records.service import RECORD_UPLOADED_TASK
    from app.workers.main import WorkerSettings

    registered: list[Any] = list(WorkerSettings.functions)
    assert RECORD_UPLOADED_TASK in {fn.__name__ for fn in registered}
