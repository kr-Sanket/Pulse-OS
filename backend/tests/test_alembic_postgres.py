"""Migration 0007 on real PostgreSQL: upgrade, model parity, constraints, downgrade safety.

**Opt-in.** Skipped unless ``PULSEOS_TEST_POSTGRES_URL`` names a PostgreSQL server the suite
may use (``postgresql+asyncpg://…``). The database in that URL is used only to issue
``CREATE DATABASE`` / ``DROP DATABASE``: every test runs Alembic against a **freshly created,
uniquely named database** (``pulseos_m6_mig_<hex>``) and drops it afterwards, so no existing
database is ever migrated. Point the URL at a disposable server, never at real data.

``test_alembic.py`` covers the same revision on SQLite; this module covers what only
PostgreSQL can show — the constraints as PostgreSQL creates and enforces them, and the absence
of drift between migration 0007 and the models the application maps.
"""

import asyncio
import datetime as dt
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from app.core.db import Base
from app.modules.auth.domain import Role
from app.modules.auth.models import User
from app.modules.consent.batch_service import AuditBatchService
from app.modules.consent.models import AuditAction, AuditLog
from app.modules.consent.repository import AuditBatchRepository
from app.modules.consent.service import HASH_SCHEME_V3, recompute_event_hash
from app.modules.patients.models import Patient
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

POSTGRES_URL = os.environ.get("PULSEOS_TEST_POSTGRES_URL", "")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL.startswith("postgresql"),
    reason="PostgreSQL tests are opt-in: set PULSEOS_TEST_POSTGRES_URL to a scratch server",
)

BACKEND_DIR = Path(__file__).resolve().parent.parent
#: The revision migration 0007 builds on, and the one its downgrade returns to.
PRE_0007 = "aedb0169a4eb"
BATCH_TABLES = {"audit_batches", "audit_batch_members"}

#: Constraint names and kinds PostgreSQL must report for each batch table
#: (``pg_constraint.contype``: p primary key, u unique, c check, f foreign key).
EXPECTED_CONSTRAINTS = {
    "audit_batches": {
        ("p", "pk_audit_batches"),
        ("u", "uq_audit_batches_batch_number"),
        ("u", "uq_audit_batches_commitment"),
        ("c", "ck_audit_batches_batch_number_positive"),
        ("c", "ck_audit_batches_leaf_count_positive"),
        ("c", "ck_audit_batches_hash_version_v3"),
    },
    "audit_batch_members": {
        ("p", "pk_audit_batch_members"),
        ("u", "uq_audit_batch_members_audit_log_id"),
        ("u", "uq_audit_batch_members_batch_id_leaf_index"),
        ("c", "ck_audit_batch_members_leaf_index_non_negative"),
        ("f", "fk_audit_batch_members_audit_batches_batch_id"),
        ("f", "fk_audit_batch_members_audit_logs_audit_log_id"),
    },
}


def _alembic(url: URL) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    # Explicit, so env.py never falls back to application settings; ``%`` is escaped because
    # Config interpolates option values.
    config.set_main_option(
        "sqlalchemy.url", url.render_as_string(hide_password=False).replace("%", "%%")
    )
    return config


async def _admin(statement: str) -> None:
    """Run one CREATE/DROP DATABASE on the URL's server, outside a transaction."""
    engine = create_async_engine(POSTGRES_URL, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            await connection.execute(text(statement))
    finally:
        await engine.dispose()


@contextmanager
def _fresh_database() -> Iterator[URL]:
    """A new, empty, uniquely named database — created here, dropped here, nothing else."""
    name = f"pulseos_m6_mig_{uuid4().hex[:12]}"
    asyncio.run(_admin(f'CREATE DATABASE "{name}"'))
    try:
        yield make_url(POSTGRES_URL).set(database=name)
    finally:
        asyncio.run(_admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


async def _scalar(url: URL, sql: str) -> object:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            return (await connection.execute(text(sql))).scalar_one()
    finally:
        await engine.dispose()


async def _tables(url: URL) -> set[str]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            rows = await connection.execute(
                text("select tablename from pg_tables where schemaname = 'public'")
            )
            return set(rows.scalars())
    finally:
        await engine.dispose()


def test_0007_upgrade_creates_the_batch_tables_and_constraints() -> None:
    with _fresh_database() as url:
        command.upgrade(_alembic(url), "head")

        async def inspect() -> dict[str, set[tuple[str, str]]]:
            engine = create_async_engine(url)
            try:
                async with engine.connect() as connection:
                    rows = await connection.execute(
                        text(
                            # contype is PostgreSQL's internal "char"; cast so the driver
                            # returns text rather than bytes.
                            "select conrelid::regclass::text, contype::text, conname"
                            " from pg_constraint"
                            " where conrelid::regclass::text in"
                            " ('audit_batches', 'audit_batch_members')"
                        )
                    )
                    found: dict[str, set[tuple[str, str]]] = {t: set() for t in BATCH_TABLES}
                    for table, kind, name in rows.tuples():
                        found[table].add((str(kind), name))
                    return found
            finally:
                await engine.dispose()

        assert asyncio.run(_scalar(url, "select version_num from alembic_version")) == "0007"
        assert asyncio.run(inspect()) == EXPECTED_CONSTRAINTS


def test_0007_matches_the_mapped_models() -> None:
    """No drift between what migration 0007 creates and what the models declare."""
    with _fresh_database() as url:
        command.upgrade(_alembic(url), "head")

        async def drift() -> list[object]:
            engine = create_async_engine(url)
            try:
                async with engine.connect() as connection:
                    differences = await connection.run_sync(
                        lambda sync: compare_metadata(
                            MigrationContext.configure(sync), Base.metadata
                        )
                    )
            finally:
                await engine.dispose()
            return [d for d in differences if any(t in repr(d) for t in BATCH_TABLES)]

        assert asyncio.run(drift()) == []


@pytest.mark.parametrize(
    ("label", "values"),
    [
        ("leaf_count", "1, 1, 3, 0"),
        ("hash_version", "1, 1, 2, 1"),
        ("batch_number", "0, 1, 3, 1"),
    ],
)
def test_0007_check_constraints_are_enforced(label: str, values: str) -> None:
    """``values`` is (batch_number, protocol_version, hash_version, leaf_count)."""
    with _fresh_database() as url:
        command.upgrade(_alembic(url), "head")

        async def attempt() -> tuple[str, str]:
            engine = create_async_engine(url)
            try:
                async with engine.connect() as connection:
                    try:
                        await connection.execute(
                            text(
                                "insert into audit_batches (id, batch_number, protocol_version,"
                                " hash_version, leaf_count, root, commitment, first_occurred_at,"
                                f" last_occurred_at) values (gen_random_uuid(), {values},"
                                " repeat('a', 64), repeat('b', 64), now(), now())"
                            )
                        )
                    except Exception as exc:  # the driver error is the assertion's subject
                        driver = getattr(getattr(exc, "orig", None), "__cause__", None)
                        return type(driver).__name__, str(getattr(driver, "sqlstate", ""))
                    return "accepted", ""
            finally:
                await engine.dispose()

        assert asyncio.run(attempt()) == ("CheckViolationError", "23514"), label


def test_0007_downgrade_drops_only_the_batch_tables_and_keeps_the_audit_trail() -> None:
    with _fresh_database() as url:
        config = _alembic(url)
        command.upgrade(config, "head")
        base = dt.datetime(2026, 10, 11, 9, 0, tzinfo=dt.UTC)

        async def seed_and_seal() -> tuple[str, str]:
            engine = create_async_engine(url)
            try:
                factory = async_sessionmaker(engine, expire_on_commit=False)
                async with factory() as session, session.begin():
                    user = User(firebase_uid=f"fb-{uuid4()}", role=Role.PATIENT)
                    session.add(user)
                    await session.flush()
                    patient = Patient(
                        user_id=user.id, health_id="PHI-IND-2026-1QE8DVR", full_name="Synthetic"
                    )
                    session.add(patient)
                    await session.flush()
                    event = AuditLog(
                        id=uuid4(),
                        actor_user_id=user.id,
                        actor_role=Role.PATIENT,
                        action=AuditAction.RECORD_VIEWED,
                        patient_id=patient.id,
                        request_context=None,
                        occurred_at=base,
                        actor_hospital_id=None,
                        hash_version=HASH_SCHEME_V3,
                        event_hash="",
                    )
                    event.event_hash = recompute_event_hash(event)
                    session.add(event)
                async with factory() as session, session.begin():
                    batch = await AuditBatchService(
                        batches=AuditBatchRepository(session),
                        max_size=256,
                        backlog_threshold=dt.timedelta(seconds=900),
                    ).seal_next_batch()
                    assert batch is not None
                return str(event.id), event.event_hash
            finally:
                await engine.dispose()

        event_id, digest = asyncio.run(seed_and_seal())
        assert asyncio.run(_scalar(url, "select count(*) from audit_batch_members")) == 1

        command.downgrade(config, PRE_0007)
        tables = asyncio.run(_tables(url))
        assert not BATCH_TABLES & tables
        assert {"audit_logs", "audit_anchors"} <= tables
        assert asyncio.run(_scalar(url, "select version_num from alembic_version")) == PRE_0007
        stored = asyncio.run(
            _scalar(url, f"select event_hash from audit_logs where id = '{event_id}'")
        )
        assert stored == digest  # the audit trail survives the downgrade untouched

        command.upgrade(config, "head")
        assert asyncio.run(_tables(url)) >= BATCH_TABLES
        assert asyncio.run(_scalar(url, "select count(*) from audit_batches")) == 0
        assert asyncio.run(_scalar(url, "select version_num from alembic_version")) == "0007"
