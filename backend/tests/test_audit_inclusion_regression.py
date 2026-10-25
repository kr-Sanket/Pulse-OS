"""Regression tests: VERIFIED requires Merkle inclusion on every verification surface.

Pins the two defects found in the 2026-10-25 audit:

1. The patient list and single-event verification reported VERIFIED for a batched v3 event
   without checking that its member digest is a leaf under the batch root. An attacker with
   database write access could edit an event, recompute its Keccak-256 digest, write that
   digest into both ``audit_logs.event_hash`` and ``audit_batch_members.digest``, and still
   see VERIFIED there — only the proof endpoint noticed.
2. The proof endpoint built its tree unguarded, so tampered membership rows (a duplicate or
   malformed digest) raised out of ``MerkleTree`` and became HTTP 500 instead of a verdict.
"""

import asyncio
import datetime as dt
from typing import Any
from uuid import UUID

from app.core.db import create_session_factory
from app.core.ratelimit import InMemoryRateLimiter
from app.modules.auth.domain import Role
from app.modules.auth.fake import FakeAuthProvider
from app.modules.consent.anchor_service import AuditAnchorService, IntegrityStatus
from app.modules.consent.anchoring import LocalChainAuditAnchor
from app.modules.consent.batch_service import AuditBatchService
from app.modules.consent.merkle import MerkleTree, verify_stored_inclusion
from app.modules.consent.models import (
    AuditAction,
    AuditAnchorEntry,
    AuditBatch,
    AuditBatchMember,
    AuditLog,
)
from app.modules.consent.repository import (
    AuditAnchorRepository,
    AuditBatchRepository,
    AuditLogRepository,
)
from app.modules.consent.service import HASH_SCHEME_V2, HASH_SCHEME_V3, recompute_event_hash
from app.modules.patients.directory import PatientDirectoryService
from app.modules.patients.repository import PatientRepository
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy import event as sqla_event
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.test_audit_api_v3 import SeededData, _seed_data, _token

DIGESTS = [f"{i:064x}" for i in range(1, 6)]


def _members(digests: list[str]) -> list[tuple[int, str]]:
    return list(enumerate(digests))


# -- verify_stored_inclusion: the shared rule ------------------------------------------


def test_stored_inclusion_valid_for_every_leaf() -> None:
    root = MerkleTree(DIGESTS).root
    for index, digest in enumerate(DIGESTS):
        result = verify_stored_inclusion(
            _members(DIGESTS), leaf_index=index, digest=digest, root=root, leaf_count=5
        )
        assert result.is_valid
        assert result.proof is not None


def test_stored_inclusion_rejects_wrong_root() -> None:
    other_root = MerkleTree(DIGESTS[:4]).root
    result = verify_stored_inclusion(
        _members(DIGESTS), leaf_index=0, digest=DIGESTS[0], root=other_root, leaf_count=5
    )
    assert not result.is_valid


def test_stored_inclusion_rejects_digest_not_at_index() -> None:
    root = MerkleTree(DIGESTS).root
    result = verify_stored_inclusion(
        _members(DIGESTS), leaf_index=0, digest=DIGESTS[1], root=root, leaf_count=5
    )
    assert not result.is_valid


def test_stored_inclusion_rejects_count_mismatch_and_gaps() -> None:
    root = MerkleTree(DIGESTS).root
    short = verify_stored_inclusion(
        _members(DIGESTS[:4]), leaf_index=0, digest=DIGESTS[0], root=root, leaf_count=5
    )
    gapped = verify_stored_inclusion(
        [(0, DIGESTS[0]), (1, DIGESTS[1]), (2, DIGESTS[2]), (3, DIGESTS[3]), (7, DIGESTS[4])],
        leaf_index=0,
        digest=DIGESTS[0],
        root=root,
        leaf_count=5,
    )
    assert not short.is_valid and short.proof is None
    assert not gapped.is_valid and gapped.proof is None


def test_stored_inclusion_never_raises_on_tampered_rows() -> None:
    root = MerkleTree(DIGESTS).root
    duplicate = [*DIGESTS[:4], DIGESTS[0]]
    malformed = [*DIGESTS[:4], "not-a-digest"]
    for rows in (duplicate, malformed):
        result = verify_stored_inclusion(
            _members(rows), leaf_index=0, digest=DIGESTS[0], root=root, leaf_count=5
        )
        assert not result.is_valid
        assert result.proof is None
    out_of_range = verify_stored_inclusion(
        _members(DIGESTS), leaf_index=9, digest=DIGESTS[0], root=root, leaf_count=5
    )
    assert not out_of_range.is_valid


# -- HTTP surfaces ---------------------------------------------------------------------


def _rewrite_event_and_member(engine: AsyncEngine, target_id: UUID) -> None:
    """The attack from defect 1: edit a row and keep its event and member digests in step."""

    async def run() -> None:
        factory = create_session_factory(engine)
        async with factory() as session, session.begin():
            row = await session.get(AuditLog, target_id)
            assert row is not None
            row.action = AuditAction.RECORD_DOWNLOADED
            row.event_hash = recompute_event_hash(row)
            member = (
                await session.execute(
                    select(AuditBatchMember).where(AuditBatchMember.audit_log_id == target_id)
                )
            ).scalar_one()
            member.digest = row.event_hash

    asyncio.run(run())


def _set_member_digest(engine: AsyncEngine, audit_log_id: UUID, digest: str) -> None:
    async def run() -> None:
        factory = create_session_factory(engine)
        async with factory() as session, session.begin():
            member = (
                await session.execute(
                    select(AuditBatchMember).where(AuditBatchMember.audit_log_id == audit_log_id)
                )
            ).scalar_one()
            member.digest = digest

    asyncio.run(run())


def _statuses(client: TestClient, token: str, seed: SeededData) -> dict[str, str]:
    response = client.get("/api/v1/audit-logs", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    return {item["id"]: item["integrity"]["status"] for item in response.json()["items"]}


def test_rewritten_event_and_member_is_not_verified_anywhere(
    client: TestClient,
    fake_auth: FakeAuthProvider,
    db_engine: AsyncEngine,
    sqlite_db: None,
) -> None:
    seed = asyncio.run(_seed_data(db_engine))
    target = seed.v3_events[1]
    _rewrite_event_and_member(db_engine, target.id)
    token = _token(fake_auth, seed.p1_user_id, seed.p1_firebase_uid, Role.PATIENT)
    headers = {"Authorization": f"Bearer {token}"}

    # The list: the rewritten event, and every sibling whose root no longer rebuilds.
    statuses = _statuses(client, token, seed)
    for event in seed.v3_events:
        assert statuses[str(event.id)] == "ANCHOR_ALTERED"

    single = client.get(f"/api/v1/audit-logs/{target.id}/verification", headers=headers)
    assert single.status_code == 200
    assert single.json()["integrity"]["status"] == "ANCHOR_ALTERED"

    proof = client.get(f"/api/v1/audit-logs/{target.id}/proof", headers=headers)
    assert proof.status_code == 200
    assert proof.json()["status"] == "ANCHOR_ALTERED"
    assert proof.json()["isProofValid"] is False

    # Events outside the batch are unaffected.
    assert statuses[str(seed.unbatched_v3.id)] == "NOT_ANCHORED"
    assert statuses[str(seed.v2_event.id)] == "VERIFIED"


def test_duplicate_member_digest_is_a_verdict_not_a_500(
    client: TestClient,
    fake_auth: FakeAuthProvider,
    db_engine: AsyncEngine,
    sqlite_db: None,
) -> None:
    seed = asyncio.run(_seed_data(db_engine))
    first, second = seed.v3_events[0], seed.v3_events[1]
    _set_member_digest(db_engine, second.id, first.event_hash)
    token = _token(fake_auth, seed.p1_user_id, seed.p1_firebase_uid, Role.PATIENT)
    headers = {"Authorization": f"Bearer {token}"}

    proof = client.get(f"/api/v1/audit-logs/{first.id}/proof", headers=headers)
    assert proof.status_code == 200, proof.text
    body = proof.json()
    assert body["status"] != "VERIFIED"
    assert body["isProofValid"] is False
    assert body["proof"] is None
    assert body["proofStepsCount"] == 0

    statuses = _statuses(client, token, seed)
    assert statuses[str(first.id)] == "ANCHOR_ALTERED"
    assert statuses[str(second.id)] in {"EVENT_ALTERED", "ANCHOR_ALTERED"}


def test_malformed_sibling_digest_is_a_verdict_not_a_500(
    client: TestClient,
    fake_auth: FakeAuthProvider,
    db_engine: AsyncEngine,
    sqlite_db: None,
) -> None:
    seed = asyncio.run(_seed_data(db_engine))
    target, sibling = seed.v3_events[0], seed.v3_events[2]
    _set_member_digest(db_engine, sibling.id, "zz" * 32)
    token = _token(fake_auth, seed.p1_user_id, seed.p1_firebase_uid, Role.PATIENT)
    headers = {"Authorization": f"Bearer {token}"}

    proof = client.get(f"/api/v1/audit-logs/{target.id}/proof", headers=headers)
    assert proof.status_code == 200, proof.text
    assert proof.json()["status"] == "ANCHOR_ALTERED"
    assert proof.json()["proof"] is None

    single = client.get(f"/api/v1/audit-logs/{target.id}/verification", headers=headers)
    assert single.json()["integrity"]["status"] == "ANCHOR_ALTERED"


def test_deleted_sibling_membership_breaks_the_batch(
    client: TestClient,
    fake_auth: FakeAuthProvider,
    db_engine: AsyncEngine,
    sqlite_db: None,
) -> None:
    seed = asyncio.run(_seed_data(db_engine))
    removed = seed.v3_events[2]

    async def run() -> None:
        factory = create_session_factory(db_engine)
        async with factory() as session, session.begin():
            await session.execute(
                delete(AuditBatchMember).where(AuditBatchMember.audit_log_id == removed.id)
            )

    asyncio.run(run())
    token = _token(fake_auth, seed.p1_user_id, seed.p1_firebase_uid, Role.PATIENT)
    statuses = _statuses(client, token, seed)

    # The remaining members no longer add up to the sealed leaf count.
    assert statuses[str(seed.v3_events[0].id)] == "ANCHOR_ALTERED"
    assert statuses[str(seed.v3_events[1].id)] == "ANCHOR_ALTERED"
    # With its membership row gone the event looks unsealed — never VERIFIED. Only
    # reconciliation can tell it was once sealed (documented limit of local verification).
    assert statuses[str(removed.id)] == "NOT_ANCHORED"


def test_untampered_batch_still_verifies_with_a_proof(
    client: TestClient,
    fake_auth: FakeAuthProvider,
    db_engine: AsyncEngine,
    sqlite_db: None,
) -> None:
    seed = asyncio.run(_seed_data(db_engine))
    token = _token(fake_auth, seed.p1_user_id, seed.p1_firebase_uid, Role.PATIENT)
    statuses = _statuses(client, token, seed)
    for event in seed.v3_events:
        assert statuses[str(event.id)] == "VERIFIED"
        proof = client.get(
            f"/api/v1/audit-logs/{event.id}/proof",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert proof.json()["status"] == "VERIFIED"
        assert proof.json()["proof"] is not None


def test_batch_verification_is_rate_limited_per_caller(
    client: TestClient,
    fake_auth: FakeAuthProvider,
    db_engine: AsyncEngine,
    sqlite_db: None,
    rate_limiter: InMemoryRateLimiter,
) -> None:
    seed = asyncio.run(_seed_data(db_engine))
    token = _token(fake_auth, seed.p1_user_id, seed.p1_firebase_uid, Role.PATIENT)
    headers = {"Authorization": f"Bearer {token}"}
    path = f"/api/v1/audit-batches/{seed.batch.batch_number}"
    limit = rate_limiter.limit_for("audit_batch_verify").limit
    for _ in range(limit):
        assert client.get(path, headers=headers).status_code == 200
    throttled = client.get(path, headers=headers)
    assert throttled.status_code == 429
    assert "Retry-After" in throttled.headers


# -- injected per-event anchors (2026-10-25 final review) ---------------------------------
#
# A per-event ``audit_anchors`` row is never written for v3 events, and the local anchor's
# reference is a deterministic function of the digest — anyone with database write access
# can forge a matching row. Before the fix, list and detail verification consulted that row
# first and reported VERIFIED for an edited v3 event while the proof endpoint disagreed.


def _forge_anchor(engine: AsyncEngine, event_id: UUID, *, hash_version: int) -> None:
    async def run() -> None:
        factory = create_session_factory(engine)
        async with factory() as session, session.begin():
            row = await session.get(AuditLog, event_id)
            assert row is not None
            receipt = await LocalChainAuditAnchor().submit(row.event_hash)
            session.add(
                AuditAnchorEntry(
                    audit_log_id=row.id,
                    digest=row.event_hash,
                    hash_version=hash_version,
                    network=receipt.network,
                    reference=receipt.reference,
                    anchored_at=receipt.anchored_at,
                )
            )

    asyncio.run(run())


def _edit_and_rehash(
    engine: AsyncEngine, event_id: UUID, *, hash_version: int | None = None
) -> None:
    async def run() -> None:
        factory = create_session_factory(engine)
        async with factory() as session, session.begin():
            row = await session.get(AuditLog, event_id)
            assert row is not None
            row.action = AuditAction.RECORD_DOWNLOADED
            if hash_version is not None:
                row.hash_version = hash_version
            row.event_hash = recompute_event_hash(row)

    asyncio.run(run())


def _delete_membership(engine: AsyncEngine, event_id: UUID) -> None:
    async def run() -> None:
        factory = create_session_factory(engine)
        async with factory() as session, session.begin():
            await session.execute(
                delete(AuditBatchMember).where(AuditBatchMember.audit_log_id == event_id)
            )

    asyncio.run(run())


def _three_surfaces(
    client: TestClient, token: str, event_id: UUID
) -> tuple[str, str, int, str | None]:
    headers = {"Authorization": f"Bearer {token}"}
    listed = {
        item["id"]: item["integrity"]["status"]
        for item in client.get("/api/v1/audit-logs", headers=headers).json()["items"]
    }[str(event_id)]
    single = client.get(f"/api/v1/audit-logs/{event_id}/verification", headers=headers)
    proof = client.get(f"/api/v1/audit-logs/{event_id}/proof", headers=headers)
    assert single.status_code == 200, single.text
    proof_status = proof.json()["status"] if proof.status_code == 200 else None
    return listed, single.json()["integrity"]["status"], proof.status_code, proof_status


def test_forged_anchor_on_edited_batched_v3_event_is_never_verified(
    client: TestClient,
    fake_auth: FakeAuthProvider,
    db_engine: AsyncEngine,
    sqlite_db: None,
) -> None:
    seed = asyncio.run(_seed_data(db_engine))
    target = seed.v3_events[0]
    _edit_and_rehash(db_engine, target.id)
    _forge_anchor(db_engine, target.id, hash_version=HASH_SCHEME_V3)
    token = _token(fake_auth, seed.p1_user_id, seed.p1_firebase_uid, Role.PATIENT)

    listed, single, proof_code, proof_status = _three_surfaces(client, token, target.id)

    # Batch evidence decides: the edited digest is not the sealed member digest.
    assert listed == single == proof_status == "EVENT_ALTERED"
    assert proof_code == 200


def test_forged_anchor_after_deleting_membership_is_never_verified(
    client: TestClient,
    fake_auth: FakeAuthProvider,
    db_engine: AsyncEngine,
    sqlite_db: None,
) -> None:
    seed = asyncio.run(_seed_data(db_engine))
    target = seed.v3_events[0]
    _delete_membership(db_engine, target.id)
    _edit_and_rehash(db_engine, target.id)
    _forge_anchor(db_engine, target.id, hash_version=HASH_SCHEME_V3)
    token = _token(fake_auth, seed.p1_user_id, seed.p1_firebase_uid, Role.PATIENT)

    listed, single, proof_code, _ = _three_surfaces(client, token, target.id)

    # A matching per-event anchor is not evidence for a v3 event: unsealed, never VERIFIED.
    assert listed == single == "NOT_ANCHORED"
    assert proof_code == 404
    # The removal is still visible on the batch it was taken from.
    statuses = _statuses(client, token, seed)
    assert statuses[str(seed.v3_events[1].id)] == "ANCHOR_ALTERED"


def test_batched_event_relabelled_v2_with_forged_v2_anchor_is_altered(
    client: TestClient,
    fake_auth: FakeAuthProvider,
    db_engine: AsyncEngine,
    sqlite_db: None,
) -> None:
    """Downgrade attempt: a sealed event relabelled v2 and rehashed under SHA-256, with a
    forged v2 anchor, must not escape to the per-event check — its batch still decides."""
    seed = asyncio.run(_seed_data(db_engine))
    target = seed.v3_events[1]
    _edit_and_rehash(db_engine, target.id, hash_version=HASH_SCHEME_V2)
    _forge_anchor(db_engine, target.id, hash_version=HASH_SCHEME_V2)
    token = _token(fake_auth, seed.p1_user_id, seed.p1_firebase_uid, Role.PATIENT)

    listed, single, _, proof_status = _three_surfaces(client, token, target.id)

    assert listed == single == proof_status == "EVENT_ALTERED"


def test_legacy_v2_per_event_anchor_still_verifies_and_still_detects_edits(
    client: TestClient,
    fake_auth: FakeAuthProvider,
    db_engine: AsyncEngine,
    sqlite_db: None,
) -> None:
    seed = asyncio.run(_seed_data(db_engine))
    token = _token(fake_auth, seed.p1_user_id, seed.p1_firebase_uid, Role.PATIENT)
    assert _statuses(client, token, seed)[str(seed.v2_event.id)] == "VERIFIED"

    async def edit_only() -> None:
        factory = create_session_factory(db_engine)
        async with factory() as session, session.begin():
            row = await session.get(AuditLog, seed.v2_event.id)
            assert row is not None
            row.action = AuditAction.RECORD_DOWNLOADED

    asyncio.run(edit_only())
    assert _statuses(client, token, seed)[str(seed.v2_event.id)] == "EVENT_ALTERED"


def test_orphaned_membership_is_anchor_altered_on_list_and_detail(
    client: TestClient,
    fake_auth: FakeAuthProvider,
    db_engine: AsyncEngine,
    sqlite_db: None,
) -> None:
    """A membership row whose batch row is gone: the event was sealed and the record of the
    sealing is damaged — ANCHOR_ALTERED, never NOT_ANCHORED or VERIFIED."""
    seed = asyncio.run(_seed_data(db_engine))

    async def drop_batch() -> None:
        # Simulates a deleted batch row. The schema's FK would refuse this, so the test turns
        # enforcement off on the driver connection (outside any transaction, where SQLite
        # honours the pragma), as direct tampering would, and back on afterwards.
        async with db_engine.connect() as connection:
            raw = await connection.get_raw_connection()
            driver = raw.driver_connection
            assert driver is not None
            await driver.execute("PRAGMA foreign_keys=OFF")
            try:
                await driver.execute("DELETE FROM audit_batches WHERE id = ?", (seed.batch.id.hex,))
                await driver.commit()
            finally:
                await driver.execute("PRAGMA foreign_keys=ON")

    asyncio.run(drop_batch())
    token = _token(fake_auth, seed.p1_user_id, seed.p1_firebase_uid, Role.PATIENT)
    target = seed.v3_events[0]
    headers = {"Authorization": f"Bearer {token}"}

    assert _statuses(client, token, seed)[str(target.id)] == "ANCHOR_ALTERED"
    single = client.get(f"/api/v1/audit-logs/{target.id}/verification", headers=headers)
    assert single.json()["integrity"]["status"] == "ANCHOR_ALTERED"


# -- multi-batch pages ------------------------------------------------------------------


def _seal_remaining(engine: AsyncEngine) -> AuditBatch:
    async def run() -> AuditBatch:
        factory = create_session_factory(engine)
        async with factory() as session, session.begin():
            service = AuditBatchService(
                batches=AuditBatchRepository(session),
                max_size=10,
                backlog_threshold=dt.timedelta(seconds=900),
            )
            batch = await service.seal_next_batch()
            assert batch is not None
            return batch

    return asyncio.run(run())


def test_multi_batch_page_is_three_queries_and_isolates_tampering(
    db_engine: AsyncEngine,
) -> None:
    seed = asyncio.run(_seed_data(db_engine))
    second = _seal_remaining(db_engine)  # seals seed.unbatched_v3 as batch #2
    assert second.batch_number == 2
    _set_member_digest(db_engine, seed.v3_events[2].id, "ab" * 32)  # tamper batch #1 only

    async def run() -> None:
        factory = create_session_factory(db_engine)
        async with factory() as session:
            service = AuditAnchorService(
                audit=AuditLogRepository(session),
                anchors=AuditAnchorRepository(session),
                anchor_provider=LocalChainAuditAnchor(),
                patients=PatientDirectoryService(PatientRepository(session)),
                batches=AuditBatchRepository(session),
            )
            rows = (await session.execute(select(AuditLog))).scalars().all()
            selects: list[str] = []

            def track(*args: Any) -> None:
                statement = args[2]
                if statement.lstrip().upper().startswith("SELECT"):
                    selects.append(statement)

            sqla_event.listen(db_engine.sync_engine, "after_cursor_execute", track)
            try:
                reports = await service.verify_many(rows)
            finally:
                sqla_event.remove(db_engine.sync_engine, "after_cursor_execute", track)

            assert len(selects) <= 3
            by_id = {key: report.status for key, report in reports.items()}
            for event in seed.v3_events:
                assert by_id[event.id] is not IntegrityStatus.VERIFIED
            assert by_id[seed.unbatched_v3.id] is IntegrityStatus.VERIFIED  # batch #2 intact
            assert by_id[seed.v2_event.id] is IntegrityStatus.VERIFIED

    asyncio.run(run())
