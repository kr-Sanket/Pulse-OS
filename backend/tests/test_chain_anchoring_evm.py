"""ADR-035 end to end against a real EVM node (opt-in).

Skipped unless ``PULSEOS_TEST_EVM_RPC_URL`` names a **local development chain** (chain id
31337, e.g. ``anvil``) and ``PULSEOS_TEST_EVM_PRIVATE_KEY`` a funded key on it, and the
contract has been built (``forge build`` in contracts/). The test deploys a fresh
``AuditCommitmentRegistry``, seals a batch in an in-memory SQLite database, submits its
commitment through the real JSON-RPC adapter, confirms it from the mined receipt and
re-reads it from contract state. This is a real EVM, not a public testnet: it proves the
code path, not public anchoring.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from app.modules.consent.chain import (
    ChainRpcError,
    JsonRpcCommitmentRegistry,
)
from app.modules.consent.chain_anchor_service import (
    ChainVerificationStatus,
    SubmissionAction,
)
from app.modules.consent.models import ChainAnchorStatus

from tests.support import sqlite_session
from tests.test_chain_anchoring import Harness

RPC_URL = os.environ.get("PULSEOS_TEST_EVM_RPC_URL", "")
PRIVATE_KEY = os.environ.get("PULSEOS_TEST_EVM_PRIVATE_KEY", "")
ARTIFACT = (
    Path(__file__).resolve().parents[2]
    / "contracts/out/AuditCommitmentRegistry.sol/AuditCommitmentRegistry.json"
)

pytestmark = pytest.mark.skipif(
    not (RPC_URL and PRIVATE_KEY and ARTIFACT.exists()),
    reason="EVM tests are opt-in: set PULSEOS_TEST_EVM_RPC_URL/_PRIVATE_KEY and forge build",
)


def _rpc(method: str, params: list[Any]) -> Any:
    body = httpx.post(
        RPC_URL, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    ).json()
    assert "error" not in body, body.get("error")
    return body["result"]


def _deploy(anchorer: str) -> str:
    from eth_account import Account

    assert int(_rpc("eth_chainId", []), 16) == 31337, "only a local dev chain is allowed"
    account = Account.from_key(PRIVATE_KEY)
    bytecode = json.loads(ARTIFACT.read_text())["bytecode"]["object"]
    data = bytecode + anchorer.lower().removeprefix("0x").rjust(64, "0")
    tx = {
        "type": 2,
        "chainId": 31337,
        "nonce": int(_rpc("eth_getTransactionCount", [account.address, "pending"]), 16),
        "data": data,
        "value": 0,
        "gas": 1_000_000,
        "maxPriorityFeePerGas": 1_000_000_000,
        "maxFeePerGas": 100_000_000_000,
    }
    raw = "0x" + bytes(account.sign_transaction(tx).raw_transaction).hex()
    tx_hash = _rpc("eth_sendRawTransaction", [raw])
    receipt = None
    for _ in range(50):
        receipt = _rpc("eth_getTransactionReceipt", [tx_hash])
        if receipt is not None:
            break
        time.sleep(0.1)
    assert receipt is not None and int(receipt["status"], 16) == 1
    return str(receipt["contractAddress"])


def test_submit_confirm_and_verify_on_a_real_evm() -> None:
    from eth_account import Account

    signer = Account.from_key(PRIVATE_KEY)
    contract = _deploy(signer.address)

    async def scenario() -> None:
        registry = JsonRpcCommitmentRegistry(
            rpc_url=RPC_URL, chain_id=31337, contract_address=contract, signer=signer
        )
        async with sqlite_session() as session:
            h = Harness(session, None)
            h.service._registry = registry
            h.service._min_confirmations = 1
            batch = await h.seal(events=4)

            assert (await h.service.status(1)).chain.status is ChainVerificationStatus.NOT_ON_CHAIN

            submitted = await h.service.submit(1)
            assert submitted.action is SubmissionAction.SUBMITTED
            confirmed = await h.service.refresh(1)
            for _ in range(50):  # anvil automines; the receipt appears within moments
                if confirmed.action is not SubmissionAction.STILL_PENDING:
                    break
                await asyncio.sleep(0.1)
                confirmed = await h.service.refresh(1)
            assert confirmed.action is SubmissionAction.CONFIRMED, confirmed
            anchor = confirmed.anchor
            assert anchor is not None and anchor.status is ChainAnchorStatus.CONFIRMED
            assert anchor.block_number == await registry.anchored_block(batch.commitment)

            view = await h.service.status(1)
            assert view.chain.status is ChainVerificationStatus.VERIFIED
            assert view.chain.expected_commitment == batch.commitment

            # Idempotent: no second transaction.
            assert (await h.service.submit(1)).action is SubmissionAction.ALREADY_CONFIRMED

            # The contract itself refuses a duplicate (estimation reverts; nothing is sent).
            with pytest.raises(ChainRpcError):
                await registry.submit(batch.commitment)

            # An unauthorized sender is refused by the contract.
            stranger = Account.create()
            other = JsonRpcCommitmentRegistry(
                rpc_url=RPC_URL, chain_id=31337, contract_address=contract, signer=stranger
            )
            with pytest.raises(ChainRpcError):
                await other.submit("ab" * 32)
            assert await registry.anchored_block("ab" * 32) == 0

            # Tampering locally after anchoring is detected, not papered over.
            batch.root = "0" * 64
            await session.flush()
            tampered = await h.service.status(1)
            assert tampered.chain.status is ChainVerificationStatus.LOCAL_INTEGRITY_FAILED

    asyncio.run(scenario())
