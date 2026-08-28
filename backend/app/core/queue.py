"""Job-queue port (ADR-008, ADR-014): the API process only ever *enqueues*.

Consumption happens in the worker process (app/workers). Like the other external
providers, the queue sits behind an interface with an in-memory fake so tests and
credential-free dev never touch Redis (docs/SYSTEM_ARCHITECTURE.md rule 4). The real
implementation is arq (ADR-014); connections are lazy so the API boots without Redis.
"""

from abc import ABC, abstractmethod
from typing import Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings


class QueueUnavailableError(Exception):
    """Redis could not be reached or the job could not be enqueued."""


class JobQueue(ABC):
    @abstractmethod
    async def enqueue(self, task: str, /, **kwargs: object) -> None:
        """Enqueue ``task`` for the worker. Raises ``QueueUnavailableError`` on failure."""

    async def aclose(self) -> None:  # noqa: B027 — optional hook; fakes need no teardown
        """Release connections (lifespan shutdown)."""


class ArqJobQueue(JobQueue):
    """arq-backed queue. The pool is created on first use and reused afterwards."""

    def __init__(self, redis_url: str) -> None:
        self._redis_settings = RedisSettings.from_dsn(redis_url)
        self._pool: ArqRedis | None = None

    async def enqueue(self, task: str, /, **kwargs: object) -> None:
        # arq types its reserved _-prefixed keywords individually; ours are plain job
        # kwargs, so the widening to Any is safe and stays inside this adapter.
        job_kwargs: dict[str, Any] = dict(kwargs)
        try:
            if self._pool is None:
                self._pool = await create_pool(self._redis_settings)
            await self._pool.enqueue_job(task, **job_kwargs)
        except OSError as exc:  # connection refused/reset/DNS — Redis is down
            raise QueueUnavailableError() from exc
        except Exception as exc:  # redis protocol/auth errors — never leak details upward
            raise QueueUnavailableError() from exc

    async def aclose(self) -> None:
        if self._pool is not None:
            await self._pool.aclose()
            self._pool = None


class InMemoryJobQueue(JobQueue):
    """Records enqueued jobs for assertions; optionally fails to test degradation."""

    def __init__(self) -> None:
        #: (task, kwargs) tuples in enqueue order — assert on this.
        self.jobs: list[tuple[str, dict[str, object]]] = []
        #: Set to make every enqueue raise (queue-down tests).
        self.enqueue_error: QueueUnavailableError | None = None

    async def enqueue(self, task: str, /, **kwargs: object) -> None:
        if self.enqueue_error is not None:
            raise self.enqueue_error
        self.jobs.append((task, kwargs))
