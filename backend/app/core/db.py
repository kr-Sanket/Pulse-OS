"""Database layer: async engine, session factory, and the request-scoped session dependency.

The engine and session factory are created once per application in the lifespan handler
(app.main) and stored on ``app.state`` — no module-level connection state, so tests can
swap in a different engine (e.g. SQLite) without patching globals.

Repositories receive an ``AsyncSession`` via ``get_db_session``; domain services never
touch the session directly (Clean Architecture rule, docs/SYSTEM_ARCHITECTURE.md §Isolation).
"""

import uuid
from collections.abc import AsyncIterator
from datetime import datetime

from fastapi import Request
from sqlalchemy import DateTime, MetaData, Uuid, func
from sqlalchemy.dialects import sqlite as sqlite_dialect
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import Settings

# Deterministic constraint names so migrations can ALTER/DROP them by name on every
# backend (docs/DATABASE_DESIGN.md: migrations are reversible, reviewed).
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(referred_table_name)s_%(column_0_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base for all module models; its metadata is Alembic's autogenerate target."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKeyMixin:
    """UUID primary key, generated client-side (docs/DATABASE_DESIGN.md principle 6)."""

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)


# SQLite stores datetimes as text and CURRENT_TIMESTAMP writes no microseconds, while
# SQLAlchemy's default bind format always appends them — so a keyset-pagination equality
# (WHERE created_at = :cursor) could never match on SQLite. Truncating microseconds on
# the SQLite side makes storage and bind formats identical; ties are broken by id in
# every keyset query. Postgres (real timestamptz) is unaffected by the variant.
_TIMESTAMP = DateTime(timezone=True).with_variant(
    # The sqlite dialect ships no annotations for DATETIME — the call itself is typed fine.
    sqlite_dialect.DATETIME(truncate_microseconds=True),  # type: ignore[no-untyped-call]
    "sqlite",
)


class TimestampMixin:
    """UTC ``created_at``/``updated_at`` on every table (docs/DATABASE_DESIGN.md principle 6)."""

    created_at: Mapped[datetime] = mapped_column(
        _TIMESTAMP, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        _TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False
    )


def create_db_engine(settings: Settings) -> AsyncEngine:
    """Create the application's async engine (connects lazily, on first use)."""
    return create_async_engine(settings.database_url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: response serialization happens after commit; don't re-fetch.
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one AsyncSession and one transaction per request.

    Commits when the request handler returns cleanly, rolls back on any exception —
    services and repositories only flush (and may use savepoints); they never commit.
    This makes every use case atomic by construction (docs/API_GUIDELINES.md:
    state-changing endpoints are transactional).
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.db_sessionmaker
    async with factory() as session, session.begin():
        yield session
