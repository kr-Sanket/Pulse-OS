from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _config(database_url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _table_names(db_file: Path) -> set[str]:
    engine = create_engine(f"sqlite:///{db_file}")
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_alembic_env_runs_upgrade_head(tmp_path: Path) -> None:
    # Executes env.py end-to-end (async engine, connection, migration context)
    # against a throwaway SQLite DB.
    config = _config(f"sqlite+aiosqlite:///{tmp_path / 'alembic-smoke.db'}")
    command.upgrade(config, "head")


def test_alembic_offline_mode_configures(tmp_path: Path) -> None:
    config = _config(f"sqlite+aiosqlite:///{tmp_path / 'alembic-offline.db'}")
    command.upgrade(config, "head", sql=True)


APP_TABLES = {
    "users",
    "patients",
    "hospitals",
    "record_categories",
    "doctors",
    "hospital_admins",
    "medical_records",
    "consent_requests",
    "consent_request_categories",
    "consent_decisions",
    "consent_grants",
    "audit_logs",
}


def test_migration_chain_is_reversible(tmp_path: Path) -> None:
    """Full chain (0001-0004): upgrade creates every table, downgrade removes them
    cleanly, and the round-trip back up succeeds (docs/DATABASE_DESIGN.md: reversible).
    """
    db_file = tmp_path / "migrate.db"
    config = _config(f"sqlite+aiosqlite:///{db_file}")

    command.upgrade(config, "head")
    assert _table_names(db_file) >= APP_TABLES

    command.downgrade(config, "base")
    assert not (APP_TABLES & _table_names(db_file))

    command.upgrade(config, "head")
    assert _table_names(db_file) >= APP_TABLES
