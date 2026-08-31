"""Test helpers shared across unit tests (no fixtures here — those live in conftest)."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from app.core.db import Base
from app.modules.consent.dependencies import CategoryVocabulary
from app.modules.consent.service import Clinician
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool


def create_sqlite_test_engine() -> AsyncEngine:
    """In-memory SQLite engine with CORRECT transaction and referential semantics.

    pysqlite's legacy transaction mode implicitly commits around SAVEPOINT statements,
    which would silently break the outer-transaction rollback our repositories rely on
    (begin_nested + request-scoped begin). The documented SQLAlchemy recipe: take over
    transaction control — disable the driver's autobegin and emit BEGIN ourselves.

    SQLite also ships with foreign keys *disabled*, so constraints the schema declares
    would silently not apply and a test could pass on a row Postgres would refuse. The
    pragma below closes that gap: what the migration declares is what the harness enforces.

    Postgres/asyncpg needs none of this; it is a test-harness fix only.
    """
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)

    @event.listens_for(engine.sync_engine, "connect")
    def _disable_driver_transaction_handling(dbapi_connection: Any, _record: Any) -> None:
        dbapi_connection.isolation_level = None

    @event.listens_for(engine.sync_engine, "connect")
    def _enforce_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    @event.listens_for(engine.sync_engine, "begin")
    def _emit_begin(connection: Any) -> None:
        connection.exec_driver_sql("BEGIN")

    return engine


def run_with_session[T](engine: AsyncEngine, action: Callable[[AsyncSession], Awaitable[T]]) -> T:
    """Run ``action`` against ``engine`` in one committed session/transaction.

    Test arrangement helper: lets sync test code seed rows on the same engine the app's
    overridden ``get_db_session`` uses (conftest ``db_engine``/``sqlite_db``).
    """

    async def scenario() -> T:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session, session.begin():
            return await action(session)

    return asyncio.run(scenario())


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


class FakeClinicianDirectory:
    """In-memory ``ClinicianDirectory`` (app/modules/consent/service.py).

    ``records`` owns the Doctor row and publishes no directory service, so consent depends
    on a protocol and this stands in for the eventual adapter. Register a clinician per
    user id; flip ``is_active`` to exercise the ADR-015 suspension rule.
    """

    def __init__(self) -> None:
        self.by_user_id: dict[UUID, Clinician] = {}

    def register(
        self, user_id: UUID, *, doctor_id: UUID, hospital_id: UUID, is_active: bool = True
    ) -> Clinician:
        clinician = Clinician(id=doctor_id, hospital_id=hospital_id, is_active=is_active)
        self.by_user_id[user_id] = clinician
        return clinician

    def suspend(self, user_id: UUID) -> None:
        current = self.by_user_id[user_id]
        self.by_user_id[user_id] = Clinician(
            id=current.id, hospital_id=current.hospital_id, is_active=False
        )

    async def get_by_user_id(self, user_id: UUID) -> Clinician | None:
        return self.by_user_id.get(user_id)


class FakeCategoryVocabularySource:
    """In-memory ``CategoryVocabularySource`` (app/modules/consent/dependencies.py).

    The record-category table belongs to ``records``; the consent boundary only needs the
    code↔id mapping, which is what this serves.
    """

    def __init__(self, by_code: dict[str, UUID]) -> None:
        self._vocabulary = CategoryVocabulary(
            by_code=dict(by_code), by_id={value: key for key, value in by_code.items()}
        )

    async def load(self) -> CategoryVocabulary:
        return self._vocabulary
