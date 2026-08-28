"""Alembic environment — async engine, URL from application Settings.

Every schema change goes through a migration generated here (CLAUDE.md principle #6:
never mutate the DB by hand). Autogenerate diffs against ``Base.metadata``; each module's
models must be imported below as they land so their tables are visible to autogenerate.
"""

import asyncio

from alembic import context
from app.core.config import get_settings
from app.core.db import Base

# Module models — imported so their tables register on Base.metadata for autogenerate.
from app.modules.audit import models as audit_models  # noqa: F401
from app.modules.auth import models as auth_models  # noqa: F401
from app.modules.consent import models as consent_models  # noqa: F401
from app.modules.doctors import models as doctors_models  # noqa: F401
from app.modules.hospitals import models as hospitals_models  # noqa: F401
from app.modules.patients import models as patients_models  # noqa: F401
from app.modules.records import models as records_models  # noqa: F401
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

config = context.config
target_metadata = Base.metadata


def _database_url() -> str:
    """sqlalchemy.url from alembic.ini/-x wins (tests, ops overrides); else app Settings."""
    return config.get_main_option("sqlalchemy.url") or get_settings().database_url


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a DB connection (`alembic upgrade head --sql`)."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_database_url())
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
