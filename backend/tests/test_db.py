import asyncio
from typing import Annotated

from app.core.db import create_session_factory, get_db_session
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


def test_session_factory_produces_working_sessions() -> None:
    async def run() -> int:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            factory = create_session_factory(engine)
            async with factory() as session:
                result = await session.execute(text("SELECT 1"))
                return int(result.scalar_one())
        finally:
            await engine.dispose()

    assert asyncio.run(run()) == 1


def test_get_db_session_dependency_yields_request_scoped_session(app: FastAPI) -> None:
    @app.get("/db-check")
    async def db_check(session: Annotated[AsyncSession, Depends(get_db_session)]) -> dict[str, int]:
        result = await session.execute(text("SELECT 1"))
        return {"value": result.scalar_one()}

    sqlite_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        with TestClient(app) as client:
            # Swap the lifespan-created engine for SQLite; the dependency reads app.state.
            app.state.db_sessionmaker = create_session_factory(sqlite_engine)
            response = client.get("/db-check")
        assert response.status_code == 200
        assert response.json() == {"value": 1}
    finally:
        asyncio.run(sqlite_engine.dispose())
