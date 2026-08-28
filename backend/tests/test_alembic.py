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


def test_migrations_are_reversible(tmp_path: Path) -> None:
    """Revisions 0001, 0002, 0003, 0004, 0005: upgrade creates users, patients, hospitals,
    doctors, record_categories, medical_records, access_requests, access_request_categories,
    consent_decisions, consent_grants, audit_events; downgrade removes them cleanly; and the
    round-trip back up succeeds.
    """
    db_file = tmp_path / "migrate.db"
    config = _config(f"sqlite+aiosqlite:///{db_file}")

    all_tables = {
        "users",
        "patients",
        "hospitals",
        "doctors",
        "record_categories",
        "medical_records",
        "access_requests",
        "access_request_categories",
        "consent_decisions",
        "consent_grants",
        "audit_events",
    }

    # Upgrade to 0001
    command.upgrade(config, "0001")
    assert {"users", "patients"} <= _table_names(db_file)
    assert not ((all_tables - {"users", "patients"}) & _table_names(db_file))

    # Upgrade to 0002
    command.upgrade(config, "0002")
    assert {"users", "patients", "hospitals", "doctors"} <= _table_names(db_file)
    assert not (
        (all_tables - {"users", "patients", "hospitals", "doctors"}) & _table_names(db_file)
    )

    # Upgrade to 0003
    command.upgrade(config, "0003")
    assert {
        "users",
        "patients",
        "hospitals",
        "doctors",
        "record_categories",
        "medical_records",
    } <= _table_names(db_file)
    assert not (
        {
            "access_requests",
            "access_request_categories",
            "consent_decisions",
            "consent_grants",
            "audit_events",
        }
        & _table_names(db_file)
    )

    # Upgrade to 0004
    command.upgrade(config, "0004")
    assert {
        "users",
        "patients",
        "hospitals",
        "doctors",
        "record_categories",
        "medical_records",
        "access_requests",
        "access_request_categories",
        "consent_decisions",
        "consent_grants",
    } <= _table_names(db_file)
    assert "audit_events" not in _table_names(db_file)

    # Upgrade to head (0005)
    command.upgrade(config, "head")
    assert all_tables <= _table_names(db_file)

    # Downgrade to 0004 (removes audit_events)
    command.downgrade(config, "0004")
    assert {
        "users",
        "patients",
        "hospitals",
        "doctors",
        "record_categories",
        "medical_records",
        "access_requests",
        "access_request_categories",
        "consent_decisions",
        "consent_grants",
    } <= _table_names(db_file)
    assert "audit_events" not in _table_names(db_file)

    # Downgrade to 0003 (removes consent tables)
    command.downgrade(config, "0003")
    assert {
        "users",
        "patients",
        "hospitals",
        "doctors",
        "record_categories",
        "medical_records",
    } <= _table_names(db_file)
    assert not (
        {
            "access_requests",
            "access_request_categories",
            "consent_decisions",
            "consent_grants",
            "audit_events",
        }
        & _table_names(db_file)
    )

    # Downgrade to 0002 (removes records tables)
    command.downgrade(config, "0002")
    assert {"users", "patients", "hospitals", "doctors"} <= _table_names(db_file)
    assert not (
        (all_tables - {"users", "patients", "hospitals", "doctors"}) & _table_names(db_file)
    )

    # Downgrade to 0001 (removes doctors and hospitals)
    command.downgrade(config, "0001")
    assert {"users", "patients"} <= _table_names(db_file)
    assert not ((all_tables - {"users", "patients"}) & _table_names(db_file))

    # Downgrade to base (removes all)
    command.downgrade(config, "base")
    assert not (all_tables & _table_names(db_file))

    # Round trip back to head
    command.upgrade(config, "head")
    assert all_tables <= _table_names(db_file)
