"""Test helpers shared across unit tests (no fixtures here — those live in conftest)."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any
from uuid import UUID

from app.core.db import Base
from app.modules.consent.dependencies import CategoryVocabulary
from app.modules.consent.service import Clinician
from sqlalchemy import Engine, event
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


@contextmanager
def counting_statements(engine: AsyncEngine) -> Iterator[list[str]]:
    """Record every SQL statement the engine emits while the block runs.

    The N+1 guard used by more than one suite: an assertion about *how many* statements a
    page costs is the only kind that catches a per-row lookup creeping back in, because the
    result is identical either way.
    """
    statements: list[str] = []

    def _record(_conn: Any, _cursor: Any, statement: str, *_rest: Any, **_kwargs: Any) -> None:
        statements.append(statement)

    sync_engine: Engine = engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", _record)
    try:
        yield statements
    finally:
        event.remove(sync_engine, "before_cursor_execute", _record)


@asynccontextmanager
async def sqlite_session_with_engine() -> AsyncIterator[tuple[AsyncSession, AsyncEngine]]:
    """As ``sqlite_session``, but also handing back the engine.

    Only tests that instrument SQL need it — a statement counter listens on the engine, not
    on the session (see the N+1 guards in test_staff_directory.py).
    """
    engine = create_sqlite_test_engine()
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session, session.begin():
            yield session, engine
    finally:
        await engine.dispose()


@asynccontextmanager
async def sqlite_session() -> AsyncIterator[AsyncSession]:
    """One in-memory SQLite session inside a transaction, schema created from metadata."""
    async with sqlite_session_with_engine() as (session, _engine):
        yield session


class FakeClinicianDirectory:
    """In-memory ``ClinicianDirectory`` (app/modules/consent/service.py).

    ``records`` owns the Doctor row and publishes no directory service, so consent depends
    on a protocol and this stands in for the eventual adapter. Register a clinician per
    user id; flip ``is_active`` to exercise the ADR-015 suspension rule.
    """

    def __init__(self) -> None:
        self.by_user_id: dict[UUID, Clinician] = {}
        self.by_doctor_id: dict[UUID, UUID] = {}

    def register(
        self, user_id: UUID, *, doctor_id: UUID, hospital_id: UUID, is_active: bool = True
    ) -> Clinician:
        clinician = Clinician(id=doctor_id, hospital_id=hospital_id, is_active=is_active)
        self.by_user_id[user_id] = clinician
        self.by_doctor_id[doctor_id] = user_id
        return clinician

    def suspend(self, user_id: UUID) -> None:
        current = self.by_user_id[user_id]
        self.by_user_id[user_id] = Clinician(
            id=current.id, hospital_id=current.hospital_id, is_active=False
        )

    async def get_by_user_id(self, user_id: UUID) -> Clinician | None:
        return self.by_user_id.get(user_id)

    async def get_user_id_by_doctor_id(self, doctor_id: UUID) -> UUID | None:
        return self.by_doctor_id.get(doctor_id)


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
