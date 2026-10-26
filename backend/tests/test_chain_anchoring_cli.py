"""``scripts/audit_integrity.py`` anchor / anchor-refresh / verify-chain (ADR-035).

Runs the real CLI dispatch over an in-memory SQLite session and the in-memory ``FakeChain``;
no network, no development database.
"""

import asyncio
import json
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest
from app.core.db import Base
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.support import create_sqlite_test_engine, sqlite_session
from tests.test_chain_anchoring import FakeChain, Harness

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.audit_integrity as audit_integrity  # type: ignore[import-not-found] # noqa: E402


@dataclass
class ChainSettings:
    environment: str = "test"
    database_url: str = "sqlite+aiosqlite:///:memory:"
    explicit_environment: bool = True
    audit_batch_max_size: int = 256
    audit_batch_interval_seconds: int = 300
    audit_batch_backlog_threshold_seconds: int = 900
    chain_min_confirmations: int = 1


async def _cli(
    target: AsyncSession | AsyncEngine,
    chain: FakeChain | None,
    argv: list[str],
    settings: object,
) -> int:
    """Run the CLI; with an engine, each run gets its own session (the CLI commits)."""

    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        if isinstance(target, AsyncSession):
            yield target
            return
        async with async_sessionmaker(target, expire_on_commit=False)() as session:
            yield session

    args = audit_integrity.build_parser().parse_args(argv)
    with patch("app.modules.consent.dependencies.build_commitment_registry", return_value=chain):
        code: int = await audit_integrity.run(args, session_factory=factory, settings=settings)
    return code


def test_anchor_refresh_and_verify_chain_round_trip(capsys: pytest.CaptureFixture[str]) -> None:
    async def scenario() -> None:
        engine = create_sqlite_test_engine()
        try:
            await _round_trip(engine, capsys)
        finally:
            await engine.dispose()

    asyncio.run(scenario())


async def _round_trip(engine: AsyncEngine, capsys: pytest.CaptureFixture[str]) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    chain = FakeChain()
    async with async_sessionmaker(engine, expire_on_commit=False)() as seed:
        batch = await Harness(seed, chain).seal()
        await seed.commit()
    settings = ChainSettings()
    confirm = ["--confirm-env", "test"]

    anchor = ["--json", "anchor", "--batch-number", "1", *confirm]
    assert await _cli(engine, chain, anchor, settings) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["action"] == "SUBMITTED"
    assert out["anchor"]["status"] == "PENDING"
    assert out["anchor"]["commitment"] == batch.commitment

    chain.mine()
    refresh = ["--json", "anchor-refresh", "--batch-number", "1", *confirm]
    assert await _cli(engine, chain, refresh, settings) == 0
    assert json.loads(capsys.readouterr().out)["action"] == "CONFIRMED"

    verify = ["--json", "verify-chain", "--batch-number", "1"]
    assert await _cli(engine, chain, verify, settings) == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified["chain_verification"] == "VERIFIED"
    assert verified["submission_status"] == "CONFIRMED"
    assert verified["expected_commitment"] == batch.commitment

    chain.recorded.clear()
    assert await _cli(engine, chain, verify, settings) == 1
    assert json.loads(capsys.readouterr().out)["chain_verification"] == "MISMATCH"


def test_anchor_is_guarded_like_seal() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            chain = FakeChain()
            await Harness(session, chain).seal()
            with pytest.raises(audit_integrity.AuditSafetyError):
                await _cli(session, chain, ["anchor", "--batch-number", "1"], ChainSettings())
            with pytest.raises(audit_integrity.AuditSafetyError):
                await _cli(
                    session,
                    chain,
                    ["anchor-refresh", "--batch-number", "1", "--confirm-env", "production"],
                    ChainSettings(),
                )
            assert chain.broadcasts == []

    asyncio.run(scenario())


def test_chain_commands_refuse_when_unconfigured() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            with pytest.raises(audit_integrity.AuditSafetyError, match="not configured"):
                await _cli(session, None, ["verify-chain", "--batch-number", "1"], ChainSettings())

    asyncio.run(scenario())
