"""Test helpers shared across unit tests (no fixtures here — those live in conftest)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from app.core.db import Base
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool


def create_sqlite_test_engine() -> AsyncEngine:
    """In-memory SQLite engine with CORRECT transaction semantics.

    pysqlite's legacy transaction mode implicitly commits around SAVEPOINT statements,
    which would silently break the outer-transaction rollback our repositories rely on
    (begin_nested + request-scoped begin). The documented SQLAlchemy recipe: take over
    transaction control — disable the driver's autobegin and emit BEGIN ourselves.
    Postgres/asyncpg needs none of this; it is a test-harness fix only.
    """
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)

    @event.listens_for(engine.sync_engine, "connect")
    def _disable_driver_transaction_handling(dbapi_connection: Any, _record: Any) -> None:
        dbapi_connection.isolation_level = None

    @event.listens_for(engine.sync_engine, "begin")
    def _emit_begin(connection: Any) -> None:
        connection.exec_driver_sql("BEGIN")

    return engine


@asynccontextmanager
async def sqlite_session() -> AsyncIterator[AsyncSession]:
    """One in-memory SQLite session inside a transaction, schema created from metadata."""
    engine = create_sqlite_test_engine()
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session, session.begin():
            yield session
    finally:
        await engine.dispose()
