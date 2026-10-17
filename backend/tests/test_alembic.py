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
    "notifications",
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


#: ADR-031's notifications table: revision 0008, on top of 0007.
NOTIFICATION_TABLES = {"notifications"}


def test_0008_creates_notifications_table_with_constraints(tmp_path: Path) -> None:
    db_file = tmp_path / "notifications.db"
    command.upgrade(_config(f"sqlite+aiosqlite:///{db_file}"), "0008")

    assert "notifications" in _table_names(db_file)
    _unique, _checks, foreign = _constraints(db_file, "notifications")
    # notifications has no unique constraints, but has foreign keys to users,
    # consent_requests, doctors, and hospitals
    assert foreign == {
        "fk_notifications_users_recipient_user_id",
        "fk_notifications_consent_requests_reference_request_id",
        "fk_notifications_doctors_actor_doctor_id",
        "fk_notifications_hospitals_actor_hospital_id",
    }

    # Inspect foreign key ondelete rules
    engine = create_engine(f"sqlite:///{db_file}")
    try:
        fks = {fk["name"]: fk for fk in inspect(engine).get_foreign_keys("notifications")}
        # recipient_user_id has NO cascade / NO ondelete rule (tombstone policy)
        assert fks["fk_notifications_users_recipient_user_id"].get("options", {}).get(
            "ondelete"
        ) in (None, "NO ACTION", "RESTRICT")
        # structured references have SET NULL ondelete
        assert (
            fks["fk_notifications_consent_requests_reference_request_id"]
            .get("options", {})
            .get("ondelete")
            == "SET NULL"
        )
        assert (
            fks["fk_notifications_doctors_actor_doctor_id"].get("options", {}).get("ondelete")
            == "SET NULL"
        )
        assert (
            fks["fk_notifications_hospitals_actor_hospital_id"].get("options", {}).get("ondelete")
            == "SET NULL"
        )
    finally:
        engine.dispose()


def test_0008_matches_model_metadata() -> None:
    """The ORM model metadata and migration 0008 must agree on table name, columns, indexes and
    foreign key options."""
    from app.core.db import Base
    from app.modules.notifications.models import Notification  # noqa: F401

    table = Base.metadata.tables["notifications"]
    index_names = {idx.name for idx in table.indexes}
    assert index_names == {
        "ix_notifications_recipient_unread_created",
        "ix_notifications_recipient_created",
    }

    col_names = set(table.columns.keys())
    assert col_names == {
        "id",
        "recipient_user_id",
        "event_type",
        "title",
        "message",
        "reference_request_id",
        "actor_doctor_id",
        "actor_hospital_id",
        "is_read",
        "read_at",
        "created_at",
        "updated_at",
    }

    # Verify foreign key ondelete parity on ORM model metadata
    fk_by_col = {fk.parent.name: fk for fk in table.foreign_keys}
    assert fk_by_col["recipient_user_id"].ondelete is None
    assert fk_by_col["reference_request_id"].ondelete == "SET NULL"
    assert fk_by_col["actor_doctor_id"].ondelete == "SET NULL"
    assert fk_by_col["actor_hospital_id"].ondelete == "SET NULL"


def test_0008_downgrade_removes_notifications_table(tmp_path: Path) -> None:
    db_file = tmp_path / "notifications_down.db"
    config = _config(f"sqlite+aiosqlite:///{db_file}")
    command.upgrade(config, "head")
    assert _table_names(db_file) >= NOTIFICATION_TABLES

    command.downgrade(config, "0007")
    remaining = _table_names(db_file)
    assert not (NOTIFICATION_TABLES & remaining)
    assert remaining >= BATCH_TABLES

    command.upgrade(config, "head")
    assert _table_names(db_file) >= NOTIFICATION_TABLES


def test_0009_adds_verification_columns_and_fk(tmp_path: Path) -> None:
    db_file = tmp_path / "hospitals_0009.db"
    config = _config(f"sqlite+aiosqlite:///{db_file}")
    command.upgrade(config, "0009")

    engine = create_engine(f"sqlite:///{db_file}")
    try:
        inspector = inspect(engine)
        columns = {col["name"]: col for col in inspector.get_columns("hospitals")}
        assert "verified_by_user_id" in columns
        assert columns["verified_by_user_id"]["nullable"] is True
        assert "verified_at" in columns
        assert columns["verified_at"]["nullable"] is True

        fks = inspector.get_foreign_keys("hospitals")
        verif_fks = [fk for fk in fks if fk.get("constrained_columns") == ["verified_by_user_id"]]
        assert len(verif_fks) == 1
        assert verif_fks[0]["referred_table"] == "users"
        assert verif_fks[0]["referred_columns"] == ["id"]
    finally:
        engine.dispose()


def test_0009_matches_model_metadata() -> None:
    from app.core.db import Base
    from app.modules.records.models import Hospital  # noqa: F401

    table = Base.metadata.tables["hospitals"]
    col_names = set(table.columns.keys())
    assert "verified_by_user_id" in col_names
    assert "verified_at" in col_names
    assert table.columns["verified_by_user_id"].nullable is True
    assert table.columns["verified_at"].nullable is True

    fk_by_col = {fk.parent.name: fk for fk in table.foreign_keys}
    assert "verified_by_user_id" in fk_by_col
    assert fk_by_col["verified_by_user_id"].target_fullname == "users.id"


def test_0009_downgrade_removes_verification_columns_cleanly(tmp_path: Path) -> None:
    db_file = tmp_path / "hospitals_down.db"
    config = _config(f"sqlite+aiosqlite:///{db_file}")

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{db_file}")
    try:
        cols_head = {col["name"] for col in inspect(engine).get_columns("hospitals")}
        assert "verified_by_user_id" in cols_head
        assert "verified_at" in cols_head
    finally:
        engine.dispose()

    command.downgrade(config, "0008")
    engine = create_engine(f"sqlite:///{db_file}")
    try:
        cols_down = {col["name"] for col in inspect(engine).get_columns("hospitals")}
        assert "verified_by_user_id" not in cols_down
        assert "verified_at" not in cols_down
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{db_file}")
    try:
        cols_reup = {col["name"] for col in inspect(engine).get_columns("hospitals")}
        assert "verified_by_user_id" in cols_reup
        assert "verified_at" in cols_reup
    finally:
        engine.dispose()
