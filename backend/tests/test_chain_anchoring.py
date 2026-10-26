"""Public-chain anchoring of batch commitments (ADR-035): adapter, service and API.

Every test here is deterministic and network-free. The JSON-RPC adapter is exercised over
``httpx.MockTransport`` (exact calldata, signing, error mapping); the service over an
in-memory ``FakeChain`` that models pending → mined → confirmed. A real EVM run is the
opt-in ``test_chain_anchoring_evm.py``; a public testnet run is a manual demonstration.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from app.core.db import create_session_factory
from app.modules.auth.domain import Role
from app.modules.auth.fake import FakeAuthProvider
from app.modules.auth.models import User
from app.modules.consent.batch_service import AuditBatchService
from app.modules.consent.chain import (
    ANCHOR_SELECTOR,
    ANCHORED_BLOCK_SELECTOR,
    COMMITMENT_ANCHORED_TOPIC,
    ChainConfigError,
    ChainError,
    ChainRpcError,
    ChainUnavailableError,
    JsonRpcCommitmentRegistry,
    LogEntry,
    TxReceipt,
)
from app.modules.consent.chain_anchor_service import (
    BatchAnchorService,
    ChainVerificationStatus,
    LocalBatchInvalidError,
    SubmissionAction,
)
from app.modules.consent.dependencies import build_commitment_registry, get_commitment_registry
from app.modules.consent.errors import AuditBatchNotFoundError
from app.modules.consent.merkle import _keccak256
from app.modules.consent.models import (
    AuditAction,
    AuditBatch,
    AuditBatchAnchor,
    AuditLog,
    ChainAnchorStatus,
)
from app.modules.consent.repository import AuditBatchAnchorRepository, AuditBatchRepository
from app.modules.consent.service import HASH_SCHEME_V3, recompute_event_hash
from app.modules.patients.models import Patient
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.support import sqlite_session

NOW = dt.datetime(2026, 10, 26, 12, 0, tzinfo=dt.UTC)
CONTRACT = "0x5FbDB2315678afecb367f032d93F642f64180aa3"
# Synthetic signing key for tests only — never funded, never used on any network.
TEST_KEY = "0x" + "11" * 32
RPC_URL = "https://rpc.example.invalid/v1/SECRET-PROVIDER-KEY"


def _run(scenario: Callable[[], Coroutine[Any, Any, None]]) -> None:
    asyncio.run(scenario())


def _selector(signature: str) -> str:
    return "0x" + _keccak256(signature.encode()).hex()[:8]


# -- ABI pins ------------------------------------------------------------------------------


def test_abi_constants_match_contract_signatures() -> None:
    assert _selector("anchor(bytes32)") == ANCHOR_SELECTOR
    assert _selector("anchoredBlock(bytes32)") == ANCHORED_BLOCK_SELECTOR
    assert "0x" + _keccak256(b"CommitmentAnchored(bytes32)").hex() == COMMITMENT_ANCHORED_TOPIC


# -- JSON-RPC adapter --------------------------------------------------------------------


@dataclass
class RpcStub:
    """Answers JSON-RPC calls from a method → result (or callable) table and records them."""

    results: dict[str, Any]
    calls: list[dict[str, Any]] = field(default_factory=list)

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            self.calls.append(body)
            result = self.results[body["method"]]
            if isinstance(result, Exception):
                raise result
            if callable(result):
                result = result(body["params"])
            if isinstance(result, dict) and "__error__" in result:
                return httpx.Response(
                    200,
                    json={"jsonrpc": "2.0", "id": body["id"], "error": result["__error__"]},
                )
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

        return httpx.MockTransport(handler)


def _registry(
    stub: RpcStub,
    *,
    chain_id: int = 80002,
    signer: Any = None,
    min_priority_fee_per_gas: int = 0,
) -> Any:
    return JsonRpcCommitmentRegistry(
        rpc_url=RPC_URL,
        chain_id=chain_id,
        contract_address=CONTRACT,
        signer=signer,
        min_priority_fee_per_gas=min_priority_fee_per_gas,
        transport=stub.transport(),
    )


COMMITMENT = "7d2d9dd7205f9adb892bd361857652127df7e954f3132228e7724aeb53476c36"


def test_anchored_block_encodes_exact_calldata() -> None:
    stub = RpcStub({"eth_call": "0x" + format(1234, "064x")})
    block = asyncio.run(_registry(stub).anchored_block(COMMITMENT))
    assert block == 1234
    call = stub.calls[0]
    assert call["method"] == "eth_call"
    assert call["params"] == [
        {"to": CONTRACT, "data": ANCHORED_BLOCK_SELECTOR + COMMITMENT},
        "latest",
    ]


def test_anchored_block_zero_and_empty_result_mean_unrecorded() -> None:
    assert (
        asyncio.run(_registry(RpcStub({"eth_call": "0x" + "0" * 64})).anchored_block(COMMITMENT))
        == 0
    )
    assert asyncio.run(_registry(RpcStub({"eth_call": "0x"})).anchored_block(COMMITMENT)) == 0


@pytest.mark.parametrize(
    "bad", ["", "0x" + COMMITMENT, COMMITMENT.upper(), "Patient Name", COMMITMENT[:-1]]
)
def test_port_refuses_anything_but_a_bare_commitment(bad: str) -> None:
    stub = RpcStub({"eth_call": "0x"})
    with pytest.raises(ValueError):
        asyncio.run(_registry(stub).anchored_block(bad))
    assert stub.calls == []


@pytest.mark.parametrize("chain_id", [1, 137, 10, 8453, 56])
def test_mainnet_chain_ids_are_refused(chain_id: int) -> None:
    with pytest.raises(ChainConfigError) as error:
        _registry(RpcStub({}), chain_id=chain_id)
    assert error.value.code == "chain_id_not_allowed"


def test_malformed_contract_address_is_refused() -> None:
    with pytest.raises(ChainConfigError):
        JsonRpcCommitmentRegistry(rpc_url=RPC_URL, chain_id=80002, contract_address="0x1234")


def test_transport_failure_maps_to_unavailable_without_leaking_url() -> None:
    stub = RpcStub({"eth_call": httpx.ConnectError(f"cannot reach {RPC_URL}")})
    with pytest.raises(ChainUnavailableError) as error:
        asyncio.run(_registry(stub).anchored_block(COMMITMENT))
    assert error.value.code == "rpc_unavailable"
    assert "SECRET" not in str(error.value)
    assert error.value.__cause__ is None


def test_jsonrpc_error_maps_to_rpc_error_without_echoing_body() -> None:
    stub = RpcStub(
        {"eth_call": {"__error__": {"code": -32000, "message": "execution reverted secret"}}}
    )
    with pytest.raises(ChainRpcError) as error:
        asyncio.run(_registry(stub).anchored_block(COMMITMENT))
    assert str(error.value) == "rpc_error"


def test_submit_without_signer_is_a_config_error_and_sends_nothing() -> None:
    stub = RpcStub({})
    with pytest.raises(ChainConfigError) as error:
        asyncio.run(_registry(stub).submit(COMMITMENT))
    assert error.value.code == "signer_not_configured"
    assert stub.calls == []


def test_submit_signs_eip1559_anchor_call_for_configured_chain() -> None:
    from eth_account import Account
    from eth_account.typed_transactions.typed_transaction import TypedTransaction
    from hexbytes import HexBytes

    signer = Account.from_key(TEST_KEY)
    signer_address = signer.address
    sent: list[str] = []

    def send(params: list[str]) -> str:
        sent.append(params[0])
        return "0x" + "ab" * 32

    stub = RpcStub(
        {
            "eth_estimateGas": "0xb000",
            "eth_getTransactionCount": "0x7",
            "eth_getBlockByNumber": {"baseFeePerGas": "0x3b9aca00", "timestamp": "0x1"},
            "eth_maxPriorityFeePerGas": "0x6fc23ac00",
            "eth_sendRawTransaction": send,
        }
    )
    tx_hash = asyncio.run(_registry(stub, signer=signer).submit(COMMITMENT))
    assert tx_hash == "0x" + "ab" * 32

    estimate = next(c for c in stub.calls if c["method"] == "eth_estimateGas")
    assert estimate["params"][0] == {
        "from": signer_address,
        "to": CONTRACT,
        "data": ANCHOR_SELECTOR + COMMITMENT,
    }
    raw = bytes.fromhex(sent[0][2:])
    assert raw[0] == 2  # EIP-1559 typed transaction
    decoded = TypedTransaction.from_bytes(HexBytes(raw)).as_dict()
    assert decoded["chainId"] == 80002
    assert decoded["nonce"] == 7
    assert decoded["value"] == 0
    assert decoded["data"].hex().removeprefix("0x") == (ANCHOR_SELECTOR + COMMITMENT)[2:]
    assert Account.recover_transaction(raw) == signer_address


def test_submit_enforces_configured_min_priority_fee_floor() -> None:
    from eth_account import Account
    from eth_account.typed_transactions.typed_transaction import TypedTransaction
    from hexbytes import HexBytes

    signer = Account.from_key(TEST_KEY)
    sent: list[str] = []

    def send(params: list[str]) -> str:
        sent.append(params[0])
        return "0x" + "ab" * 32

    # Node returns 1 Gwei (0x3b9aca00), but floor is 30 Gwei (30_000_000_000)
    stub = RpcStub(
        {
            "eth_estimateGas": "0xb000",
            "eth_getTransactionCount": "0x7",
            "eth_getBlockByNumber": {"baseFeePerGas": "0x3b9aca00", "timestamp": "0x1"},
            "eth_maxPriorityFeePerGas": "0x3b9aca00",  # 1 Gwei
            "eth_sendRawTransaction": send,
        }
    )
    floor = 30_000_000_000
    registry = _registry(stub, signer=signer, min_priority_fee_per_gas=floor)
    tx_hash = asyncio.run(registry.submit(COMMITMENT))
    assert tx_hash == "0x" + "ab" * 32

    raw = bytes.fromhex(sent[0][2:])
    decoded = TypedTransaction.from_bytes(HexBytes(raw)).as_dict()
    assert decoded["maxPriorityFeePerGas"] == floor
    # maxFeePerGas = 2 * baseFee + maxPriorityFee = 2 * 1 Gwei + 30 Gwei = 32 Gwei
    assert decoded["maxFeePerGas"] == 2 * 1_000_000_000 + floor


def test_submit_handles_rpc_error_on_priority_fee_with_floor() -> None:
    from eth_account import Account
    from eth_account.typed_transactions.typed_transaction import TypedTransaction
    from hexbytes import HexBytes

    signer = Account.from_key(TEST_KEY)
    sent: list[str] = []

    def send(params: list[str]) -> str:
        sent.append(params[0])
        return "0x" + "ab" * 32

    def raise_rpc_error(params: list[Any]) -> Any:
        raise ChainRpcError("rpc_error")

    # Node errors on eth_maxPriorityFeePerGas, but floor is configured
    stub = RpcStub(
        {
            "eth_estimateGas": "0xb000",
            "eth_getTransactionCount": "0x7",
            "eth_getBlockByNumber": {"baseFeePerGas": "0x3b9aca00", "timestamp": "0x1"},
            "eth_maxPriorityFeePerGas": raise_rpc_error,
            "eth_sendRawTransaction": send,
        }
    )
    floor = 25_000_000_000
    registry = _registry(stub, signer=signer, min_priority_fee_per_gas=floor)
    tx_hash = asyncio.run(registry.submit(COMMITMENT))
    assert tx_hash == "0x" + "ab" * 32

    raw = bytes.fromhex(sent[0][2:])
    decoded = TypedTransaction.from_bytes(HexBytes(raw)).as_dict()
    assert decoded["maxPriorityFeePerGas"] == floor


def test_submit_raises_rpc_error_on_priority_fee_when_no_floor() -> None:
    from eth_account import Account

    signer = Account.from_key(TEST_KEY)

    def raise_rpc_error(params: list[Any]) -> Any:
        raise ChainRpcError("rpc_error")

    stub = RpcStub(
        {
            "eth_estimateGas": "0xb000",
            "eth_getTransactionCount": "0x7",
            "eth_getBlockByNumber": {"baseFeePerGas": "0x3b9aca00", "timestamp": "0x1"},
            "eth_maxPriorityFeePerGas": raise_rpc_error,
        }
    )
    registry = _registry(stub, signer=signer, min_priority_fee_per_gas=0)
    with pytest.raises(ChainRpcError) as exc:
        asyncio.run(registry.submit(COMMITMENT))
    assert exc.value.code == "rpc_error"


def test_submit_rejects_negative_min_priority_fee() -> None:
    stub = RpcStub({})
    with pytest.raises(ChainConfigError) as exc:
        _registry(stub, min_priority_fee_per_gas=-1)
    assert exc.value.code == "invalid_min_priority_fee"


def test_settings_validates_min_priority_fee() -> None:
    from app.core.config import Settings
    from pydantic import ValidationError

    s = Settings(chain_min_priority_fee_per_gas=30_000_000_000)
    assert s.chain_min_priority_fee_per_gas == 30_000_000_000

    with pytest.raises(ValidationError):
        Settings(chain_min_priority_fee_per_gas=-5)


def test_receipt_and_log_matching() -> None:
    good = LogEntry(address=CONTRACT.lower(), topics=(COMMITMENT_ANCHORED_TOPIC, "0x" + COMMITMENT))
    receipt = TxReceipt(tx_hash="0x" + "1" * 64, succeeded=True, block_number=5, logs=(good,))
    assert receipt.records_commitment(contract_address=CONTRACT, commitment=COMMITMENT)
    other = "dcf485fefd095822e3191e95048dfe944a8dcdc7e0412397a9fb1c53af8caa4c"
    assert not receipt.records_commitment(contract_address=CONTRACT, commitment=other)
    foreign = LogEntry(address="0x" + "9" * 40, topics=good.topics)
    receipt2 = TxReceipt(tx_hash="0x" + "1" * 64, succeeded=True, block_number=5, logs=(foreign,))
    assert not receipt2.records_commitment(contract_address=CONTRACT, commitment=COMMITMENT)


def test_build_registry_requires_complete_config_and_hides_key_errors() -> None:
    from app.core.config import Settings
    from pydantic import SecretStr

    assert build_commitment_registry(Settings(chain_rpc_url=None)) is None
    complete = Settings(
        chain_rpc_url=SecretStr(RPC_URL), chain_id=80002, chain_contract_address=CONTRACT
    )
    assert build_commitment_registry(complete) is not None
    with pytest.raises(ChainConfigError) as missing:
        build_commitment_registry(complete, with_signer=True)
    assert missing.value.code == "signer_not_configured"
    bad_key = complete.model_copy(update={"chain_anchorer_private_key": SecretStr("0xnot-a-key")})
    with pytest.raises(ChainConfigError) as invalid:
        build_commitment_registry(bad_key, with_signer=True)
    assert invalid.value.code == "invalid_private_key"
    assert invalid.value.__cause__ is None
    assert "not-a-key" not in str(invalid.value)


# -- In-memory chain for service tests ---------------------------------------------------


class FakeChain:
    """A registry contract on a toy chain: pending txs, mining, confirmations, faults."""

    def __init__(self, *, chain_id: int = 80002, contract: str = CONTRACT) -> None:
        self.network = "polygon-amoy"
        self.chain_id = chain_id
        self.contract_address = contract
        self.reported_chain_id = chain_id
        self.head = 100
        self.recorded: dict[str, int] = {}
        self.pending: dict[str, str] = {}
        self.receipts: dict[str, TxReceipt] = {}
        self.broadcasts: list[str] = []
        self.fail_with: ChainError | None = None
        self.revert_next = False
        self.omit_event_next = False

    def _check(self) -> None:
        if self.fail_with is not None:
            raise self.fail_with

    async def remote_chain_id(self) -> int:
        self._check()
        return self.reported_chain_id

    async def anchored_block(self, commitment: str) -> int:
        self._check()
        return self.recorded.get(commitment, 0)

    async def submit(self, commitment: str) -> str:
        self._check()
        tx = "0x" + _keccak256(f"{commitment}:{len(self.broadcasts)}".encode()).hex()
        self.broadcasts.append(tx)
        self.pending[tx] = commitment
        return tx

    async def get_receipt(self, tx_hash: str) -> TxReceipt | None:
        self._check()
        return self.receipts.get(tx_hash)

    async def head_block(self) -> int:
        self._check()
        return self.head

    async def block_timestamp(self, block_number: int) -> dt.datetime:
        self._check()
        return NOW + dt.timedelta(seconds=block_number)

    async def find_anchor_tx(self, commitment: str, block_number: int) -> str | None:
        self._check()
        for receipt in self.receipts.values():
            if receipt.block_number == block_number and receipt.records_commitment(
                contract_address=self.contract_address, commitment=commitment
            ):
                return receipt.tx_hash
        return None

    def mine(self) -> None:
        """Include every pending tx in the next block."""
        self.head += 1
        for tx, commitment in list(self.pending.items()):
            reverted = self.revert_next or commitment in self.recorded
            logs: tuple[LogEntry, ...] = ()
            if not reverted:
                if not self.omit_event_next:
                    logs = (
                        LogEntry(
                            address=self.contract_address,
                            topics=(COMMITMENT_ANCHORED_TOPIC, "0x" + commitment),
                        ),
                    )
                self.recorded[commitment] = self.head
            self.receipts[tx] = TxReceipt(
                tx_hash=tx, succeeded=not reverted, block_number=self.head, logs=logs
            )
            del self.pending[tx]
        self.revert_next = False
        self.omit_event_next = False


class Harness:
    def __init__(self, session: AsyncSession, chain: FakeChain | None) -> None:
        self.session = session
        self.chain = chain
        repo = AuditBatchRepository(session)
        self.batch_service = AuditBatchService(
            batches=repo,
            max_size=10,
            backlog_threshold=dt.timedelta(seconds=900),
            clock=lambda: NOW,
        )
        self.service = BatchAnchorService(
            batches=repo,
            anchors=AuditBatchAnchorRepository(session),
            batch_service=self.batch_service,
            registry=chain,
            min_confirmations=2,
            clock=lambda: NOW,
        )

    async def seal(self, events: int = 3) -> AuditBatch:
        user = User(id=uuid4(), firebase_uid=f"fb-{uuid4()}", role=Role.PATIENT)
        self.session.add(user)
        await self.session.flush()
        patient = Patient(
            id=uuid4(),
            user_id=user.id,
            health_id=f"PHI-IND-2026-{uuid4().hex[:7].upper()}",
            full_name="Synthetic Patient",
        )
        self.session.add(patient)
        await self.session.flush()
        for i in range(events):
            event = AuditLog(
                id=uuid4(),
                actor_user_id=user.id,
                actor_role=Role.PATIENT,
                action=AuditAction.RECORD_VIEWED,
                patient_id=patient.id,
                request_context=None,
                occurred_at=NOW - dt.timedelta(hours=1, seconds=-i),
                actor_hospital_id=None,
                hash_version=HASH_SCHEME_V3,
                event_hash="",
            )
            event.event_hash = recompute_event_hash(event)
            self.session.add(event)
        await self.session.flush()
        sealed = await self.batch_service.seal_all_batches()
        assert len(sealed) == 1
        return sealed[0]

    async def rows(self) -> list[AuditBatchAnchor]:
        return list((await self.session.execute(select(AuditBatchAnchor))).scalars())


def test_full_lifecycle_submit_pending_confirm_verify() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            chain = FakeChain()
            h = Harness(session, chain)
            batch = await h.seal()

            before = await h.service.status(1)
            assert before.anchor is None
            assert before.chain.status is ChainVerificationStatus.NOT_ON_CHAIN
            assert before.chain.expected_commitment == batch.commitment

            out = await h.service.submit(1)
            assert out.action is SubmissionAction.SUBMITTED
            assert out.anchor is not None and out.anchor.status is ChainAnchorStatus.PENDING
            assert out.anchor.commitment == batch.commitment
            assert out.anchor.tx_hash == chain.broadcasts[0]
            assert chain.pending == {chain.broadcasts[0]: batch.commitment}

            assert (await h.service.refresh(1)).action is SubmissionAction.STILL_PENDING
            chain.mine()  # 1 confirmation < 2
            assert (await h.service.refresh(1)).action is SubmissionAction.STILL_PENDING
            mined_block = chain.head
            chain.head += 1
            done = await h.service.refresh(1)
            assert done.action is SubmissionAction.CONFIRMED
            assert done.anchor is not None
            assert done.anchor.block_number == mined_block
            assert done.anchor.block_timestamp is not None

            view = await h.service.status(1)
            assert view.chain.status is ChainVerificationStatus.VERIFIED
            assert view.chain.on_chain_block_number == mined_block
            assert view.network == "polygon-amoy" and view.contract_address == CONTRACT

    _run(scenario)


def test_resubmitting_confirmed_or_pending_never_broadcasts_again() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            chain = FakeChain()
            h = Harness(session, chain)
            await h.seal()
            await h.service.submit(1)
            again = await h.service.submit(1)  # pending: refresh, no broadcast
            assert again.action is SubmissionAction.STILL_PENDING
            assert len(chain.broadcasts) == 1
            chain.mine()
            chain.head += 1
            await h.service.refresh(1)
            assert (await h.service.submit(1)).action is SubmissionAction.ALREADY_CONFIRMED
            assert len(chain.broadcasts) == 1
            assert len(await h.rows()) == 1

    _run(scenario)


def test_rpc_unavailable_records_failure_then_retry_succeeds() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            chain = FakeChain()
            h = Harness(session, chain)
            await h.seal()
            original_submit = chain.submit

            async def broken_submit(commitment: str) -> str:
                raise ChainUnavailableError("rpc_unavailable")

            chain.submit = broken_submit  # type: ignore[method-assign]
            out = await h.service.submit(1)
            assert out.action is SubmissionAction.FAILED
            assert out.anchor is not None
            assert out.anchor.status is ChainAnchorStatus.FAILED
            assert out.anchor.failure_reason == "rpc_unavailable"
            assert out.anchor.tx_hash is None
            assert (await h.service.status(1)).chain.status is ChainVerificationStatus.NOT_ON_CHAIN

            chain.submit = original_submit  # type: ignore[method-assign]
            retry = await h.service.submit(1)
            assert retry.action is SubmissionAction.SUBMITTED
            assert len(await h.rows()) == 1  # same row, retried

    _run(scenario)


def test_retry_adopts_commitment_already_on_chain_without_sending() -> None:
    """A tx that landed although the DB never recorded it (crash after broadcast)."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            chain = FakeChain()
            h = Harness(session, chain)
            batch = await h.seal()
            await chain.submit(batch.commitment)  # broadcast outside the service
            chain.mine()
            out = await h.service.submit(1)
            assert out.action is SubmissionAction.ADOPTED_EXISTING
            assert out.anchor is not None and out.anchor.status is ChainAnchorStatus.CONFIRMED
            assert out.anchor.tx_hash == chain.broadcasts[0]
            assert len(chain.broadcasts) == 1
            assert (await h.service.status(1)).chain.status is ChainVerificationStatus.VERIFIED

    _run(scenario)


def test_reverted_and_eventless_receipts_fail() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            chain = FakeChain()
            h = Harness(session, chain)
            await h.seal()
            await h.service.submit(1)
            chain.revert_next = True
            chain.mine()
            chain.head += 1
            out = await h.service.refresh(1)
            assert out.action is SubmissionAction.FAILED
            assert out.anchor is not None and out.anchor.failure_reason == "transaction_reverted"

            await h.service.submit(1)  # retry
            chain.omit_event_next = True
            chain.mine()
            chain.head += 1
            out = await h.service.refresh(1)
            assert out.action is SubmissionAction.FAILED
            assert out.anchor is not None
            assert out.anchor.failure_reason == "commitment_event_missing"

    _run(scenario)


def test_tampered_batch_is_never_submitted() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            chain = FakeChain()
            h = Harness(session, chain)
            batch = await h.seal()
            batch.root = "0" * 64
            await session.flush()
            with pytest.raises(LocalBatchInvalidError):
                await h.service.submit(1)
            assert chain.broadcasts == []
            assert await h.rows() == []
            view = await h.service.status(1)
            assert view.chain.status is ChainVerificationStatus.LOCAL_INTEGRITY_FAILED

    _run(scenario)


def test_wrong_chain_refuses_before_writing() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            chain = FakeChain()
            chain.reported_chain_id = 1
            h = Harness(session, chain)
            await h.seal()
            with pytest.raises(ChainConfigError):
                await h.service.submit(1)
            assert chain.broadcasts == [] and await h.rows() == []

    _run(scenario)


def test_missing_batch_and_unconfigured_registry() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = Harness(session, None)
            with pytest.raises(AuditBatchNotFoundError):
                await h.service.status(1)
            await h.seal()
            view = await h.service.status(1)
            assert view.chain.status is ChainVerificationStatus.NOT_CONFIGURED
            with pytest.raises(ChainConfigError):
                await h.service.submit(1)

    _run(scenario)


def test_verification_detects_chain_and_record_disagreements() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            chain = FakeChain()
            h = Harness(session, chain)
            batch = await h.seal()
            await h.service.submit(1)
            chain.mine()
            chain.head += 1
            await h.service.refresh(1)
            assert (await h.service.status(1)).chain.status is ChainVerificationStatus.VERIFIED

            # The chain no longer has it (e.g. a different contract deployment at that address).
            block = chain.recorded.pop(batch.commitment)
            assert (await h.service.status(1)).chain.status is ChainVerificationStatus.MISMATCH
            chain.recorded[batch.commitment] = block

            # The stored block was edited.
            row = (await h.rows())[0]
            row.block_number = block + 5
            await session.flush()
            assert (await h.service.status(1)).chain.status is ChainVerificationStatus.MISMATCH
            row.block_number = block

            # The stored receipt's tx no longer carries the commitment.
            assert row.tx_hash is not None
            original = chain.receipts[row.tx_hash]
            chain.receipts[row.tx_hash] = TxReceipt(
                tx_hash=row.tx_hash, succeeded=True, block_number=block, logs=()
            )
            assert (await h.service.status(1)).chain.status is ChainVerificationStatus.MISMATCH
            chain.receipts[row.tx_hash] = original

            # RPC down: reported, not guessed.
            chain.fail_with = ChainUnavailableError("rpc_unavailable")
            assert (await h.service.status(1)).chain.status is ChainVerificationStatus.UNAVAILABLE
            chain.fail_with = None

            # A local edit after anchoring: the expected commitment cannot be trusted.
            members_event = (
                (await session.execute(select(AuditLog).order_by(AuditLog.occurred_at)))
                .scalars()
                .first()
            )
            assert members_event is not None
            members_event.request_context = "edited"
            await session.flush()
            view = await h.service.status(1)
            assert view.local.is_valid is False
            assert view.chain.status is ChainVerificationStatus.LOCAL_INTEGRITY_FAILED

    _run(scenario)


def test_transient_error_during_refresh_leaves_pending() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            chain = FakeChain()
            h = Harness(session, chain)
            await h.seal()
            await h.service.submit(1)
            chain.fail_with = ChainUnavailableError("rpc_unavailable")
            out = await h.service.refresh(1)
            assert out.action is SubmissionAction.STILL_PENDING
            assert out.anchor is not None and out.anchor.status is ChainAnchorStatus.PENDING

    _run(scenario)


# -- HTTP --------------------------------------------------------------------------------


async def _seed_confirmed(engine: AsyncEngine, chain: FakeChain | None) -> tuple[UUID, str, str]:
    factory = create_session_factory(engine)
    async with factory() as session, session.begin():
        h = Harness(session, chain)
        batch = await h.seal()
        user = User(id=uuid4(), firebase_uid=f"fb-viewer-{uuid4()}", role=Role.PATIENT)
        session.add(user)
        await session.flush()
        if chain is not None:
            await h.service.submit(1)
            chain.mine()
            chain.head += 1
            await h.service.refresh(1)
        return user.id, user.firebase_uid, batch.commitment


def _auth(fake_auth: FakeAuthProvider, user_id: UUID, uid: str) -> dict[str, str]:
    token = f"token-{uid}"
    fake_auth.register_user(token, user_id=user_id, firebase_uid=uid, role=Role.PATIENT)
    return {"Authorization": f"Bearer {token}"}


def test_anchor_endpoint_reports_confirmed_and_verified(
    app: FastAPI,
    client: TestClient,
    fake_auth: FakeAuthProvider,
    db_engine: AsyncEngine,
    sqlite_db: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = FakeChain()
    user_id, uid, commitment = asyncio.run(_seed_confirmed(db_engine, chain))
    app.dependency_overrides[get_commitment_registry] = lambda: chain
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "chain_explorer_base_url", "https://amoy.polygonscan.com/")
    resp = client.get("/api/v1/audit-batches/1/anchor", headers=_auth(fake_auth, user_id, uid))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["localStatus"] == "VALID"
    assert data["commitment"] == commitment
    assert data["network"] == "polygon-amoy"
    assert data["chainId"] == 80002
    assert data["contractAddress"] == CONTRACT
    assert data["explorerContractUrl"] == f"https://amoy.polygonscan.com/address/{CONTRACT}"
    anchor = data["anchor"]
    assert anchor["status"] == "CONFIRMED"
    assert anchor["txHash"] == chain.broadcasts[0]
    assert anchor["explorerTxUrl"] == f"https://amoy.polygonscan.com/tx/{chain.broadcasts[0]}"
    assert data["chainVerification"]["status"] == "VERIFIED"
    assert data["chainVerification"]["expectedCommitment"] == commitment
    # No PHI or event identifiers in the payload.
    text = resp.text
    assert "PHI-IND" not in text and "Synthetic Patient" not in text


def test_anchor_endpoint_unconfigured_errors_and_auth(
    app: FastAPI,
    client: TestClient,
    fake_auth: FakeAuthProvider,
    db_engine: AsyncEngine,
    sqlite_db: None,
) -> None:
    user_id, uid, _ = asyncio.run(_seed_confirmed(db_engine, None))
    app.dependency_overrides[get_commitment_registry] = lambda: None
    headers = _auth(fake_auth, user_id, uid)
    resp = client.get("/api/v1/audit-batches/1/anchor", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["anchor"] is None
    assert data["network"] is None and data["explorerContractUrl"] is None
    assert data["chainVerification"]["status"] == "NOT_CONFIGURED"
    assert client.get("/api/v1/audit-batches/99/anchor", headers=headers).status_code == 404
    assert client.get("/api/v1/audit-batches/0/anchor", headers=headers).status_code == 422
    assert client.get("/api/v1/audit-batches/1/anchor").status_code == 401


def test_anchor_endpoint_has_no_write_method(client: TestClient) -> None:
    for method in ("post", "put", "patch", "delete"):
        assert getattr(client, method)("/api/v1/audit-batches/1/anchor").status_code in {401, 405}


def test_configured_logging_never_writes_the_rpc_url(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    from app.core.logging import configure_logging

    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    try:
        configure_logging("DEBUG")
        root.addHandler(caplog.handler)
        stub = RpcStub({"eth_call": "0x"})
        asyncio.run(_registry(stub).anchored_block(COMMITMENT))
        assert "SECRET-PROVIDER-KEY" not in caplog.text
    finally:
        root.handlers, root.level = saved_handlers, saved_level


def test_contract_address_is_normalized_to_eip55_checksum() -> None:
    # EIP-55's own test vectors.
    for address in (
        "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed",
        "0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359",
        "0xdbF03B407c01E7cD3CBea99509d93f8DDDC8C6FB",
    ):
        registry = JsonRpcCommitmentRegistry(
            rpc_url=RPC_URL, chain_id=80002, contract_address=address.lower()
        )
        assert registry.contract_address == address
    with pytest.raises(ChainConfigError):  # bad checksum: refused, not "corrected"
        JsonRpcCommitmentRegistry(
            rpc_url=RPC_URL,
            chain_id=80002,
            contract_address="0x5AAeb6053F3E94C9b9A09f33669435E7Ef1BeAed",
        )
