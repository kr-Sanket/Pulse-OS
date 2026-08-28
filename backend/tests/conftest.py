import asyncio
from collections.abc import AsyncIterator, Iterator

import pytest
from app.core.db import Base, create_session_factory, get_db_session
from app.main import create_app
from app.modules.auth.dependencies import get_auth_provider
from app.modules.auth.fake import FakeAuthProvider
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

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
def sqlite_db(app: FastAPI) -> Iterator[None]:
    """Back get_db_session with a per-test in-memory SQLite DB (schema from metadata).

    Mirrors production semantics exactly: one session and one transaction per request,
    committed on success, rolled back on exceptions.
    """
    engine = create_sqlite_test_engine()
    factory = create_session_factory(engine)
    schema_ready = False

    async def override_get_db_session() -> AsyncIterator[AsyncSession]:
        nonlocal schema_ready
        if not schema_ready:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            schema_ready = True
        async with factory() as session, session.begin():
            yield session

    app.dependency_overrides[get_db_session] = override_get_db_session
    yield
    asyncio.run(engine.dispose())
