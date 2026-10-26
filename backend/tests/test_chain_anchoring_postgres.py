"""Migration 0011 (``audit_batch_anchors``, ADR-035) on real PostgreSQL.

**Opt-in**, like ``test_alembic_postgres.py`` (whose fresh-database helpers this reuses):
skipped unless ``PULSEOS_TEST_POSTGRES_URL`` names a disposable server; every test migrates a
freshly created, uniquely named database and drops it afterwards.
"""

import asyncio

from alembic import command
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

from tests.test_alembic_postgres import (
    _alembic,
    _fresh_database,
    _tables,
    pytestmark,  # noqa: F401  (re-exported skip marker)
)

_BATCH = (
    "insert into audit_batches (id, batch_number, protocol_version, hash_version, leaf_count,"
    " root, commitment, first_occurred_at, last_occurred_at) values"
    " ('00000000-0000-0000-0000-000000000001', 1, 1, 3, 1, repeat('a', 64), repeat('b', 64),"
    " now(), now())"
)


def _anchor(status: str, tx: str, block: str, network: str = "polygon-amoy") -> str:
    return (
        "insert into audit_batch_anchors (id, batch_id, network, chain_id, contract_address,"
        " commitment, status, tx_hash, block_number) values (gen_random_uuid(),"
        f" '00000000-0000-0000-0000-000000000001', '{network}', 80002, '0x' || repeat('c', 40),"
        f" repeat('b', 64), '{status}', {tx}, {block})"
    )


async def _attempt(url: URL, *statements: str) -> str:
    """Run statements in one transaction; the SQLSTATE of the first failure, or 'ok'."""
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            for statement in statements:
                try:
                    await connection.execute(text(statement))
                except Exception as exc:
                    driver = getattr(getattr(exc, "orig", None), "__cause__", None)
                    return str(getattr(driver, "sqlstate", "error"))
        return "ok"
    finally:
        await engine.dispose()


TX = "'0x' || repeat('d', 64)"


def test_0011_constraints_are_enforced_and_downgrade_keeps_batches() -> None:
    with _fresh_database() as url:
        config = _alembic(url)
        command.upgrade(config, "head")

        assert asyncio.run(_attempt(url, _BATCH, _anchor("CONFIRMED", TX, "42"))) == "ok"
        # One row per (batch, network).
        assert asyncio.run(_attempt(url, _anchor("FAILED", "null", "null"))) == "23505"
        other = "ethereum-sepolia"
        # A confirmation needs a tx and a block; a pending submission needs a tx.
        assert asyncio.run(_attempt(url, _anchor("CONFIRMED", "null", "42", other))) == "23514"
        assert asyncio.run(_attempt(url, _anchor("CONFIRMED", TX, "null", other))) == "23514"
        assert asyncio.run(_attempt(url, _anchor("PENDING", "null", "null", other))) == "23514"
        assert asyncio.run(_attempt(url, _anchor("BOGUS", TX, "1", other))) == "23514"
        # A failure before any transaction existed is representable.
        assert asyncio.run(_attempt(url, _anchor("FAILED", "null", "null", other))) == "ok"
        # The batch must exist.
        orphan = _anchor("FAILED", "null", "null", "local-evm").replace(
            "00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000009"
        )
        assert asyncio.run(_attempt(url, orphan)) == "23503"

        command.downgrade(config, "0010")
        tables = asyncio.run(_tables(url))
        assert "audit_batch_anchors" not in tables
        assert {"audit_batches", "audit_batch_members", "audit_logs"} <= tables
        command.upgrade(config, "head")
        assert "audit_batch_anchors" in asyncio.run(_tables(url))
