"""Audit domain, repository, hashing, and anchor unit tests."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.modules.audit.anchor import (
    AnchorReceipt,
    DbAuditAnchor,
    compute_canonical_hash,
    compute_canonical_json,
)
from app.modules.audit.errors import (
    AuditEventNotFoundError,
    AuditValidationError,
)
from app.modules.audit.models import AnchorStatus, AuditAction
from app.modules.audit.repository import AuditEventRepository
from app.modules.audit.service import AuditService
from app.modules.auth.accounts import UserAccountService
from app.modules.auth.domain import Role
from app.modules.auth.fake import FakeAuthProvider
from app.modules.auth.models import User
from app.modules.auth.repository import UserRepository
from app.modules.patients.models import Patient
from app.modules.patients.repository import PatientRepository
from app.modules.patients.service import PatientService
from sqlalchemy.ext.asyncio import AsyncSession

from tests.support import sqlite_session


def _make_audit_service(session: AsyncSession) -> AuditService:
    auth_provider = FakeAuthProvider()
    user_repo = UserRepository(session)
    accounts = UserAccountService(user_repo, auth_provider)

    patient_repo = PatientRepository(session)
    patients = PatientService(accounts=accounts, patients=patient_repo)

    audit_repo = AuditEventRepository(session)
    return AuditService(
        audit=audit_repo,
        accounts=accounts,
        patients=patients,
        anchor=DbAuditAnchor(),
    )


async def _setup_actor_and_patient(session: AsyncSession) -> tuple[User, User, Patient]:
    u_actor = await UserRepository(session).add(User(firebase_uid="fb-actor", role=Role.DOCTOR))
    u_pat = await UserRepository(session).add(User(firebase_uid="fb-pat", role=Role.PATIENT))
    patient = await PatientRepository(session).add(
        Patient(user_id=u_pat.id, health_id="PHI-IND-2026-7K3M99X", full_name="Asha Rao")
    )
    return u_actor, u_pat, patient


# --- Canonical Hashing & Determinism Tests ---


def test_canonical_json_and_hashing_determinism() -> None:
    actor_id = uuid4()
    patient_id = uuid4()
    target_id = uuid4()
    fixed_ts = datetime(2026, 8, 28, 12, 0, 0, tzinfo=UTC)

    json_1 = compute_canonical_json(
        actor_id=actor_id,
        actor_role=Role.DOCTOR,
        action=AuditAction.RECORD_VIEWED,
        patient_id=patient_id,
        target_id=target_id,
        target_type="RECORD",
        timestamp=fixed_ts,
        request_context={"ip": "127.0.0.1", "route": "/api/v1/records/123"},
    )

    json_2 = compute_canonical_json(
        actor_id=actor_id,
        actor_role=Role.DOCTOR,
        action=AuditAction.RECORD_VIEWED,
        patient_id=patient_id,
        target_id=target_id,
        target_type="RECORD",
        timestamp=fixed_ts,
        request_context={"route": "/api/v1/records/123", "ip": "127.0.0.1"},  # different dict order
    )

    # 1. Assert sorted keys guarantee byte-for-byte identical canonical representation
    assert json_1 == json_2
    assert '"action":"RECORD_VIEWED"' in json_1
    assert '"actor_role":"DOCTOR"' in json_1

    # 2. Assert hashes are identical
    hash_1 = compute_canonical_hash(
        actor_id=actor_id,
        actor_role=Role.DOCTOR,
        action=AuditAction.RECORD_VIEWED,
        patient_id=patient_id,
        target_id=target_id,
        target_type="RECORD",
        timestamp=fixed_ts,
        request_context={"ip": "127.0.0.1", "route": "/api/v1/records/123"},
    )
    hash_2 = compute_canonical_hash(
        actor_id=actor_id,
        actor_role=Role.DOCTOR,
        action=AuditAction.RECORD_VIEWED,
        patient_id=patient_id,
        target_id=target_id,
        target_type="RECORD",
        timestamp=fixed_ts,
        request_context={"route": "/api/v1/records/123", "ip": "127.0.0.1"},
    )
    assert hash_1 == hash_2
    assert len(hash_1) == 64


def test_canonical_hash_changes_when_fields_change() -> None:
    actor_id = uuid4()
    patient_id = uuid4()
    fixed_ts = datetime(2026, 8, 28, 12, 0, 0, tzinfo=UTC)

    base_hash = compute_canonical_hash(
        actor_id=actor_id,
        actor_role=Role.DOCTOR,
        action=AuditAction.CONSENT_APPROVED,
        patient_id=patient_id,
        target_id=None,
        target_type=None,
        timestamp=fixed_ts,
    )

    # Change action
    diff_action_hash = compute_canonical_hash(
        actor_id=actor_id,
        actor_role=Role.DOCTOR,
        action=AuditAction.CONSENT_REJECTED,
        patient_id=patient_id,
        target_id=None,
        target_type=None,
        timestamp=fixed_ts,
    )
    assert base_hash != diff_action_hash

    # Change timestamp
    diff_ts_hash = compute_canonical_hash(
        actor_id=actor_id,
        actor_role=Role.DOCTOR,
        action=AuditAction.CONSENT_APPROVED,
        patient_id=patient_id,
        target_id=None,
        target_type=None,
        timestamp=datetime(2026, 8, 28, 12, 0, 1, tzinfo=UTC),
    )
    assert base_hash != diff_ts_hash

    # Change actor
    diff_actor_hash = compute_canonical_hash(
        actor_id=uuid4(),
        actor_role=Role.DOCTOR,
        action=AuditAction.CONSENT_APPROVED,
        patient_id=patient_id,
        target_id=None,
        target_type=None,
        timestamp=fixed_ts,
    )
    assert base_hash != diff_actor_hash


# --- Service Lifecycle & Actions Tests ---


def test_record_all_documented_audit_actions() -> None:
    """Verify that all 8 authoritative audit actions are valid and persist correctly."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            u_actor, _, patient = await _setup_actor_and_patient(session)
            service = _make_audit_service(session)

            actions = [
                AuditAction.RECORD_UPLOADED,
                AuditAction.ACCESS_REQUESTED,
                AuditAction.CONSENT_APPROVED,
                AuditAction.CONSENT_REJECTED,
                AuditAction.CONSENT_REVOKED,
                AuditAction.RECORD_VIEWED,
                AuditAction.RECORD_DOWNLOADED,
                AuditAction.SUMMARY_GENERATED,
            ]

            for act in actions:
                event = await service.record_event(
                    actor_id=u_actor.id,
                    actor_role=Role.DOCTOR,
                    action=act,
                    patient_id=patient.id,
                    target_id=uuid4(),
                    target_type="TEST_TARGET",
                    request_context={"test": act.value},
                    auto_anchor=True,
                )
                assert event.id is not None
                assert event.action is act
                assert event.actor_id == u_actor.id
                assert event.patient_id == patient.id
                assert len(event.canonical_hash) == 64
                assert event.anchor_status is AnchorStatus.ANCHORED
                assert event.anchor_tx_hash is not None

            # Assert all 8 events are retrievable for the patient
            events = await service.list_events_for_patient(patient.id)
            assert len(events) == len(actions)

    asyncio.run(scenario())


def test_audit_validation_failures() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            u_actor, _, patient = await _setup_actor_and_patient(session)
            service = _make_audit_service(session)

            # 1. Non-existent actor
            with pytest.raises(AuditValidationError, match="Actor"):
                await service.record_event(
                    actor_id=uuid4(),
                    actor_role=Role.DOCTOR,
                    action=AuditAction.RECORD_VIEWED,
                    patient_id=patient.id,
                )

            # 2. Non-existent patient
            with pytest.raises(AuditValidationError, match="patient"):
                await service.record_event(
                    actor_id=u_actor.id,
                    actor_role=Role.DOCTOR,
                    action=AuditAction.RECORD_VIEWED,
                    patient_id=uuid4(),
                )

    asyncio.run(scenario())


# --- Append-Only Integrity & Tamper Verification Tests ---


def test_tamper_verification_and_integrity() -> None:
    """Tamper-evidence property (ADR-004, RC-2 experiment):
    recomputing hash from event attributes detects any unauthorized row modifications.
    """

    async def scenario() -> None:
        async with sqlite_session() as session:
            u_actor, _, patient = await _setup_actor_and_patient(session)
            service = _make_audit_service(session)

            event = await service.record_event(
                actor_id=u_actor.id,
                actor_role=Role.DOCTOR,
                action=AuditAction.RECORD_VIEWED,
                patient_id=patient.id,
                target_id=uuid4(),
                target_type="RECORD",
            )

            # 1. Genuine event passes verification
            assert await service.verify_event_integrity(event.id) is True

            # 2. Simulate row tampering (action changed from RECORD_VIEWED to SUMMARY_GENERATED)
            event.action = AuditAction.SUMMARY_GENERATED
            await session.flush()

            # Integrity check flags mismatch
            assert await service.verify_event_integrity(event.id) is False

            # Non-existent event lookup raises error
            with pytest.raises(AuditEventNotFoundError):
                await service.verify_event_integrity(uuid4())

    asyncio.run(scenario())


def test_repository_is_strictly_append_only() -> None:
    """Security property: AuditEventRepository does not expose mutation or deletion methods."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            repo = AuditEventRepository(session)
            assert not hasattr(repo, "delete")
            assert not hasattr(repo, "delete_by_id")
            assert not hasattr(repo, "update")
            assert not hasattr(repo, "remove")

    asyncio.run(scenario())


# --- AuditAnchor Interface Tests ---


def test_db_audit_anchor_behavior() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            u_actor, _, patient = await _setup_actor_and_patient(session)
            service = _make_audit_service(session)
            anchor = DbAuditAnchor()

            event = await service.record_event(
                actor_id=u_actor.id,
                actor_role=Role.DOCTOR,
                action=AuditAction.CONSENT_APPROVED,
                patient_id=patient.id,
                auto_anchor=False,
            )

            # Anchor event
            receipt = await anchor.anchor(event)
            assert isinstance(receipt, AnchorReceipt)
            assert receipt.status is AnchorStatus.ANCHORED
            assert receipt.canonical_hash == event.canonical_hash
            assert receipt.tx_hash == f"db:{event.canonical_hash[:16]}"

            # Verify receipt
            assert await anchor.verify(event, receipt) is True

            # Fake receipt with wrong hash fails verification
            fake_receipt = AnchorReceipt(
                event_id=event.id,
                canonical_hash="0000000000000000000000000000000000000000000000000000000000000000",
                tx_hash="fake",
                anchored_at=datetime.now(UTC),
                status=AnchorStatus.ANCHORED,
            )
            assert await anchor.verify(event, fake_receipt) is False

    asyncio.run(scenario())
