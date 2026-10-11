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
    "audit_anchors",
    "audit_batches",
    "audit_batch_members",
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


#: ADR-027's batch tables: revision 0007, on top of the AI head ``aedb0169a4eb``.
BATCH_TABLES = {"audit_batches", "audit_batch_members"}


def _constraints(db_file: Path, table: str) -> tuple[set[str], set[str], set[str]]:
    """(unique constraint names, check constraint names, foreign key names) of ``table``."""
    engine = create_engine(f"sqlite:///{db_file}")
    try:
        inspector = inspect(engine)
        unique = {c["name"] for c in inspector.get_unique_constraints(table) if c["name"]}
        checks = {c["name"] for c in inspector.get_check_constraints(table) if c["name"]}
        foreign = {c["name"] for c in inspector.get_foreign_keys(table) if c["name"]}
        return unique, checks, foreign
    finally:
        engine.dispose()


def test_0007_creates_the_batch_tables_with_their_constraints(tmp_path: Path) -> None:
    db_file = tmp_path / "batches.db"
    command.upgrade(_config(f"sqlite+aiosqlite:///{db_file}"), "0007")

    assert _constraints(db_file, "audit_batches") == (
        {"uq_audit_batches_batch_number", "uq_audit_batches_commitment"},
        {
            "ck_audit_batches_batch_number_positive",
            "ck_audit_batches_leaf_count_positive",
            "ck_audit_batches_hash_version_v3",
        },
        set(),
    )
    assert _constraints(db_file, "audit_batch_members") == (
        {
            "uq_audit_batch_members_audit_log_id",
            "uq_audit_batch_members_batch_id_leaf_index",
        },
        {"ck_audit_batch_members_leaf_index_non_negative"},
        {
            "fk_audit_batch_members_audit_batches_batch_id",
            "fk_audit_batch_members_audit_logs_audit_log_id",
        },
    )


def test_0007_matches_the_model_metadata_the_test_harness_builds() -> None:
    """The SQLite harness creates tables from models, not migrations; the two must agree on
    the constraints the sealing design depends on."""
    from app.core.db import Base
    from sqlalchemy import CheckConstraint, UniqueConstraint

    def names(table: str, kind: type) -> set[str]:
        constraints = Base.metadata.tables[table].constraints
        return {str(c.name) for c in constraints if isinstance(c, kind)}

    assert names("audit_batches", UniqueConstraint) == {
        "uq_audit_batches_batch_number",
        "uq_audit_batches_commitment",
    }
    assert names("audit_batches", CheckConstraint) == {
        "ck_audit_batches_batch_number_positive",
        "ck_audit_batches_leaf_count_positive",
        "ck_audit_batches_hash_version_v3",
    }
    assert names("audit_batch_members", UniqueConstraint) == {
        "uq_audit_batch_members_audit_log_id",
        "uq_audit_batch_members_batch_id_leaf_index",
    }
    assert names("audit_batch_members", CheckConstraint) == {
        "ck_audit_batch_members_leaf_index_non_negative"
    }


def test_0007_downgrade_removes_only_the_batch_tables(tmp_path: Path) -> None:
    db_file = tmp_path / "batches_down.db"
    config = _config(f"sqlite+aiosqlite:///{db_file}")
    command.upgrade(config, "head")
    assert _table_names(db_file) >= BATCH_TABLES

    command.downgrade(config, "aedb0169a4eb")
    remaining = _table_names(db_file)
    assert not (BATCH_TABLES & remaining)
    assert {"audit_logs", "audit_anchors"} <= remaining

    command.upgrade(config, "head")
    assert _table_names(db_file) >= BATCH_TABLES
