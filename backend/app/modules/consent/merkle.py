"""Deterministic Merkle batching of v3 audit digests (ADR-004, ADR-019; M6.2).

A batch commits many audit digests under one 32-byte root, so one on-chain transaction can
attest to all of them and each event can later prove its membership with a short path. The
construction is chosen so a Solidity contract can recompute every hash below with
``keccak256(abi.encodePacked(...))`` and nothing else:

* **Hash:** Ethereum Keccak-256 throughout — never SHA3-256, never Python's ``hash()``.
* **Leaf:** ``keccak256(0x00 || digest)`` where ``digest`` is the event's 32 raw bytes (the
  64-hex ``event_hash`` decoded). No JSON, no string encoding: a leaf commits to exactly the
  digest the row already carries.
* **Node:** ``keccak256(0x01 || left || right)``, 65 bytes in. The distinct prefixes are the
  domain separation (RFC 6962 §2.1): no leaf can ever be read as an internal node or the
  reverse, so a subtree root cannot be passed off as a member.
* **Odd node:** an unpaired last node is **promoted unchanged** to the next level (RFC 6962),
  never duplicated. Duplicating it (Bitcoin's rule) gives ``[a, b, c]`` and ``[a, b, c, c]``
  the same root, which is exactly the ambiguity an audit commitment must not have.
* **Pairs are positional, not sorted.** ``node(a, b) != node(b, a)``, so the root commits to
  the order of the batch, and a proof carries which side each sibling sits on.
* **Single leaf:** the root is that leaf's hash — ``keccak256(0x00 || digest)``, not the
  digest itself — and its proof is empty. **Empty batch:** refused; there is nothing to
  commit to and no root is defined.
* **Duplicate digests:** refused. A v3 digest covers the event's own id, so two equal
  digests mean the same event twice — a caller bug that would make "the proof for this
  digest" ambiguous.

Roots and siblings are 64 lowercase hex characters without ``0x``, the same shape as an
audit digest (``require_digest``), which maps one-to-one onto a Solidity ``bytes32``.

**Two layers, deliberately.** ``MerkleTree`` is the bare primitive over digests and cannot
know which scheme produced them — a 64-hex string says nothing about its algorithm.
``V3Batch`` is the entry point for anything bound for a chain: it admits only
rows whose ``hash_version`` is 3 *and* whose stored digest recomputes under v3, fixes the
order, and only then builds the tree.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from Crypto.Hash import keccak

from app.modules.consent.anchoring import InvalidDigestError, require_digest
from app.modules.consent.models import AuditLog
from app.modules.consent.service import (
    HASH_SCHEME_V3,
    as_utc,
    recompute_event_hash,
)

#: Domain-separation prefixes (RFC 6962 §2.1). One byte each, prepended before hashing.
LEAF_PREFIX: Final = b"\x00"
NODE_PREFIX: Final = b"\x01"
#: Prefix of the batch commitment (ADR-027 decision 5), distinct from both of the above.
COMMITMENT_PREFIX: Final = b"\x02"

#: The Merkle batch protocol this module implements (ADR-027 decision 3): Keccak-256, the
#: prefixes above, positional children, odd-node promotion, v3 leaves. Bound into every
#: commitment, so a future protocol can never be mistaken for this one.
MERKLE_PROTOCOL_VERSION: Final = 1

#: Field widths of the commitment preimage: ``uint8``, ``uint64``, ``uint32``.
_MAX_UINT8: Final = 2**8 - 1
_MAX_UINT64: Final = 2**64 - 1
_MAX_UINT32: Final = 2**32 - 1


class MerkleError(ValueError):
    """Base for refusals raised while building a batch or asking it for a proof."""


class EmptyBatchError(MerkleError):
    """A tree was requested over no digests; no root is defined for an empty batch."""


class DuplicateLeafError(MerkleError):
    """The same digest (or the same audit event) appears twice in one batch."""


class LeafIndexError(MerkleError):
    """A proof was requested for a position or event the batch does not contain."""


class InvalidCommitmentInputError(MerkleError):
    """A commitment field is not an integer, or does not fit its fixed width."""


class IneligibleEventError(MerkleError):
    """An audit event may not enter a chain batch: not v3, or its digest does not
    recompute under v3. Carries the event id only — never event content."""


def _keccak256(data: bytes) -> bytes:
    return keccak.new(digest_bits=256, data=data).digest()


def leaf_hash(digest: str) -> str:
    """``keccak256(0x00 || digest)``. Raises ``InvalidDigestError`` for a non-digest."""
    return _keccak256(LEAF_PREFIX + bytes.fromhex(require_digest(digest))).hex()


def node_hash(left: str, right: str) -> str:
    """``keccak256(0x01 || left || right)``. Raises ``InvalidDigestError`` for a non-hash."""
    return _keccak256(
        NODE_PREFIX + bytes.fromhex(require_digest(left)) + bytes.fromhex(require_digest(right))
    ).hex()


@dataclass(frozen=True, slots=True)
class ProofStep:
    """One level of a membership path: the sibling hash and which side it sits on."""

    sibling: str
    sibling_on_left: bool


@dataclass(frozen=True, slots=True)
class MerkleProof:
    """The path from one leaf to the root.

    ``leaf_index`` and ``leaf_count`` are the position the proof *claims*. They fix the
    path's expected shape — how many steps, and which side each sibling is on (a promoted
    node contributes no step) — and ``verify_proof`` rejects a path that does not have it.
    **They are not authenticated by the root**: the root commits to the leaves, not to how
    many there are, and several (index, count) pairs share one shape — the path of leaf 4
    in a five-leaf tree is also the shape of leaf 1 in a two-leaf tree. Treat them as
    trustworthy only when they match values the caller obtained independently (see
    ``verify_proof``'s ``trusted_leaf_index`` / ``trusted_leaf_count``).
    """

    leaf_index: int
    leaf_count: int
    steps: tuple[ProofStep, ...]


def _path_shape(leaf_index: int, leaf_count: int) -> list[bool]:
    """``sibling_on_left`` for every level that has a sibling, bottom up.

    Levels where the node is the unpaired last one are skipped: it is promoted unchanged,
    so the path has no step there.
    """
    shape: list[bool] = []
    index, width = leaf_index, leaf_count
    while width > 1:
        if index % 2 == 1:
            shape.append(True)
        elif index + 1 < width:
            shape.append(False)
        index //= 2
        width = (width + 1) // 2
    return shape


class MerkleTree:
    """A positional Merkle tree over an ordered list of digests.

    **Does not check hash versions** — it cannot; see ``V3Batch`` for the chain-bound
    entry point. Every input must still be a well-formed digest (``InvalidDigestError``),
    there must be at least one (``EmptyBatchError``), and none may repeat
    (``DuplicateLeafError``).
    """

    def __init__(self, digests: Sequence[str]) -> None:
        if not digests:
            raise EmptyBatchError("a Merkle batch needs at least one digest")
        if len(set(digests)) != len(digests):
            raise DuplicateLeafError("a Merkle batch may not contain the same digest twice")
        self._digests: tuple[str, ...] = tuple(digests)
        levels = [[leaf_hash(digest) for digest in self._digests]]
        while len(levels[-1]) > 1:
            below = levels[-1]
            above = [node_hash(below[i], below[i + 1]) for i in range(0, len(below) - 1, 2)]
            if len(below) % 2 == 1:
                above.append(below[-1])  # promoted unchanged, never duplicated
            levels.append(above)
        self._levels = levels

    @property
    def root(self) -> str:
        return self._levels[-1][0]

    @property
    def leaf_count(self) -> int:
        return len(self._digests)

    @property
    def digests(self) -> tuple[str, ...]:
        return self._digests

    def proof(self, leaf_index: int) -> MerkleProof:
        """The membership path for the leaf at ``leaf_index``."""
        if not 0 <= leaf_index < self.leaf_count:
            raise LeafIndexError(f"leaf index {leaf_index} is outside a batch of {self.leaf_count}")
        steps: list[ProofStep] = []
        index = leaf_index
        for level in self._levels[:-1]:
            if index % 2 == 1:
                steps.append(ProofStep(sibling=level[index - 1], sibling_on_left=True))
            elif index + 1 < len(level):
                steps.append(ProofStep(sibling=level[index + 1], sibling_on_left=False))
            index //= 2
        return MerkleProof(leaf_index=leaf_index, leaf_count=self.leaf_count, steps=tuple(steps))


def _is_int(value: object) -> bool:
    """A real integer — ``bool`` is an ``int`` subclass in Python and is not accepted."""
    return type(value) is int


def _well_formed(proof: object) -> bool:
    """Runtime shape of an untrusted proof: the right types all the way down."""
    if not isinstance(proof, MerkleProof):
        return False
    if not (_is_int(proof.leaf_index) and _is_int(proof.leaf_count)):
        return False
    if not isinstance(proof.steps, tuple | list):
        return False
    return all(
        isinstance(step, ProofStep)
        and isinstance(step.sibling, str)
        and type(step.sibling_on_left) is bool
        for step in proof.steps
    )


def verify_proof(
    digest: str,
    proof: MerkleProof,
    root: str,
    *,
    trusted_leaf_index: int | None = None,
    trusted_leaf_count: int | None = None,
) -> bool:
    """Whether ``proof`` shows ``digest`` is a leaf of the tree committed to by ``root``.

    **What ``True`` means depends on what the caller trusts:**

    * With no trusted values: ``digest`` is a member of the tree whose root is ``root``.
      Nothing more — ``proof.leaf_index`` and ``proof.leaf_count`` only had to be
      *consistent* with the path, and other (index, count) pairs can be equally consistent
      (see ``MerkleProof``). Do not read a position or a batch size off such a proof.
    * With ``trusted_leaf_count`` (e.g. the leaf count stored beside an anchored root) and
      ``trusted_leaf_index`` (e.g. the event's recorded position): additionally, ``digest``
      is the leaf at exactly that position of a batch of exactly that size. A proof that
      claims any other index or count is rejected before any hashing.

    In neither case does it say the batch is *complete* — that every event that should be
    in it is — which only a reconciliation against the database can establish.

    **Never raises for untrusted input.** A malformed or wrongly typed digest, root, proof,
    step or sibling, a ``bool`` where an integer index/count is required, a non-``bool``
    side flag, an impossible index or count, or a path whose length or sides do not match
    the claimed position are all simply ``False``: an exception would be a second, implicit
    answer for a caller to forget to handle. The trusted values are the caller's own and are
    held to a stricter standard: a non-integer there is a programming error and raises
    ``TypeError``.
    """
    for name, trusted in (
        ("trusted_leaf_index", trusted_leaf_index),
        ("trusted_leaf_count", trusted_leaf_count),
    ):
        if trusted is not None and not _is_int(trusted):
            raise TypeError(f"{name} must be an int")
    if not (isinstance(digest, str) and isinstance(root, str) and _well_formed(proof)):
        return False
    if trusted_leaf_index is not None and proof.leaf_index != trusted_leaf_index:
        return False
    if trusted_leaf_count is not None and proof.leaf_count != trusted_leaf_count:
        return False
    if not 0 <= proof.leaf_index < proof.leaf_count:
        return False
    shape = _path_shape(proof.leaf_index, proof.leaf_count)
    if [step.sibling_on_left for step in proof.steps] != shape:
        return False
    try:
        require_digest(root)
        current = leaf_hash(digest)
        for step in proof.steps:
            if step.sibling_on_left:
                current = node_hash(step.sibling, current)
            else:
                current = node_hash(current, step.sibling)
    except InvalidDigestError:
        return False
    return current == root


@dataclass(frozen=True, slots=True)
class BatchLeaf:
    """One event's place in a batch: which event, and the digest committed for it."""

    audit_log_id: UUID
    digest: str


class V3Batch:
    """The chain-bound batch: v3-verified events, in canonical order, and their tree.

    **Admission happens in the constructor**, so there is no way to hold a ``V3Batch``
    whose events were not checked. Two checks per row, because neither alone is proof:
    ``hash_version == 3`` is a label outside the hashed payload (ADR-023), and a 64-hex
    ``event_hash`` says nothing about its algorithm. Recomputing the digest under v3 and
    finding it equal to the stored one is what shows it is the Keccak-256 digest of this
    row. Any failure refuses the whole batch rather than silently dropping the row.

    **Canonical order** is ``(occurred_at ASC, id ASC)`` — the order the anchoring sweep
    already selects unanchored events in (``AuditAnchorRepository.list_unanchored_events``)
    — applied here regardless of the order rows arrive in, so the same set of events always
    yields the same root.
    """

    def __init__(self, entries: Iterable[AuditLog]) -> None:
        rows = list(entries)
        for row in rows:
            # The id is the hashed payload's first field and the leaf's only link back to its
            # event. ``AuditLog.id`` gets its uuid4 default only at flush, so an unflushed row
            # built without one carries ``None`` — and would hash ``"None"`` consistently and
            # pass the recompute check below. The value is never echoed: it is not a UUID.
            if not isinstance(row.id, UUID):
                raise IneligibleEventError("an audit event without a valid UUID id")
        if len({row.id for row in rows}) != len(rows):
            raise DuplicateLeafError("a Merkle batch may not contain the same audit event twice")
        for row in rows:
            if row.hash_version != HASH_SCHEME_V3:
                raise IneligibleEventError(
                    f"audit event {row.id} has hash_version {row.hash_version}, not 3"
                )
            if recompute_event_hash(row) != row.event_hash:
                raise IneligibleEventError(
                    f"audit event {row.id} does not recompute to its stored digest"
                )
        rows.sort(key=lambda row: (as_utc(row.occurred_at), row.id))
        self._leaves = tuple(BatchLeaf(audit_log_id=row.id, digest=row.event_hash) for row in rows)
        self._tree = MerkleTree([leaf.digest for leaf in self._leaves])
        self._index = {leaf.audit_log_id: position for position, leaf in enumerate(self._leaves)}

    @property
    def leaves(self) -> tuple[BatchLeaf, ...]:
        return self._leaves

    @property
    def root(self) -> str:
        return self._tree.root

    def proof_for(self, audit_log_id: UUID) -> MerkleProof:
        """The membership path for one event of this batch."""
        try:
            position = self._index[audit_log_id]
        except KeyError:
            raise LeafIndexError(f"audit event {audit_log_id} is not in this batch") from None
        return self._tree.proof(position)


def batch_commitment(
    *, protocol_version: int, batch_number: int, leaf_count: int, root: str
) -> str:
    """The one value a batch publishes (ADR-027 decision 5)::

        keccak256(0x02 ‖ uint8 protocol_version ‖ uint64 batch_number ‖ uint32 leaf_count ‖ root)

    Packed and big-endian, 46 bytes in — Solidity's
    ``keccak256(abi.encodePacked(bytes1(0x02), uint8(v), uint64(n), uint32(c), root))``.
    Binding the count and sequence number here is what makes them authoritative rather than
    proof-supplied claims.

    Refuses rather than truncates: a non-``int`` (``bool`` included), a value outside its
    width, a zero batch number or leaf count, or a protocol version of 0 raises
    ``InvalidCommitmentInputError``; a malformed root raises ``InvalidDigestError``.
    """
    for name, value, low, high in (
        ("protocol_version", protocol_version, 1, _MAX_UINT8),
        ("batch_number", batch_number, 1, _MAX_UINT64),
        ("leaf_count", leaf_count, 1, _MAX_UINT32),
    ):
        if not _is_int(value) or not low <= value <= high:
            raise InvalidCommitmentInputError(f"{name} must be an integer in [{low}, {high}]")
    preimage = (
        COMMITMENT_PREFIX
        + protocol_version.to_bytes(1, "big")
        + batch_number.to_bytes(8, "big")
        + leaf_count.to_bytes(4, "big")
        + bytes.fromhex(require_digest(root))
    )
    return _keccak256(preimage).hex()
