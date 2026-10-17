"""Unit tests for the audit integrity verification CLI safety guard.

Tests safety rules, environment gates, secret redaction, and CLI behaviors
without connecting to any database.
"""

import asyncio
import json
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.audit_integrity as audit_integrity  # type: ignore[import-not-found] # noqa: E402
from scripts.audit_integrity import (  # noqa: E402
    DEV_DB_PORT,
    AuditSafetyError,
    database_host,
    database_port,
    ensure_sealing_safety,
    sanitize_database_url,
)


@dataclass
class FakeSettings:
    environment: str = "local"
    database_url: str = "postgresql+asyncpg://pulseos:pulseos@localhost:5433/pulseos"
    explicit_environment: bool = True
    audit_batch_max_size: int = 256
    audit_batch_interval_seconds: int = 300
    audit_batch_backlog_threshold_seconds: int = 900


# -----------------------------------------------------------------------------
# 1. URL Sanitization and Parsing
# -----------------------------------------------------------------------------


def test_sanitize_database_url_removes_credentials_and_query_parameters() -> None:
    raw = (
        "postgresql+asyncpg://admin_user:SUPER_SECRET_PASSWORD@localhost:5433/pulseos"
        "?sslmode=require&token=SECRET_TOKEN_XYZ"
    )
    sanitized = sanitize_database_url(raw)
    assert sanitized == "postgresql+asyncpg://localhost:5433/pulseos"
    assert "SUPER_SECRET_PASSWORD" not in sanitized
    assert "admin_user" not in sanitized
    assert "SECRET_TOKEN_XYZ" not in sanitized
    assert "sslmode" not in sanitized


def test_sanitize_database_url_preserves_ipv6_and_sqlite() -> None:
    ipv6 = "postgresql+asyncpg://u:p@[::1]:5432/pulseos"
    assert sanitize_database_url(ipv6) == "postgresql+asyncpg://[::1]:5432/pulseos"

    sqlite_path = "sqlite+aiosqlite:////tmp/test_audit.db"
    assert sanitize_database_url(sqlite_path) == "sqlite+aiosqlite:////tmp/test_audit.db"

    sqlite_mem = "sqlite+aiosqlite:///:memory:"
    assert sanitize_database_url(sqlite_mem) == "sqlite+aiosqlite:///:memory:"


def test_sanitize_database_url_handles_malformed_urls_gracefully() -> None:
    assert sanitize_database_url("not_a_valid_url") == "<invalid-database-url>"
    assert sanitize_database_url("") == "<invalid-database-url>"


def test_database_host_and_port_extraction() -> None:
    assert database_host("postgresql+asyncpg://u:p@localhost:5433/pulseos") == "localhost"
    assert database_port("postgresql+asyncpg://u:p@localhost:5433/pulseos") == 5433

    assert database_host("postgresql+asyncpg://u:p@[::1]:5432/pulseos") == "::1"
    assert database_port("postgresql+asyncpg://u:p@[::1]:5432/pulseos") == 5432

    assert database_host("sqlite+aiosqlite:////tmp/test.db") == ""
    assert database_port("sqlite+aiosqlite:////tmp/test.db") is None


# -----------------------------------------------------------------------------
# 2. Environment and Confirmation Guard
# -----------------------------------------------------------------------------


def test_missing_confirmation_raises_safety_error() -> None:
    settings = FakeSettings()
    with pytest.raises(AuditSafetyError) as exc_info:
        ensure_sealing_safety(settings, confirm_env=None)
    msg = str(exc_info.value)
    assert "Specify --confirm-env local to proceed" in msg
    assert "localhost:5433/pulseos" in msg


def test_empty_confirmation_raises_safety_error() -> None:
    settings = FakeSettings()
    with pytest.raises(AuditSafetyError) as exc_info:
        ensure_sealing_safety(settings, confirm_env="   ")
    assert "Specify --confirm-env local to proceed" in str(exc_info.value)


def test_matching_confirmation_passes() -> None:
    settings = FakeSettings(environment="local")
    ensure_sealing_safety(settings, confirm_env="local")


def test_matching_confirmation_case_insensitive_passes() -> None:
    settings = FakeSettings(environment="local")
    ensure_sealing_safety(settings, confirm_env="  LOCAL  ")


def test_mismatched_confirmation_raises_safety_error() -> None:
    settings = FakeSettings(environment="local")
    with pytest.raises(AuditSafetyError) as exc_info:
        ensure_sealing_safety(settings, confirm_env="production")
    msg = str(exc_info.value)
    expected = (
        "Confirmation mismatch: --confirm-env is 'production', "
        "but configured environment is 'local'"
    )
    assert expected in msg


# -----------------------------------------------------------------------------
# 3. Fail-Closed Environment Configuration
# -----------------------------------------------------------------------------


def test_missing_environment_raises_safety_error() -> None:
    settings = FakeSettings(environment="")
    with pytest.raises(AuditSafetyError) as exc_info:
        ensure_sealing_safety(settings, confirm_env="local")
    assert "PULSEOS_ENVIRONMENT is not set" in str(exc_info.value)


def test_unsupported_environment_raises_safety_error() -> None:
    settings = FakeSettings(environment="development_experimental")
    with pytest.raises(AuditSafetyError) as exc_info:
        ensure_sealing_safety(settings, confirm_env="development_experimental")
    assert "Unsupported environment 'development_experimental'" in str(exc_info.value)


def test_implicit_default_environment_fails_closed() -> None:
    settings = FakeSettings(environment="local", explicit_environment=False)
    with pytest.raises(AuditSafetyError) as exc_info:
        ensure_sealing_safety(settings, confirm_env="local")
    assert "came from default configuration rather than an explicit setting" in str(exc_info.value)


# -----------------------------------------------------------------------------
# 4. Target Host and Database Suitability
# -----------------------------------------------------------------------------


def test_remote_host_in_local_environment_is_rejected() -> None:
    settings = FakeSettings(
        environment="local",
        database_url="postgresql+asyncpg://u:p@db.production.example.com:5432/pulseos",
    )
    with pytest.raises(AuditSafetyError) as exc_info:
        ensure_sealing_safety(settings, confirm_env="local")
    assert "database host 'db.production.example.com' is not a local host" in str(exc_info.value)


def test_local_host_in_production_environment_is_rejected() -> None:
    settings = FakeSettings(
        environment="production",
        database_url="postgresql+asyncpg://u:p@localhost:5432/pulseos",
    )
    with pytest.raises(AuditSafetyError) as exc_info:
        ensure_sealing_safety(settings, confirm_env="production")
    assert "database target is a local or embedded host" in str(exc_info.value)


def test_dev_database_port_5433_rejected_in_non_local_environments() -> None:
    # Port 5433 is development compose stack; never allowed for staging or production
    prod_settings = FakeSettings(
        environment="production",
        database_url=f"postgresql+asyncpg://u:p@localhost:{DEV_DB_PORT}/pulseos",
    )
    with pytest.raises(AuditSafetyError) as exc_info:
        ensure_sealing_safety(prod_settings, confirm_env="production")
    assert f"target is the development database on port {DEV_DB_PORT}" in str(exc_info.value)

    # Also rejected in test environment
    test_settings = FakeSettings(
        environment="test",
        database_url=f"postgresql+asyncpg://u:p@localhost:{DEV_DB_PORT}/pulseos",
    )
    with pytest.raises(AuditSafetyError) as exc_info:
        ensure_sealing_safety(test_settings, confirm_env="test")
    assert f"port {DEV_DB_PORT}" in str(exc_info.value)


def test_malformed_and_unsupported_database_urls_rejected() -> None:
    with pytest.raises(AuditSafetyError, match="missing or empty"):
        ensure_sealing_safety(FakeSettings(database_url=""), confirm_env="local")

    with pytest.raises(AuditSafetyError, match="malformed"):
        ensure_sealing_safety(FakeSettings(database_url="not_a_valid_url"), confirm_env="local")

    with pytest.raises(AuditSafetyError, match="Unsupported database scheme 'mysql'"):
        ensure_sealing_safety(
            FakeSettings(database_url="mysql://u:p@localhost:3306/db"), confirm_env="local"
        )


def test_secret_redaction_in_safety_error_messages() -> None:
    secret_pass = "PULSEOS_SUPER_SECRET_12345"
    secret_token = "TOKEN_VALUE_SECRET_98765"
    settings = FakeSettings(
        database_url=f"postgresql+asyncpg://user:{secret_pass}@localhost:5433/pulseos?token={secret_token}",
    )
    with pytest.raises(AuditSafetyError) as exc_info:
        ensure_sealing_safety(settings, confirm_env=None)
    err_msg = str(exc_info.value)
    assert secret_pass not in err_msg
    assert secret_token not in err_msg
    assert "localhost:5433/pulseos" in err_msg


# -----------------------------------------------------------------------------
# 5. CLI Execution Order & Injection Behavior
# -----------------------------------------------------------------------------


def test_guard_fails_before_engine_or_session_creation() -> None:
    async def scenario() -> None:
        parser = audit_integrity.build_parser()
        args = parser.parse_args(["seal"])  # Missing --confirm-env

        settings = FakeSettings()
        with (
            patch("app.core.db.create_db_engine") as mock_engine,
            patch("app.core.db.create_session_factory") as mock_factory,
            pytest.raises(AuditSafetyError),
        ):
            await audit_integrity.run(args, settings=settings)

        mock_engine.assert_not_called()
        mock_factory.assert_not_called()

    asyncio.run(scenario())


def test_remote_target_in_local_mode_fails_before_engine_or_session_creation() -> None:
    async def scenario() -> None:
        parser = audit_integrity.build_parser()
        args = parser.parse_args(["seal", "--confirm-env", "local"])

        remote_settings = FakeSettings(
            environment="local",
            database_url="postgresql+asyncpg://pulseos:secret@remote.db.example.com:5432/pulseos",
        )
        with (
            patch("app.core.db.create_db_engine") as mock_engine,
            patch("app.core.db.create_session_factory") as mock_factory,
            pytest.raises(AuditSafetyError) as exc_info,
        ):
            await audit_integrity.run(args, settings=remote_settings)

        assert "is not a local host" in str(exc_info.value)
        mock_engine.assert_not_called()
        mock_factory.assert_not_called()

    asyncio.run(scenario())


def test_injected_session_factory_is_not_a_safety_bypass() -> None:
    async def scenario() -> None:
        parser = audit_integrity.build_parser()
        args = parser.parse_args(["seal"])  # Missing --confirm-env

        mock_factory = MagicMock()
        settings = FakeSettings()

        with pytest.raises(AuditSafetyError):
            await audit_integrity.run(args, session_factory=mock_factory, settings=settings)

        mock_factory.assert_not_called()

    asyncio.run(scenario())


def test_injected_session_factory_executes_when_guard_passes() -> None:
    async def scenario() -> None:
        parser = audit_integrity.build_parser()
        args = parser.parse_args(["seal", "--confirm-env", "local"])

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()

        @asynccontextmanager
        async def mock_factory() -> AsyncIterator[AsyncMock]:
            yield mock_session

        from app.modules.consent.batch_service import AuditBatchService

        mock_svc = MagicMock(spec=AuditBatchService)
        mock_svc.seal_all_batches = AsyncMock(return_value=[])

        settings = FakeSettings()
        with (
            patch(
                "app.modules.consent.dependencies.build_audit_batch_service",
                return_value=mock_svc,
            ),
        ):
            code = await audit_integrity.run(args, session_factory=mock_factory, settings=settings)
            assert code == 0
            mock_svc.seal_all_batches.assert_awaited_once_with(max_batches=None)

    asyncio.run(scenario())


def test_injected_service_workflow_preserves_behavior() -> None:
    async def scenario() -> None:
        from app.modules.consent.batch_service import AuditBatchService

        parser = audit_integrity.build_parser()
        args = parser.parse_args(["seal"])

        mock_svc = MagicMock(spec=AuditBatchService)
        mock_svc.seal_all_batches = AsyncMock(return_value=[])

        # Injected service bypasses DB connection entirely for unit testing formatters
        code = await audit_integrity.run(args, service=mock_svc)
        assert code == 0
        mock_svc.seal_all_batches.assert_awaited_once_with(max_batches=None)

    asyncio.run(scenario())


def test_genuine_read_only_commands_require_no_confirmation() -> None:
    parser = audit_integrity.build_parser()

    # None of the read-only commands have or require --confirm-env
    vb_args = parser.parse_args(["verify-batch", "--batch-number", "1"])
    assert not hasattr(vb_args, "confirm_env") or vb_args.confirm_env is None

    ve_args = parser.parse_args(["verify-event", "--event-id", str(uuid4())])
    assert not hasattr(ve_args, "confirm_env") or ve_args.confirm_env is None

    rec_args = parser.parse_args(["reconcile"])
    assert not hasattr(rec_args, "confirm_env") or rec_args.confirm_env is None


# -----------------------------------------------------------------------------
# 6. CLI Main Exit Status & Error Formatting
# -----------------------------------------------------------------------------


def test_cli_main_exit_status_2_on_default_environment(
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = FakeSettings(environment="local", explicit_environment=False)
    with patch("app.core.config.get_settings", return_value=settings):
        code = audit_integrity.main(["seal"])
        assert code == 2
        captured = capsys.readouterr()
        assert "Safety Error:" in captured.err
        assert "default configuration rather than an explicit setting" in captured.err


def test_cli_main_exit_status_2_on_missing_confirmation(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PULSEOS_ENVIRONMENT", "local")
    code = audit_integrity.main(["seal"])
    assert code == 2
    captured = capsys.readouterr()
    assert "Safety Error:" in captured.err
    assert "--confirm-env" in captured.err


def test_cli_main_json_output_on_safety_failure(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PULSEOS_ENVIRONMENT", "local")
    code = audit_integrity.main(["--json", "seal"])
    assert code == 2
    captured = capsys.readouterr()
    payload = json.loads(captured.err)
    assert payload["status"] == "SAFETY_ERROR"
    assert "--confirm-env" in payload["error"]
