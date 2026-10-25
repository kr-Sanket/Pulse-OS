"""Integration and HTTP tests for the v3 Audit Integrity API (ADR-027).

Pins:
- V3 Merkle-batched audit records verify to VERIFIED with local-merkle-batch network
  and batch commitment reference.
- Unbatched v3 records report NOT_ANCHORED.
- Historical v1/v2 records continue to verify against audit_anchors.
- Event tampering after sealing reports EVENT_ALTERED.
- Batch commitment, root tampering, or invalid leaf index reports ANCHOR_ALTERED.
- The Merkle proof endpoint GET /api/v1/audit-logs/{id}/proof returns valid cryptographic
  proof paths and enforces patient ownership (404 for another patient's event).
- Invalid Merkle proofs never return VERIFIED on the proof endpoint (reports ANCHOR_ALTERED).
- The batch verification endpoint GET /api/v1/audit-batches/{batch_number} verifies sealed
  batches independently against the database with zero PHI and in bounded O(1) queries.
- Pagination does not cause N+1 database queries.
"""

import datetime as dt
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from app.core.db import create_session_factory
from app.modules.auth.domain import Role
from app.modules.auth.fake import FakeAuthProvider
from app.modules.auth.models import User
from app.modules.consent.anchor_service import (
    LOCAL_MERKLE_BATCH_NETWORK,
    AuditAnchorService,
    IntegrityStatus,
)
from app.modules.consent.anchoring import LocalChainAuditAnchor
from app.modules.consent.batch_service import AuditBatchService
from app.modules.consent.merkle import batch_commitment, rebuild_stored_batch
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
from app.modules.consent.service import (
    HASH_SCHEME_V2,
    HASH_SCHEME_V3,
    recompute_event_hash,
)
from app.modules.patients.directory import PatientDirectoryService
from app.modules.patients.models import Patient
from app.modules.patients.repository import PatientRepository
from fastapi.testclient import TestClient
from sqlalchemy import event as sqla_event
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

NOW = dt.datetime(2026, 10, 17, 12, 0, tzinfo=dt.UTC)
BASE = NOW - dt.timedelta(hours=1)


@dataclass(frozen=True)
class SeededData:
    p1_user_id: UUID
    p1_id: UUID
    p1_firebase_uid: str
    p2_user_id: UUID
    p2_id: UUID
    p2_firebase_uid: str
    batch: AuditBatch
    v3_events: list[AuditLog]
    unbatched_v3: AuditLog
    v2_event: AuditLog


async def _seed_data(engine: AsyncEngine) -> SeededData:
    """Seed test users, patients, events, and a sealed Merkle batch."""
    factory = create_session_factory(engine)
    async with factory() as session, session.begin():
        # Patient 1
        p1_user = User(id=uuid4(), firebase_uid=f"fb-p1-{uuid4()}", role=Role.PATIENT)
        session.add(p1_user)
        await session.flush()

        p1 = Patient(
            id=uuid4(),
            user_id=p1_user.id,
            health_id="PHI-IND-2026-P1TEST",
            full_name="Patient One Test",
        )
        session.add(p1)
        await session.flush()

        # Patient 2
        p2_user = User(id=uuid4(), firebase_uid=f"fb-p2-{uuid4()}", role=Role.PATIENT)
        session.add(p2_user)
        await session.flush()

        p2 = Patient(
            id=uuid4(),
            user_id=p2_user.id,
            health_id="PHI-IND-2026-P2TEST",
            full_name="Patient Two Test",
        )
        session.add(p2)
        await session.flush()

        # Create 3 v3 events for Patient 1
        v3_events: list[AuditLog] = []
        for i in range(3):
            ev = AuditLog(
                id=uuid4(),
                actor_user_id=p1_user.id,
                actor_role=Role.PATIENT,
                action=AuditAction.RECORD_VIEWED,
                patient_id=p1.id,
                request_context=None,
                occurred_at=BASE + dt.timedelta(seconds=i * 10),
                actor_hospital_id=None,
                hash_version=HASH_SCHEME_V3,
                event_hash="",
            )
            ev.event_hash = recompute_event_hash(ev)
            session.add(ev)
            v3_events.append(ev)
        await session.flush()

        # Create 1 historical v2 event for Patient 1 with per-event anchor
        v2_event = AuditLog(
            id=uuid4(),
            actor_user_id=p1_user.id,
            actor_role=Role.PATIENT,
            action=AuditAction.RECORD_VIEWED,
            patient_id=p1.id,
            request_context=None,
            occurred_at=BASE - dt.timedelta(seconds=100),
            actor_hospital_id=None,
            hash_version=HASH_SCHEME_V2,
            event_hash="",
        )
        v2_event.event_hash = recompute_event_hash(v2_event)
        session.add(v2_event)
        await session.flush()

        anchor_provider = LocalChainAuditAnchor()
        receipt = await anchor_provider.submit(v2_event.event_hash)
        anchor_entry = AuditAnchorEntry(
            id=uuid4(),
            audit_log_id=v2_event.id,
            digest=v2_event.event_hash,
            hash_version=HASH_SCHEME_V2,
            network=receipt.network,
            reference=receipt.reference,
            anchored_at=receipt.anchored_at,
        )
        session.add(anchor_entry)
        await session.flush()

        # Seal the 3 v3 events into Batch #1 using AuditBatchService
        batch_repo = AuditBatchRepository(session)
        batch_svc = AuditBatchService(
            batches=batch_repo,
            max_size=10,
            backlog_threshold=dt.timedelta(seconds=900),
            clock=lambda: NOW,
        )
        batch = await batch_svc.seal_next_batch()
        assert batch is not None
        assert batch.batch_number == 1
        assert batch.leaf_count == 3

        # Create 1 unbatched v3 event for Patient 1 (created after batch #1 is sealed)
        unbatched_v3 = AuditLog(
            id=uuid4(),
            actor_user_id=p1_user.id,
            actor_role=Role.PATIENT,
            action=AuditAction.RECORD_VIEWED,
            patient_id=p1.id,
            request_context=None,
            occurred_at=BASE + dt.timedelta(seconds=100),
            actor_hospital_id=None,
            hash_version=HASH_SCHEME_V3,
            event_hash="",
        )
        unbatched_v3.event_hash = recompute_event_hash(unbatched_v3)
        session.add(unbatched_v3)
        await session.flush()

        return SeededData(
            p1_user_id=p1_user.id,
            p1_id=p1.id,
            p1_firebase_uid=p1_user.firebase_uid,
            p2_user_id=p2_user.id,
            p2_id=p2.id,
            p2_firebase_uid=p2_user.firebase_uid,
            batch=batch,
            v3_events=v3_events,
            unbatched_v3=unbatched_v3,
            v2_event=v2_event,
        )


def _token(fake_auth: FakeAuthProvider, user_id: UUID, uid: str, role: Role) -> str:
    token = f"token-{uid}"
    fake_auth.register_user(token, user_id=user_id, firebase_uid=uid, role=role)
    return token


# -----------------------------------------------------------------------------
# 1. GET /api/v1/audit-logs: Patient audit listing
# -----------------------------------------------------------------------------


def test_audit_logs_listing_verifies_v3_batched_events(
    client: TestClient,
    fake_auth: FakeAuthProvider,
    db_engine: AsyncEngine,
    sqlite_db: None,
) -> None:
    import asyncio

    seed = asyncio.run(_seed_data(db_engine))
    token = _token(fake_auth, seed.p1_user_id, seed.p1_firebase_uid, Role.PATIENT)
    response = client.get("/api/v1/audit-logs", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    data = response.json()
    items = {item["id"]: item for item in data["items"]}

    # Batched v3 events show VERIFIED with local-merkle-batch network and commitment reference
    for ev in seed.v3_events:
        item = items[str(ev.id)]
        assert item["integrity"]["status"] == "VERIFIED"
        assert item["integrity"]["network"] == LOCAL_MERKLE_BATCH_NETWORK
        assert item["integrity"]["reference"] == f"0x{seed.batch.commitment}"
        assert item["integrity"]["anchoredAt"] is not None

    # Unbatched v3 event shows NOT_ANCHORED
    unbatched_item = items[str(seed.unbatched_v3.id)]
    assert unbatched_item["integrity"]["status"] == "NOT_ANCHORED"
    assert unbatched_item["integrity"]["network"] is None
    assert unbatched_item["integrity"]["reference"] is None
    assert unbatched_item["integrity"]["anchoredAt"] is None

    # Historical v2 event shows VERIFIED with individual chain anchor reference
    v2_item = items[str(seed.v2_event.id)]
    assert v2_item["integrity"]["status"] == "VERIFIED"
    assert v2_item["integrity"]["network"] is not None
    assert v2_item["integrity"]["network"] != LOCAL_MERKLE_BATCH_NETWORK
    assert v2_item["integrity"]["reference"] is not None
    assert v2_item["integrity"]["anchoredAt"] is not None


# -----------------------------------------------------------------------------
# 2. GET /api/v1/audit-logs/{id}/verification: Single event verification
# -----------------------------------------------------------------------------


def test_audit_event_verification_endpoint_v3_and_v2(
    client: TestClient,
    fake_auth: FakeAuthProvider,
    db_engine: AsyncEngine,
    sqlite_db: None,
) -> None:
    import asyncio

    seed = asyncio.run(_seed_data(db_engine))
    token_p1 = _token(fake_auth, seed.p1_user_id, seed.p1_firebase_uid, Role.PATIENT)
    token_p2 = _token(fake_auth, seed.p2_user_id, seed.p2_firebase_uid, Role.PATIENT)

    target_event = seed.v3_events[0]

    # Patient 1 verifies their own batched v3 event -> VERIFIED
    resp = client.get(
        f"/api/v1/audit-logs/{target_event.id}/verification",
        headers={"Authorization": f"Bearer {token_p1}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["auditLogId"] == str(target_event.id)
    assert body["integrity"]["status"] == "VERIFIED"
    assert body["integrity"]["network"] == LOCAL_MERKLE_BATCH_NETWORK
    assert body["integrity"]["reference"] == f"0x{seed.batch.commitment}"
    assert body["integrity"]["anchoredAt"] is not None

    # Historical v2 event verifies -> VERIFIED with historical anchor network
    resp_v2 = client.get(
        f"/api/v1/audit-logs/{seed.v2_event.id}/verification",
        headers={"Authorization": f"Bearer {token_p1}"},
    )
    assert resp_v2.status_code == 200
    assert resp_v2.json()["integrity"]["status"] == "VERIFIED"
    assert resp_v2.json()["integrity"]["network"] != LOCAL_MERKLE_BATCH_NETWORK

    # Unbatched event -> NOT_ANCHORED
    resp_unbatched = client.get(
        f"/api/v1/audit-logs/{seed.unbatched_v3.id}/verification",
        headers={"Authorization": f"Bearer {token_p1}"},
    )
    assert resp_unbatched.status_code == 200
    assert resp_unbatched.json()["integrity"]["status"] == "NOT_ANCHORED"

    # Patient 2 calling on Patient 1's event -> 404 (patient isolation)
    resp_other = client.get(
        f"/api/v1/audit-logs/{target_event.id}/verification",
        headers={"Authorization": f"Bearer {token_p2}"},
    )
    assert resp_other.status_code == 404

    # Nonexistent UUID -> 404
    resp_nonexistent = client.get(
        f"/api/v1/audit-logs/{uuid4()}/verification",
        headers={"Authorization": f"Bearer {token_p1}"},
    )
    assert resp_nonexistent.status_code == 404


def test_tampered_event_content_detected_in_verification(
    client: TestClient,
    fake_auth: FakeAuthProvider,
    db_engine: AsyncEngine,
    sqlite_db: None,
) -> None:
    import asyncio

    seed = asyncio.run(_seed_data(db_engine))
    target = seed.v3_events[1]

    # Tamper the event's action in the database
    async def _tamper() -> None:
        factory = create_session_factory(db_engine)
        async with factory() as session, session.begin():
            row = await session.get(AuditLog, target.id)
            assert row is not None
            row.action = AuditAction.RECORD_DOWNLOADED
            await session.flush()

    asyncio.run(_tamper())

    token = _token(fake_auth, seed.p1_user_id, seed.p1_firebase_uid, Role.PATIENT)
    resp = client.get(
        f"/api/v1/audit-logs/{target.id}/verification",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["integrity"]["status"] == "EVENT_ALTERED"


def test_tampered_anchor_commitment_detected_on_single_verification(
    client: TestClient,
    fake_auth: FakeAuthProvider,
    db_engine: AsyncEngine,
    sqlite_db: None,
) -> None:
    """Tampering batch commitment in DB causes single-event verification to report
    ANCHOR_ALTERED.
    """
    import asyncio

    seed = asyncio.run(_seed_data(db_engine))
    target = seed.v3_events[0]

    async def _tamper() -> None:
        factory = create_session_factory(db_engine)
        async with factory() as session, session.begin():
            b = await session.get(AuditBatch, seed.batch.id)
            assert b is not None
            b.commitment = "0" * 64
            await session.flush()

    asyncio.run(_tamper())

    token = _token(fake_auth, seed.p1_user_id, seed.p1_firebase_uid, Role.PATIENT)
    resp = client.get(
        f"/api/v1/audit-logs/{target.id}/verification",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["integrity"]["status"] == "ANCHOR_ALTERED"


def test_negative_and_out_of_range_leaf_indices_report_anchor_altered(
    client: TestClient,
    fake_auth: FakeAuthProvider,
    db_engine: AsyncEngine,
    sqlite_db: None,
) -> None:
    """Out-of-range leaf indices (< 0 or >= leaf_count) must report ANCHOR_ALTERED."""
    import asyncio

    seed = asyncio.run(_seed_data(db_engine))
    target = seed.v3_events[0]
    token = _token(fake_auth, seed.p1_user_id, seed.p1_firebase_uid, Role.PATIENT)

    # 1. Out of range (> leaf_count) tested via HTTP endpoint
    async def _set_leaf_index(val: int) -> None:
        factory = create_session_factory(db_engine)
        async with factory() as session, session.begin():
            res = await session.execute(
                select(AuditBatchMember).where(AuditBatchMember.audit_log_id == target.id)
            )
            m = res.scalar_one()
            m.leaf_index = val
            await session.flush()

    asyncio.run(_set_leaf_index(999))
    resp_over = client.get(
        f"/api/v1/audit-logs/{target.id}/verification",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_over.status_code == 200
    assert resp_over.json()["integrity"]["status"] == "ANCHOR_ALTERED"

    # 2. Negative leaf index (< 0) verified directly on _assess_batched
    # (database schema enforces ck_audit_batch_members_leaf_index_non_negative)
    async def _test_negative_service() -> None:
        factory = create_session_factory(db_engine)
        async with factory() as session, session.begin():
            audit_repo = AuditLogRepository(session)
            anchors_repo = AuditAnchorRepository(session)
            batches_repo = AuditBatchRepository(session)
            patients_svc = PatientDirectoryService(PatientRepository(session))
            service = AuditAnchorService(
                audit=audit_repo,
                anchors=anchors_repo,
                anchor_provider=LocalChainAuditAnchor(),
                patients=patients_svc,
                batches=batches_repo,
            )
            neg_member = AuditBatchMember(
                id=uuid4(),
                batch_id=seed.batch.id,
                audit_log_id=target.id,
                leaf_index=-1,
                digest=target.event_hash,
            )
            siblings = await batches_repo.list_members_for_batch(seed.batch.id)
            stored = rebuild_stored_batch(
                [(s.leaf_index, s.digest) for s in siblings],
                root=seed.batch.root,
                leaf_count=seed.batch.leaf_count,
            )
            rep = service._assess_batched(target, neg_member, seed.batch, stored)
            assert rep.status is IntegrityStatus.ANCHOR_ALTERED

    asyncio.run(_test_negative_service())


# -----------------------------------------------------------------------------
# 3. GET /api/v1/audit-logs/{id}/proof: Merkle Proof Endpoint
# -----------------------------------------------------------------------------


def test_audit_event_proof_endpoint(
    client: TestClient,
    fake_auth: FakeAuthProvider,
    db_engine: AsyncEngine,
    sqlite_db: None,
) -> None:
    import asyncio

    seed = asyncio.run(_seed_data(db_engine))
    token_p1 = _token(fake_auth, seed.p1_user_id, seed.p1_firebase_uid, Role.PATIENT)
    token_p2 = _token(fake_auth, seed.p2_user_id, seed.p2_firebase_uid, Role.PATIENT)
    target = seed.v3_events[0]

    # Patient 1 gets proof for sealed event
    resp = client.get(
        f"/api/v1/audit-logs/{target.id}/proof",
        headers={"Authorization": f"Bearer {token_p1}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["auditLogId"] == str(target.id)
    assert data["status"] == "VERIFIED"
    assert data["batchNumber"] == seed.batch.batch_number
    assert data["batchId"] == str(seed.batch.id)
    assert data["leafCount"] == 3
    assert data["root"] == seed.batch.root
    assert data["commitment"] == seed.batch.commitment
    assert data["isEventValid"] is True
    assert data["isProofValid"] is True
    assert "proof" in data
    assert "steps" in data["proof"]
    assert len(data["proof"]["steps"]) == data["proofStepsCount"]

    # Verify patient isolation: Patient 2 requesting Patient 1's proof -> 404
    resp_p2 = client.get(
        f"/api/v1/audit-logs/{target.id}/proof",
        headers={"Authorization": f"Bearer {token_p2}"},
    )
    assert resp_p2.status_code == 404

    # Unbatched event -> 404 (proof not found)
    resp_unbatched = client.get(
        f"/api/v1/audit-logs/{seed.unbatched_v3.id}/proof",
        headers={"Authorization": f"Bearer {token_p1}"},
    )
    assert resp_unbatched.status_code == 404
    assert "Merkle proof not found" in resp_unbatched.text

    # Historical v2 event -> 404 (proof not found, individual anchor only)
    resp_v2 = client.get(
        f"/api/v1/audit-logs/{seed.v2_event.id}/proof",
        headers={"Authorization": f"Bearer {token_p1}"},
    )
    assert resp_v2.status_code == 404

    # Unauthenticated -> 401
    resp_unauth = client.get(f"/api/v1/audit-logs/{target.id}/proof")
    assert resp_unauth.status_code == 401


def test_invalid_merkle_proof_never_returns_verified(
    client: TestClient,
    fake_auth: FakeAuthProvider,
    db_engine: AsyncEngine,
    sqlite_db: None,
) -> None:
    """When a Merkle proof fails verification against batch.root, /proof returns ANCHOR_ALTERED."""
    import asyncio

    seed = asyncio.run(_seed_data(db_engine))
    target = seed.v3_events[0]
    token = _token(fake_auth, seed.p1_user_id, seed.p1_firebase_uid, Role.PATIENT)

    # Tamper batch.root and recompute commitment so commitment is valid for the forged root,
    # but the proof recomputed from members will NOT match the forged root.
    forged_root = "a" * 64
    forged_commitment = batch_commitment(
        protocol_version=seed.batch.protocol_version,
        batch_number=seed.batch.batch_number,
        leaf_count=seed.batch.leaf_count,
        root=forged_root,
    )

    async def _tamper_root() -> None:
        factory = create_session_factory(db_engine)
        async with factory() as session, session.begin():
            b = await session.get(AuditBatch, seed.batch.id)
            assert b is not None
            b.root = forged_root
            b.commitment = forged_commitment
            await session.flush()

    asyncio.run(_tamper_root())

    resp = client.get(
        f"/api/v1/audit-logs/{target.id}/proof",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["isProofValid"] is False
    assert data["status"] == "ANCHOR_ALTERED"
    assert data["status"] != "VERIFIED"


# -----------------------------------------------------------------------------
# 4. GET /api/v1/audit-batches/{batch_number}: Batch verification
# -----------------------------------------------------------------------------


def test_audit_batch_verification_endpoint(
    client: TestClient,
    fake_auth: FakeAuthProvider,
    db_engine: AsyncEngine,
    sqlite_db: None,
) -> None:
    import asyncio

    seed = asyncio.run(_seed_data(db_engine))
    token = _token(fake_auth, seed.p1_user_id, seed.p1_firebase_uid, Role.PATIENT)

    # Valid batch #1
    resp = client.get("/api/v1/audit-batches/1", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["batchNumber"] == 1
    assert data["batchId"] == str(seed.batch.id)
    assert data["protocolVersion"] == 1
    assert data["hashVersion"] == 3
    assert data["leafCount"] == 3
    assert data["root"] == seed.batch.root
    assert data["commitment"] == seed.batch.commitment
    assert data["isValid"] is True
    assert data["status"] == "VALID"
    assert data["findings"] == []

    # Nonexistent batch #999 -> 404
    resp_404 = client.get("/api/v1/audit-batches/999", headers={"Authorization": f"Bearer {token}"})
    assert resp_404.status_code == 404

    # Invalid batch number 0 -> 422
    resp_422 = client.get("/api/v1/audit-batches/0", headers={"Authorization": f"Bearer {token}"})
    assert resp_422.status_code == 422

    # Unauthenticated -> 401
    resp_unauth = client.get("/api/v1/audit-batches/1")
    assert resp_unauth.status_code == 401


def test_tampered_batch_detected_in_batch_verification(
    client: TestClient,
    fake_auth: FakeAuthProvider,
    db_engine: AsyncEngine,
    sqlite_db: None,
) -> None:
    import asyncio

    seed = asyncio.run(_seed_data(db_engine))

    # Tamper the batch commitment in the database
    async def _tamper_batch() -> None:
        factory = create_session_factory(db_engine)
        async with factory() as session, session.begin():
            b = await session.get(AuditBatch, seed.batch.id)
            assert b is not None
            b.commitment = "f" * 64
            await session.flush()

    asyncio.run(_tamper_batch())

    token = _token(fake_auth, seed.p1_user_id, seed.p1_firebase_uid, Role.PATIENT)
    resp = client.get("/api/v1/audit-batches/1", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["isValid"] is False
    assert data["status"] == "TAMPERED"
    assert any(f["kind"] == "COMMITMENT_MISMATCH" for f in data["findings"])


# -----------------------------------------------------------------------------
# 5. Role gating on proof and batch verification endpoints
# -----------------------------------------------------------------------------


def test_role_gating_on_proof_and_batch_endpoints(
    client: TestClient,
    fake_auth: FakeAuthProvider,
    db_engine: AsyncEngine,
    sqlite_db: None,
) -> None:
    import asyncio

    seed = asyncio.run(_seed_data(db_engine))

    doc_uid = uuid4()
    doc_fb = f"fb-doc-{uuid4()}"
    admin_uid = uuid4()
    admin_fb = f"fb-admin-{uuid4()}"

    async def _insert_users() -> None:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        async_session = async_sessionmaker(db_engine, expire_on_commit=False)
        async with async_session() as session, session.begin():
            session.add_all(
                [
                    User(id=doc_uid, firebase_uid=doc_fb, role=Role.DOCTOR),
                    User(id=admin_uid, firebase_uid=admin_fb, role=Role.HOSPITAL_ADMIN),
                ]
            )

    asyncio.run(_insert_users())

    token_doc = _token(fake_auth, doc_uid, doc_fb, Role.DOCTOR)
    token_admin = _token(fake_auth, admin_uid, admin_fb, Role.HOSPITAL_ADMIN)
    target = seed.v3_events[0]

    # Non-patient (Doctor) calling proof endpoint -> 403 Forbidden
    resp_doc_proof = client.get(
        f"/api/v1/audit-logs/{target.id}/proof",
        headers={"Authorization": f"Bearer {token_doc}"},
    )
    assert resp_doc_proof.status_code == 403

    # Doctor calling batch verification -> 200 OK (all authenticated users can verify batches)
    resp_doc_batch = client.get(
        "/api/v1/audit-batches/1",
        headers={"Authorization": f"Bearer {token_doc}"},
    )
    assert resp_doc_batch.status_code == 200
    assert resp_doc_batch.json()["isValid"] is True

    # Hospital Admin calling batch verification -> 200 OK
    resp_admin_batch = client.get(
        "/api/v1/audit-batches/1",
        headers={"Authorization": f"Bearer {token_admin}"},
    )
    assert resp_admin_batch.status_code == 200
    assert resp_admin_batch.json()["isValid"] is True


# -----------------------------------------------------------------------------
# 6. Service-level test: mixed-scheme trail and bounded query counts
# -----------------------------------------------------------------------------


def test_audit_anchor_service_mixed_scheme_verifications(
    db_engine: AsyncEngine,
) -> None:
    """Verify that AuditAnchorService accurately assesses mixed-version events."""
    import asyncio

    seed = asyncio.run(_seed_data(db_engine))

    async def scenario() -> None:
        factory = create_session_factory(db_engine)
        async with factory() as session, session.begin():
            audit_repo = AuditLogRepository(session)
            anchors_repo = AuditAnchorRepository(session)
            batches_repo = AuditBatchRepository(session)
            patients_svc = PatientDirectoryService(PatientRepository(session))

            service = AuditAnchorService(
                audit=audit_repo,
                anchors=anchors_repo,
                anchor_provider=LocalChainAuditAnchor(),
                patients=patients_svc,
                batches=batches_repo,
            )

            # verify single v3 batched event
            rep_v3 = await service.verify(seed.v3_events[0])
            assert rep_v3.status is IntegrityStatus.VERIFIED
            assert rep_v3.network == LOCAL_MERKLE_BATCH_NETWORK
            assert rep_v3.reference == f"0x{seed.batch.commitment}"
            assert rep_v3.anchored_at is not None

            # verify single unbatched event
            rep_unbatched = await service.verify(seed.unbatched_v3)
            assert rep_unbatched.status is IntegrityStatus.NOT_ANCHORED
            assert rep_unbatched.network is None
            assert rep_unbatched.reference is None

            # verify historical v2 event
            rep_v2 = await service.verify(seed.v2_event)
            assert rep_v2.status is IntegrityStatus.VERIFIED
            assert rep_v2.network != LOCAL_MERKLE_BATCH_NETWORK

            # verify_many with all mixed events
            all_events = [*seed.v3_events, seed.unbatched_v3, seed.v2_event]
            reports = await service.verify_many(all_events)
            assert len(reports) == 5
            for ev in seed.v3_events:
                assert reports[ev.id].status is IntegrityStatus.VERIFIED
                assert reports[ev.id].network == LOCAL_MERKLE_BATCH_NETWORK
            assert reports[seed.unbatched_v3.id].status is IntegrityStatus.NOT_ANCHORED
            assert reports[seed.v2_event.id].status is IntegrityStatus.VERIFIED

    asyncio.run(scenario())


def test_bounded_queries_for_paginated_verification(
    db_engine: AsyncEngine,
) -> None:
    """verify_many executes at most 3 SQL statements across any page size (no N+1)."""
    import asyncio

    seed = asyncio.run(_seed_data(db_engine))

    async def scenario() -> None:
        factory = create_session_factory(db_engine)
        async with factory() as session, session.begin():
            audit_repo = AuditLogRepository(session)
            anchors_repo = AuditAnchorRepository(session)
            batches_repo = AuditBatchRepository(session)
            patients_svc = PatientDirectoryService(PatientRepository(session))

            service = AuditAnchorService(
                audit=audit_repo,
                anchors=anchors_repo,
                anchor_provider=LocalChainAuditAnchor(),
                patients=patients_svc,
                batches=batches_repo,
            )

            all_events = [*seed.v3_events, seed.unbatched_v3, seed.v2_event]

            # Measure queries executed during verify_many
            statements: list[str] = []

            def _track(
                conn: Any,
                cursor: Any,
                statement: str,
                params: Any,
                context: Any,
                executemany: bool,
            ) -> None:
                statements.append(statement)

            sqla_event.listen(db_engine.sync_engine, "after_cursor_execute", _track)
            try:
                reports = await service.verify_many(all_events)
            finally:
                sqla_event.remove(db_engine.sync_engine, "after_cursor_execute", _track)

            assert len(reports) == 5
            # Exactly 3 queries: audit_anchors IN, audit_batch_members (whole batches of the
            # page's events, for the inclusion check), audit_batches IN
            select_statements = [s for s in statements if s.strip().upper().startswith("SELECT")]
            assert len(select_statements) <= 3

    asyncio.run(scenario())


def test_bounded_queries_for_batch_verification(
    db_engine: AsyncEngine,
) -> None:
    """verify_batch executes in exactly 2 SQL statements (batch + bulk members/events join)."""
    import asyncio

    _ = asyncio.run(_seed_data(db_engine))

    async def scenario() -> None:
        factory = create_session_factory(db_engine)
        async with factory() as session, session.begin():
            batches_repo = AuditBatchRepository(session)
            batch_svc = AuditBatchService(
                batches=batches_repo,
                max_size=10,
                backlog_threshold=dt.timedelta(seconds=900),
                clock=lambda: NOW,
            )

            statements: list[str] = []

            def _track(
                conn: Any,
                cursor: Any,
                statement: str,
                params: Any,
                context: Any,
                executemany: bool,
            ) -> None:
                statements.append(statement)

            sqla_event.listen(db_engine.sync_engine, "after_cursor_execute", _track)
            try:
                res = await batch_svc.verify_batch(1)
            finally:
                sqla_event.remove(db_engine.sync_engine, "after_cursor_execute", _track)

            assert res is not None
            assert res.is_valid is True
            # Exactly 2 queries: get_batch_by_number + list_members_with_events_for_batch
            select_statements = [s for s in statements if s.strip().upper().startswith("SELECT")]
            assert len(select_statements) == 2

    asyncio.run(scenario())
