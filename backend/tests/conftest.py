import asyncio
from collections.abc import AsyncIterator, Iterator

import pytest
from app.core.db import Base, create_session_factory, get_db_session
from app.core.queue import InMemoryJobQueue
from app.main import create_app
from app.modules.auth.dependencies import get_auth_provider
from app.modules.auth.fake import FakeAuthProvider
from app.modules.records.dependencies import get_job_queue, get_object_storage
from app.modules.records.fake import FakeObjectStorage
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.support import create_sqlite_test_engine


@pytest.fixture
def app() -> FastAPI:
    return create_app()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    # Context manager runs the lifespan (engine/session factory on app.state).
    # The engine connects lazily, so no real database is needed here.
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def fake_auth(app: FastAPI) -> FakeAuthProvider:
    # Replaces FirebaseAuthProvider for the whole app: tests never contact Google.
    provider = FakeAuthProvider()
    app.dependency_overrides[get_auth_provider] = lambda: provider
    return provider


@pytest.fixture
def fake_storage(app: FastAPI) -> FakeObjectStorage:
    # Replaces S3ObjectStorage for the whole app: tests never contact MinIO/S3.
    storage = FakeObjectStorage()
    app.dependency_overrides[get_object_storage] = lambda: storage
    return storage


@pytest.fixture
def fake_queue(app: FastAPI) -> InMemoryJobQueue:
    # Replaces ArqJobQueue for the whole app: tests never contact Redis.
    queue = InMemoryJobQueue()
    app.dependency_overrides[get_job_queue] = lambda: queue
    return queue


@pytest.fixture
def db_engine() -> Iterator[AsyncEngine]:
    """A per-test in-memory SQLite engine with the schema already created.

    Exposed separately from ``sqlite_db`` so tests can arrange data directly
    (seed functions, fixture rows) outside any request.
    """
    engine = create_sqlite_test_engine()

    async def _create_schema() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(_create_schema())
    yield engine
    asyncio.run(engine.dispose())


@pytest.fixture
def sqlite_db(app: FastAPI, db_engine: AsyncEngine) -> None:
    """Back get_db_session with the per-test SQLite DB.

    Mirrors production semantics exactly: one session and one transaction per request,
    committed on success, rolled back on exceptions.
    """
    factory = create_session_factory(db_engine)

    async def override_get_db_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session, session.begin():
            yield session

    app.dependency_overrides[get_db_session] = override_get_db_session
