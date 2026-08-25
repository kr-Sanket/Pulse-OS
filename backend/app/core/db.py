"""Database layer: async engine, session factory, and the request-scoped session dependency.

The engine and session factory are created once per application in the lifespan handler
(app.main) and stored on ``app.state`` — no module-level connection state, so tests can
swap in a different engine (e.g. SQLite) without patching globals.

Repositories receive an ``AsyncSession`` via ``get_db_session``; domain services never
touch the session directly (Clean Architecture rule, docs/SYSTEM_ARCHITECTURE.md §Isolation).
"""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import Settings


class Base(DeclarativeBase):
    """Declarative base for all module models; its metadata is Alembic's autogenerate target."""


def create_db_engine(settings: Settings) -> AsyncEngine:
    """Create the application's async engine (connects lazily, on first use)."""
    return create_async_engine(settings.database_url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: response serialization happens after commit; don't re-fetch.
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding one AsyncSession per request (closed automatically)."""
    factory: async_sessionmaker[AsyncSession] = request.app.state.db_sessionmaker
    async with factory() as session:
        yield session
