"""Merkle batching of v3 audit digests (M6.2; app/modules/consent/merkle.py).

The pinned vectors below are intended to be reproduced verbatim by the Solidity contract's
tests: leaves are ``keccak256(abi.encodePacked(bytes1(0x00), digest))`` and nodes
``keccak256(abi.encodePacked(bytes1(0x01), left, right))``, with an unpaired last node
promoted unchanged.

**What is and is not independent here.** The pinned roots and proofs are regression vectors:
they were validated *manually*, when written, against a separate from-scratch tree hashing
with OpenSSL's ``keccak-256`` (OpenSSL >= 3.2) instead of pycryptodome, and against RFC 6962's
recursive tree-hash definition. That cross-check is not automated, because CI's OpenSSL is not
guaranteed to expose Keccak. In CI, the independent anchor for the hash function itself is
the published Keccak-256 vectors (``test_merkle_keccak_reproduces_published_vectors``).
"""

import datetime as dt
import hashlib
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.modules.auth.domain import Role
from app.modules.consent.anchoring import InvalidDigestError
from app.modules.consent.merkle import (
    LEAF_PREFIX,
    NODE_PREFIX,
    DuplicateLeafError,
    EmptyBatchError,
    IneligibleEventError,
    LeafIndexError,
    MerkleProof,
    MerkleTree,
    ProofStep,
    V3Batch,
    _keccak256,
    _path_shape,
    leaf_hash,
    node_hash,
    verify_proof,
)
from app.modules.consent.models import AuditAction, AuditLog
from app.modules.consent.service import (
    HASH_SCHEME_V1,
    HASH_SCHEME_V2,
    HASH_SCHEME_V3,
    keccak256_event_hash,
    recompute_event_hash,
)
from Crypto.Hash import keccak

#: Five fixed digests: 0x1111…11 through 0x5555…55.
D = [byte * 32 for byte in ("11", "22", "33", "44", "55")]

#: ``leaf_hash(D[0])``.
LEAF_0 = "5f61df1468962c8107c77ae5f01bbd92c363c87a057eba326bd87ca93188e313"

#: Roots over the first n digests of ``D`` — odd and even counts, including the
#: single-leaf case (whose root is the leaf hash).
ROOTS = {
    1: LEAF_0,
    2: "ace91b357d1aad4381cfd1f6635c93b76c70ec4e3933fed11d397a2d6d8db5e2",
    3: "496c05622cbf04ed3ebb29ddd3ee572a3e338db13723f6a30e0a9a96990521d6",
    4: "01dd97a595388b4f43ec5980831684b8b3d1cf052e6899af96ee41cb83058640",
    5: "9649d2b300d317f168dd1ac9b6c8db26888dc5cb4d28bd394e22fa75d0cb1952",
}

#: Membership paths in the five-leaf tree, as (sibling, sibling_on_left), bottom up. Leaf 4
#: is promoted twice and so pairs only once, with the root of the first four.
PROOFS_OF_5 = {
    0: [
        ("9608b11d41faf730ce9e119a06798480433341ea1fa9cf8c0f0edb544d30c0b5", False),
        ("136a9a482a94533d4a35fca36c84005c4badb0aa0edbe4e29459f41a34c5cca8", False),
        ("39b3f2fa322d6172f0d73d905908ec6a3abfb563890a98cdf1f90ec89e57ffec", False),
    ],
    2: [
        ("a9c53bf7cea0d9ad600e9d73dc217e78ebbeb78697719d0b98b9d011ab8fd1e9", False),
        ("ace91b357d1aad4381cfd1f6635c93b76c70ec4e3933fed11d397a2d6d8db5e2", True),
        ("39b3f2fa322d6172f0d73d905908ec6a3abfb563890a98cdf1f90ec89e57ffec", False),
    ],
    4: [
        ("01dd97a595388b4f43ec5980831684b8b3d1cf052e6899af96ee41cb83058640", True),
    ],
}

BASE = dt.datetime(2026, 10, 1, 9, 0, tzinfo=dt.UTC)


def _raw_keccak(data: bytes) -> str:
    return keccak.new(digest_bits=256, data=data).hexdigest()


def _event(
    *, scheme: int = HASH_SCHEME_V3, seconds: int = 0, event_id: UUID | None = None
) -> AuditLog:
    """An in-memory audit row hashed under ``scheme``. No session: hashing reads columns only."""
    event = AuditLog(
        id=event_id or uuid4(),
        actor_user_id=UUID("22222222-2222-4222-8222-222222222222"),
        actor_role=Role.PATIENT,
        action=AuditAction.RECORD_VIEWED,
        patient_id=UUID("33333333-3333-4333-8333-333333333333"),
        target_record_id=None,
        target_category_id=None,
        target_request_id=None,
        request_context=None,
        occurred_at=BASE + dt.timedelta(seconds=seconds),
        actor_hospital_id=None,
        hash_version=scheme,
        event_hash="",
    )
    event.event_hash = recompute_event_hash(event)
    return event


# -- hashing primitives and domain separation -------------------------------------------


def test_leaf_hash_is_keccak_of_prefixed_raw_digest_bytes() -> None:
    assert leaf_hash(D[0]) == LEAF_0
    assert _raw_keccak(LEAF_PREFIX + bytes.fromhex(D[0])) == LEAF_0


def test_node_hash_is_keccak_of_prefixed_concatenation() -> None:
    left, right = leaf_hash(D[0]), leaf_hash(D[1])

    assert node_hash(left, right) == _raw_keccak(
        NODE_PREFIX + bytes.fromhex(left) + bytes.fromhex(right)
    )


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (b"", "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"),
        (b"abc", "4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45"),
    ],
)
def test_merkle_keccak_reproduces_published_vectors(message: bytes, expected: str) -> None:
    """Published Keccak-256 vectors (the empty one is Ethereum's ``KECCAK_EMPTY``): the
    independent check that the Merkle primitive is Keccak-256 and not SHA3-256."""
    assert _keccak256(message).hex() == expected
    assert hashlib.sha3_256(message).hexdigest() != expected


def test_merkle_and_event_hashing_share_one_keccak_implementation() -> None:
    """A consistency check, **not** an independent cross-check: both sides are pycryptodome.
    It pins that the Merkle layer and v3 event digests use the same function, so a later
    change to one cannot silently diverge from the other."""
    for text in ("", "abc", '{"action":"RECORD_VIEWED"}'):
        assert _keccak256(text.encode()).hex() == keccak256_event_hash(text)


def test_leaves_and_nodes_are_domain_separated() -> None:
    left, right = leaf_hash(D[0]), leaf_hash(D[1])
    unprefixed_node = _raw_keccak(bytes.fromhex(left) + bytes.fromhex(right))

    assert leaf_hash(D[0]) != _raw_keccak(bytes.fromhex(D[0]))  # a leaf is not the bare hash
    assert node_hash(left, right) != unprefixed_node
    # A 64-byte node preimage read as a leaf would need the 0x00 prefix; it never matches.
    assert node_hash(left, right) != _raw_keccak(
        LEAF_PREFIX + bytes.fromhex(left) + bytes.fromhex(right)
    )


def test_merkle_hashing_is_not_sha3_256() -> None:
    preimage = LEAF_PREFIX + bytes.fromhex(D[0])

    assert leaf_hash(D[0]) != hashlib.sha3_256(preimage).hexdigest()


def test_node_order_matters() -> None:
    left, right = leaf_hash(D[0]), leaf_hash(D[1])

    assert node_hash(left, right) != node_hash(right, left)


# -- tree shape ---------------------------------------------------------------------------


def test_an_empty_batch_is_refused() -> None:
    with pytest.raises(EmptyBatchError):
        MerkleTree([])


def test_a_single_leaf_root_is_its_leaf_hash_with_an_empty_proof() -> None:
    tree = MerkleTree([D[0]])
    proof = tree.proof(0)

    assert tree.root == LEAF_0
    assert tree.root != D[0]
    assert proof.steps == ()
    assert verify_proof(D[0], proof, tree.root)


def test_a_two_leaf_root_hashes_the_two_leaves_in_order() -> None:
    assert MerkleTree(D[:2]).root == node_hash(leaf_hash(D[0]), leaf_hash(D[1]))


def test_an_odd_last_node_is_promoted_not_duplicated() -> None:
    a, b, c = (leaf_hash(digest) for digest in D[:3])

    assert MerkleTree(D[:3]).root == node_hash(node_hash(a, b), c)
    assert MerkleTree(D[:3]).root != node_hash(node_hash(a, b), node_hash(c, c))


@pytest.mark.parametrize("count", sorted(ROOTS))
def test_roots_match_pinned_vectors(count: int) -> None:
    tree = MerkleTree(D[:count])

    assert tree.root == ROOTS[count]
    assert tree.leaf_count == count


def test_roots_are_deterministic() -> None:
    assert MerkleTree(D).root == MerkleTree(list(D)).root == ROOTS[5]


@pytest.mark.parametrize("count", [2, 3, 4, 5])
def test_roots_are_order_sensitive(count: int) -> None:
    assert MerkleTree(list(reversed(D[:count]))).root != ROOTS[count]


def test_swapping_two_leaves_changes_the_root() -> None:
    swapped = [D[1], D[0], *D[2:]]

    assert MerkleTree(swapped).root != ROOTS[5]


@pytest.mark.parametrize(
    "bad",
    ["", "a" * 63, "a" * 65, "A" * 64, "g" * 64, "0x" + "a" * 62, "0x" + "a" * 64, " " + "a" * 63],
)
def test_invalid_digests_are_refused(bad: str) -> None:
    with pytest.raises(InvalidDigestError):
        MerkleTree([D[0], bad])
    with pytest.raises(InvalidDigestError):
        leaf_hash(bad)


def test_duplicate_digests_are_refused() -> None:
    with pytest.raises(DuplicateLeafError):
        MerkleTree([D[0], D[1], D[0]])


# -- proofs -------------------------------------------------------------------------------


@pytest.mark.parametrize("index", sorted(PROOFS_OF_5))
def test_proofs_match_pinned_vectors(index: int) -> None:
    proof = MerkleTree(D).proof(index)

    assert [(step.sibling, step.sibling_on_left) for step in proof.steps] == PROOFS_OF_5[index]
    assert (proof.leaf_index, proof.leaf_count) == (index, 5)
    assert verify_proof(D[index], proof, ROOTS[5])


@pytest.mark.parametrize("count", range(1, 18))
def test_every_leaf_of_every_small_tree_proves_membership(count: int) -> None:
    digests = [_raw_keccak(f"leaf-{i}".encode()) for i in range(count)]
    tree = MerkleTree(digests)

    for index, digest in enumerate(digests):
        assert verify_proof(digest, tree.proof(index), tree.root)


@pytest.mark.parametrize("index", [-1, 5, 99])
def test_a_proof_outside_the_batch_is_refused(index: int) -> None:
    with pytest.raises(LeafIndexError):
        MerkleTree(D).proof(index)


def test_a_modified_leaf_fails_verification() -> None:
    proof = MerkleTree(D).proof(2)

    assert not verify_proof(D[3], proof, ROOTS[5])
    assert not verify_proof("3" * 63 + "4", proof, ROOTS[5])


def test_a_modified_root_fails_verification() -> None:
    proof = MerkleTree(D).proof(2)

    assert not verify_proof(D[2], proof, ROOTS[4])
    assert not verify_proof(D[2], proof, "0" * 64)


def test_a_proof_for_another_position_fails_verification() -> None:
    tree = MerkleTree(D)
    proof = tree.proof(0)
    moved = MerkleProof(leaf_index=1, leaf_count=5, steps=proof.steps)

    assert not verify_proof(D[0], moved, tree.root)


def _malformed_variants(proof: MerkleProof) -> list[MerkleProof]:
    first = proof.steps[0]
    return [
        # a sibling on the wrong side
        MerkleProof(
            proof.leaf_index,
            proof.leaf_count,
            (ProofStep(first.sibling, not first.sibling_on_left), *proof.steps[1:]),
        ),
        # a step missing, or one too many
        MerkleProof(proof.leaf_index, proof.leaf_count, proof.steps[:-1]),
        MerkleProof(proof.leaf_index, proof.leaf_count, (*proof.steps, first)),
        # a sibling hash altered
        MerkleProof(
            proof.leaf_index,
            proof.leaf_count,
            (ProofStep("0" * 64, first.sibling_on_left), *proof.steps[1:]),
        ),
        # siblings that are not hashes at all
        MerkleProof(
            proof.leaf_index,
            proof.leaf_count,
            (ProofStep("not-a-hash", first.sibling_on_left), *proof.steps[1:]),
        ),
        MerkleProof(
            proof.leaf_index,
            proof.leaf_count,
            (ProofStep("0x" + first.sibling[2:], first.sibling_on_left), *proof.steps[1:]),
        ),
        # impossible positions
        MerkleProof(-1, proof.leaf_count, proof.steps),
        MerkleProof(proof.leaf_count, proof.leaf_count, proof.steps),
        MerkleProof(0, 0, ()),
        MerkleProof(proof.leaf_index, 1, ()),
        # a wrong batch size whose expected path shape differs from this path's. A wrong
        # size with the *same* shape is not caught by shape alone — see the relabelling
        # tests below, which need a trusted count to reject it.
        MerkleProof(proof.leaf_index, proof.leaf_count + 4, proof.steps),
    ]


def test_malformed_proofs_are_rejected_without_raising() -> None:
    tree = MerkleTree(D)
    proof = tree.proof(2)
    # The wrong-size variant above is only a valid "malformed" case if its shape differs.
    assert _path_shape(2, 9) != _path_shape(2, 5)

    for variant in _malformed_variants(proof):
        assert verify_proof(D[2], variant, tree.root) is False


@pytest.mark.parametrize("bad", ["", "A" * 64, "0x" + "a" * 64, "zz" * 32])
def test_malformed_digest_or_root_is_rejected_without_raising(bad: str) -> None:
    tree = MerkleTree(D)
    proof = tree.proof(2)

    assert verify_proof(bad, proof, tree.root) is False
    assert verify_proof(D[2], proof, bad) is False


# -- proof metadata is claimed, not authenticated (review finding M1) ---------------------


def test_index_4_of_5_relabelled_as_index_1_of_2_proves_membership_only() -> None:
    """Both positions have the path shape [left]: the relabelled proof still folds to the
    five-leaf root, so it proves membership — and nothing about index or batch size."""
    tree = MerkleTree(D)
    genuine = tree.proof(4)
    relabelled = MerkleProof(leaf_index=1, leaf_count=2, steps=genuine.steps)

    assert _path_shape(1, 2) == _path_shape(4, 5)
    # Membership against the root alone: accepted.
    assert verify_proof(D[4], relabelled, tree.root) is True
    # With the anchored metadata enforced: rejected on either value.
    assert verify_proof(D[4], relabelled, tree.root, trusted_leaf_count=5) is False
    assert verify_proof(D[4], relabelled, tree.root, trusted_leaf_index=4) is False
    assert (
        verify_proof(D[4], relabelled, tree.root, trusted_leaf_index=4, trusted_leaf_count=5)
        is False
    )
    # The genuine proof passes the same enforcement.
    assert verify_proof(D[4], genuine, tree.root, trusted_leaf_index=4, trusted_leaf_count=5)


def test_index_2_of_5_relabelled_with_count_6_proves_membership_only() -> None:
    tree = MerkleTree(D)
    genuine = tree.proof(2)
    relabelled = MerkleProof(leaf_index=2, leaf_count=6, steps=genuine.steps)

    assert _path_shape(2, 6) == _path_shape(2, 5)
    assert verify_proof(D[2], relabelled, tree.root) is True
    assert verify_proof(D[2], relabelled, tree.root, trusted_leaf_count=5) is False
    assert verify_proof(D[2], genuine, tree.root, trusted_leaf_index=2, trusted_leaf_count=5)


@pytest.mark.parametrize("count", range(1, 18))
def test_with_trusted_metadata_each_proof_verifies_only_at_its_own_position(count: int) -> None:
    digests = [_raw_keccak(f"leaf-{i}".encode()) for i in range(count)]
    tree = MerkleTree(digests)

    for index, digest in enumerate(digests):
        proof = tree.proof(index)
        for claimed in range(count):
            assert verify_proof(
                digest, proof, tree.root, trusted_leaf_index=claimed, trusted_leaf_count=count
            ) is (claimed == index)


@pytest.mark.parametrize("bad", [True, "2", 2.0])
def test_a_non_integer_trusted_value_is_a_caller_error(bad: object) -> None:
    tree = MerkleTree(D)
    proof = tree.proof(2)

    with pytest.raises(TypeError):
        verify_proof(D[2], proof, tree.root, trusted_leaf_index=_any(bad))
    with pytest.raises(TypeError):
        verify_proof(D[2], proof, tree.root, trusted_leaf_count=_any(bad))


# -- runtime-invalid input never raises (review finding L1) -----------------------------


def _any(value: object) -> Any:
    """Defeat the type checker on purpose: these tests feed what untrusted input could."""
    return value


def _runtime_invalid_cases() -> list[tuple[str, Any, Any, Any]]:
    """(label, digest, proof, root) — every one must verify ``False`` without raising.

    Built on the genuine proof for index 1 of the five-leaf tree, whose sides are
    [left, right, right], so each case changes exactly one thing.
    """
    tree = MerkleTree(D)
    good = tree.proof(1)
    first, rest = good.steps[0], good.steps[1:]

    def proof_with(**changes: Any) -> MerkleProof:
        fields: dict[str, Any] = {
            "leaf_index": good.leaf_index,
            "leaf_count": good.leaf_count,
            "steps": good.steps,
            **changes,
        }
        return MerkleProof(**fields)

    def first_step(sibling: Any = first.sibling, side: Any = first.sibling_on_left) -> Any:
        return proof_with(steps=(ProofStep(sibling, side), *rest))

    root = tree.root
    return [
        ("digest None", None, good, root),
        ("digest bytes", bytes.fromhex(D[1]), good, root),
        ("root None", D[1], good, None),
        ("root bytes", D[1], good, bytes.fromhex(root)),
        ("proof None", D[1], None, root),
        ("proof not a MerkleProof", D[1], "proof", root),
        ("steps None", D[1], proof_with(steps=None), root),
        ("steps a string", D[1], proof_with(steps="steps"), root),
        ("step not a ProofStep", D[1], proof_with(steps=((first.sibling, True), *rest)), root),
        ("sibling None", D[1], first_step(sibling=None), root),
        ("sibling bytes", D[1], first_step(sibling=bytes.fromhex(first.sibling)), root),
        ("side int 1", D[1], first_step(side=1), root),
        ("side int 0", D[1], first_step(side=0), root),
        ("side string", D[1], first_step(side="True"), root),
        ("side None", D[1], first_step(side=None), root),
        ("index bool", D[1], proof_with(leaf_index=True), root),
        ("index string", D[1], proof_with(leaf_index="1"), root),
        ("index float", D[1], proof_with(leaf_index=1.0), root),
        ("index None", D[1], proof_with(leaf_index=None), root),
        ("count bool", D[1], proof_with(leaf_count=True), root),
        ("count string", D[1], proof_with(leaf_count="5"), root),
        ("count float", D[1], proof_with(leaf_count=5.0), root),
        ("count None", D[1], proof_with(leaf_count=None), root),
    ]


@pytest.mark.parametrize(
    ("label", "digest", "proof", "root"),
    _runtime_invalid_cases(),
    ids=[case[0] for case in _runtime_invalid_cases()],
)
def test_runtime_invalid_input_returns_false_without_raising(
    label: str, digest: Any, proof: Any, root: Any
) -> None:
    assert verify_proof(digest, proof, root) is False


def test_the_unaltered_baseline_of_the_invalid_cases_verifies() -> None:
    """Guards the cases above: each differs from a proof that is genuinely valid."""
    tree = MerkleTree(D)
    proof = tree.proof(1)

    assert [step.sibling_on_left for step in proof.steps] == [True, False, False]
    assert verify_proof(D[1], proof, tree.root) is True


# -- the v3 batch: eligibility and ordering -----------------------------------------------


def test_a_v3_batch_proves_every_event() -> None:
    events = [_event(seconds=i) for i in range(5)]
    batch = V3Batch(events)

    assert batch.root == MerkleTree([event.event_hash for event in events]).root
    for event in events:
        assert verify_proof(event.event_hash, batch.proof_for(event.id), batch.root)


def test_a_v3_batch_orders_canonically_whatever_the_input_order() -> None:
    events = [_event(seconds=i) for i in range(6)]
    shuffled = [events[i] for i in (3, 0, 5, 1, 4, 2)]

    batch = V3Batch(shuffled)

    assert [leaf.audit_log_id for leaf in batch.leaves] == [event.id for event in events]
    assert batch.root == V3Batch(events).root == V3Batch(reversed(events)).root


def test_events_at_the_same_instant_are_ordered_by_id() -> None:
    low = _event(event_id=UUID("00000000-0000-4000-8000-000000000001"))
    high = _event(event_id=UUID("ffffffff-ffff-4fff-bfff-ffffffffffff"))

    assert [leaf.audit_log_id for leaf in V3Batch([high, low]).leaves] == [low.id, high.id]


def test_naive_and_aware_timestamps_order_alike() -> None:
    """SQLite returns this column naive and Postgres aware; the order must not depend on it."""
    first, second = _event(seconds=0), _event(seconds=1)
    first.occurred_at = first.occurred_at.replace(tzinfo=None)
    first.event_hash = recompute_event_hash(first)

    assert [leaf.audit_log_id for leaf in V3Batch([second, first]).leaves] == [
        first.id,
        second.id,
    ]


@pytest.mark.parametrize("scheme", [HASH_SCHEME_V1, HASH_SCHEME_V2])
def test_v1_and_v2_events_are_refused(scheme: int) -> None:
    with pytest.raises(IneligibleEventError):
        V3Batch([_event(seconds=0), _event(scheme=scheme, seconds=1)])


def test_a_v2_event_relabelled_v3_is_refused() -> None:
    """A 64-hex SHA-256 digest with a v3 label: the label alone is not proof."""
    event = _event(scheme=HASH_SCHEME_V2)
    event.hash_version = HASH_SCHEME_V3

    with pytest.raises(IneligibleEventError):
        V3Batch([event])


def test_an_altered_v3_event_is_refused() -> None:
    event = _event()
    event.request_context = "edited"

    with pytest.raises(IneligibleEventError):
        V3Batch([event])


def test_an_unknown_version_is_refused() -> None:
    event = _event()
    event.hash_version = 4

    with pytest.raises(IneligibleEventError):
        V3Batch([event])


def test_the_refusal_names_the_event_and_nothing_else() -> None:
    event = _event(scheme=HASH_SCHEME_V2)

    with pytest.raises(IneligibleEventError) as raised:
        V3Batch([event])

    message = str(raised.value)
    assert str(event.id) in message
    assert str(event.patient_id) not in message
    assert event.event_hash not in message


def test_the_same_event_twice_is_refused() -> None:
    event = _event()

    with pytest.raises(DuplicateLeafError):
        V3Batch([event, event])


def test_an_empty_v3_batch_is_refused() -> None:
    with pytest.raises(EmptyBatchError):
        V3Batch([])


def test_a_proof_for_an_event_outside_the_batch_is_refused() -> None:
    batch = V3Batch([_event()])

    with pytest.raises(LeafIndexError):
        batch.proof_for(uuid4())


def test_an_event_without_an_id_is_refused() -> None:
    """``AuditLog.id`` is assigned its default only at flush; a hand-built row has none, and
    would otherwise hash ``"None"`` consistently and pass the recompute check."""
    event = _event()
    event.id = _any(None)
    event.event_hash = recompute_event_hash(event)

    with pytest.raises(IneligibleEventError):
        V3Batch([event])


def test_two_events_without_ids_are_refused_as_ineligible_not_duplicate() -> None:
    first, second = _event(seconds=0), _event(seconds=1)
    for event in (first, second):
        event.id = _any(None)
        event.event_hash = recompute_event_hash(event)

    with pytest.raises(IneligibleEventError):
        V3Batch([first, second])


def test_an_event_whose_id_is_not_a_uuid_is_refused_without_echoing_it() -> None:
    event = _event()
    event.id = _any(str(event.id))
    event.event_hash = recompute_event_hash(event)

    with pytest.raises(IneligibleEventError) as raised:
        V3Batch([event])

    assert str(event.id) not in str(raised.value)
