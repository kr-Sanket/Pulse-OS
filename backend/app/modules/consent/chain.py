"""The batch-commitment registry port and its EVM JSON-RPC adapter (ADR-027, ADR-035).

What crosses this boundary is a batch commitment ``C`` (64 lowercase hex, ADR-027 decision 5)
and chain coordinates — never an event, a patient, a root or a digest. ``require_digest``
gates every commitment, so the port cannot be handed a clinical payload (decision 12).

``CommitmentRegistry`` is deliberately separate from the per-event ``AuditAnchor`` port
(``anchoring.py``): a public chain has a pending → mined → confirmed lifecycle that a
synchronous ``submit → receipt`` cannot express, and the per-event port stays as it is for
historical rows.

``JsonRpcCommitmentRegistry`` talks plain Ethereum JSON-RPC over ``httpx`` to the
``AuditCommitmentRegistry`` contract (contracts/src). Signing uses ``eth-account`` and happens
locally; the key never leaves the process and is never logged or put in an error. Only
testnet and local development chain ids are accepted (``ALLOWED_CHAIN_IDS``): this code
refuses to send anything to a mainnet.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Protocol

import httpx
from Crypto.Hash import keccak

from app.modules.consent.anchoring import require_digest

#: Chain ids this code will talk to. Polygon Amoy (ADR-027's target), Ethereum Sepolia, and
#: the local development chain id used by anvil/hardhat. Anything else — every mainnet
#: included — is refused before a request is made.
ALLOWED_CHAIN_IDS: Final[Mapping[int, str]] = {
    80002: "polygon-amoy",
    11155111: "ethereum-sepolia",
    31337: "local-evm",
}

# ABI of contracts/src/AuditCommitmentRegistry.sol (pinned by tests/test_chain_registry.py
# against keccak of the signatures).
ANCHOR_SELECTOR: Final = "0xeecdf927"
ANCHORED_BLOCK_SELECTOR: Final = "0x65cbe879"
COMMITMENT_ANCHORED_TOPIC: Final = (
    "0x1cf0da3ca427b38287262cdd97cbccf45bc3d3a18e8d6608f880b895b294a0d4"
)

_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
_TX_HASH = re.compile(r"^0x[0-9a-f]{64}$")


class ChainError(Exception):
    """A chain interaction failed. ``code`` is short, stable and safe to persist or show.

    The message never carries an RPC response body, URL or key — RPC URLs often embed API
    keys and node errors can echo request data.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ChainUnavailableError(ChainError):
    """Transport failure, timeout or non-JSON-RPC answer: the chain could not be asked."""


class ChainRpcError(ChainError):
    """The node answered with a JSON-RPC error (e.g. a revert during gas estimation)."""


class ChainConfigError(ChainError):
    """Configuration is unusable: unknown chain id, malformed address, missing signer."""


@dataclass(frozen=True, slots=True)
class LogEntry:
    address: str
    topics: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TxReceipt:
    tx_hash: str
    succeeded: bool
    block_number: int
    logs: tuple[LogEntry, ...]

    def records_commitment(self, *, contract_address: str, commitment: str) -> bool:
        """Whether this receipt carries the registry's ``CommitmentAnchored(C)`` event.

        A transaction hash alone proves nothing about *what* was stored; this is the check
        that ties the mined transaction to the intended commitment.
        """
        expected_topic = "0x" + require_digest(commitment)
        return any(
            log.address.lower() == contract_address.lower()
            and len(log.topics) >= 2
            and log.topics[0].lower() == COMMITMENT_ANCHORED_TOPIC
            and log.topics[1].lower() == expected_topic
            for log in self.logs
        )


class CommitmentRegistry(Protocol):
    """Publish batch commitments to a write-restricted on-chain registry, and read them back."""

    @property
    def network(self) -> str: ...

    @property
    def chain_id(self) -> int: ...

    @property
    def contract_address(self) -> str: ...

    async def remote_chain_id(self) -> int:
        """The chain id the RPC endpoint reports (compared with ``chain_id`` before writes)."""
        ...

    async def anchored_block(self, commitment: str) -> int:
        """Block in which ``commitment`` was recorded, read from contract state; 0 if never."""
        ...

    async def submit(self, commitment: str) -> str:
        """Sign and broadcast ``anchor(C)``; returns the transaction hash. Not yet mined."""
        ...

    async def get_receipt(self, tx_hash: str) -> TxReceipt | None:
        """The mined receipt, or None while the transaction is still pending/unknown."""
        ...

    async def head_block(self) -> int: ...

    async def block_timestamp(self, block_number: int) -> datetime: ...

    async def find_anchor_tx(self, commitment: str, block_number: int) -> str | None:
        """Hash of the transaction that emitted ``CommitmentAnchored(C)`` in that block."""
        ...


class Signer(Protocol):
    """The slice of ``eth_account``'s ``LocalAccount`` used here (keeps the type local)."""

    @property
    def address(self) -> str: ...

    def sign_transaction(self, transaction_dict: dict[str, Any]) -> Any: ...


def network_for_chain_id(chain_id: int) -> str:
    """The canonical network label for an allowed chain id; refuses everything else."""
    try:
        return ALLOWED_CHAIN_IDS[chain_id]
    except KeyError:
        raise ChainConfigError("chain_id_not_allowed") from None


def require_address(value: str) -> str:
    """A 20-byte hex address, returned in EIP-55 checksum form (what signers require).

    A mixed-case input must already carry a valid checksum — a typo in a configured address
    is refused rather than silently "corrected" into a different account.
    """
    if not _ADDRESS.match(value):
        raise ChainConfigError("invalid_contract_address")
    checksummed = to_checksum_address(value)
    body = value[2:]
    if body != body.lower() and body != body.upper() and value != checksummed:
        raise ChainConfigError("invalid_contract_address")
    return checksummed


def to_checksum_address(value: str) -> str:
    """EIP-55 mixed-case checksum encoding of a hex address."""
    body = value[2:].lower()
    digest = keccak.new(digest_bits=256, data=body.encode()).hexdigest()
    return "0x" + "".join(
        char.upper() if char.isalpha() and int(digest[i], 16) >= 8 else char
        for i, char in enumerate(body)
    )


def _quantity(value: object) -> int:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise ChainUnavailableError("malformed_rpc_response")
    try:
        return int(value, 16)
    except ValueError:
        raise ChainUnavailableError("malformed_rpc_response") from None


class JsonRpcCommitmentRegistry:
    """``CommitmentRegistry`` over Ethereum JSON-RPC (Polygon Amoy, Sepolia, local anvil)."""

    def __init__(
        self,
        *,
        rpc_url: str,
        chain_id: int,
        contract_address: str,
        signer: Signer | None = None,
        timeout_seconds: float = 10.0,
        min_priority_fee_per_gas: int = 0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if min_priority_fee_per_gas < 0:
            raise ChainConfigError("invalid_min_priority_fee")
        self._network = network_for_chain_id(chain_id)
        self._chain_id = chain_id
        self._contract = require_address(contract_address)
        self._rpc_url = rpc_url
        self._signer = signer
        self._timeout = timeout_seconds
        self._min_priority_fee_per_gas = min_priority_fee_per_gas
        self._transport = transport
        self._request_id = 0

    @property
    def network(self) -> str:
        return self._network

    @property
    def chain_id(self) -> int:
        return self._chain_id

    @property
    def contract_address(self) -> str:
        return self._contract

    async def _call(self, method: str, params: list[Any]) -> Any:
        self._request_id += 1
        payload = {"jsonrpc": "2.0", "id": self._request_id, "method": method, "params": params}
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.post(self._rpc_url, json=payload)
        except httpx.HTTPError:
            raise ChainUnavailableError("rpc_unavailable") from None
        if response.status_code != 200:
            raise ChainUnavailableError("rpc_unavailable")
        try:
            body = response.json()
        except ValueError:
            raise ChainUnavailableError("malformed_rpc_response") from None
        if not isinstance(body, dict):
            raise ChainUnavailableError("malformed_rpc_response")
        if body.get("error") is not None:
            raise ChainRpcError("rpc_error")
        if "result" not in body:
            raise ChainUnavailableError("malformed_rpc_response")
        return body["result"]

    async def remote_chain_id(self) -> int:
        return _quantity(await self._call("eth_chainId", []))

    async def anchored_block(self, commitment: str) -> int:
        data = ANCHORED_BLOCK_SELECTOR + require_digest(commitment)
        result = await self._call("eth_call", [{"to": self._contract, "data": data}, "latest"])
        return _quantity(result) if result != "0x" else 0

    async def head_block(self) -> int:
        return _quantity(await self._call("eth_blockNumber", []))

    async def block_timestamp(self, block_number: int) -> datetime:
        block = await self._call("eth_getBlockByNumber", [hex(block_number), False])
        if not isinstance(block, dict):
            raise ChainUnavailableError("block_not_found")
        return datetime.fromtimestamp(_quantity(block.get("timestamp")), tz=UTC)

    async def get_receipt(self, tx_hash: str) -> TxReceipt | None:
        receipt = await self._call("eth_getTransactionReceipt", [tx_hash])
        if receipt is None:
            return None
        if not isinstance(receipt, dict):
            raise ChainUnavailableError("malformed_rpc_response")
        logs = tuple(
            LogEntry(address=str(log.get("address", "")), topics=tuple(log.get("topics", [])))
            for log in receipt.get("logs", [])
            if isinstance(log, dict)
        )
        return TxReceipt(
            tx_hash=tx_hash,
            succeeded=_quantity(receipt.get("status")) == 1,
            block_number=_quantity(receipt.get("blockNumber")),
            logs=logs,
        )

    async def find_anchor_tx(self, commitment: str, block_number: int) -> str | None:
        logs = await self._call(
            "eth_getLogs",
            [
                {
                    "address": self._contract,
                    "fromBlock": hex(block_number),
                    "toBlock": hex(block_number),
                    "topics": [COMMITMENT_ANCHORED_TOPIC, "0x" + require_digest(commitment)],
                }
            ],
        )
        if not isinstance(logs, list):
            raise ChainUnavailableError("malformed_rpc_response")
        for log in logs:
            if isinstance(log, dict) and isinstance(log.get("transactionHash"), str):
                return str(log["transactionHash"]).lower()
        return None

    async def submit(self, commitment: str) -> str:
        """Estimate, sign and broadcast ``anchor(C)`` as an EIP-1559 transaction.

        Gas estimation runs the call first, so an unauthorized sender or an already-recorded
        commitment fails here as ``ChainRpcError`` and nothing is broadcast.
        """
        if self._signer is None:
            raise ChainConfigError("signer_not_configured")
        data = ANCHOR_SELECTOR + require_digest(commitment)
        sender = self._signer.address
        call = {"from": sender, "to": self._contract, "data": data}
        gas = _quantity(await self._call("eth_estimateGas", [call]))
        nonce = _quantity(await self._call("eth_getTransactionCount", [sender, "pending"]))
        latest = await self._call("eth_getBlockByNumber", ["latest", False])
        if not isinstance(latest, dict):
            raise ChainUnavailableError("block_not_found")
        base_fee = _quantity(latest.get("baseFeePerGas", "0x0"))
        priority_fee = 0
        try:
            priority_fee = _quantity(await self._call("eth_maxPriorityFeePerGas", []))
        except ChainRpcError:
            if self._min_priority_fee_per_gas <= 0:
                raise
        if priority_fee < self._min_priority_fee_per_gas:
            priority_fee = self._min_priority_fee_per_gas
        transaction = {
            "type": 2,
            "chainId": self._chain_id,
            "nonce": nonce,
            "to": self._contract,
            "value": 0,
            "data": data,
            # Headroom over the estimate; unused gas is not charged.
            "gas": gas + gas // 5,
            "maxPriorityFeePerGas": priority_fee,
            "maxFeePerGas": 2 * base_fee + priority_fee,
        }
        signed = self._signer.sign_transaction(transaction)
        raw = "0x" + bytes(signed.raw_transaction).hex()
        tx_hash = await self._call("eth_sendRawTransaction", [raw])
        if not isinstance(tx_hash, str) or not _TX_HASH.match(tx_hash.lower()):
            raise ChainUnavailableError("malformed_rpc_response")
        return tx_hash.lower()
