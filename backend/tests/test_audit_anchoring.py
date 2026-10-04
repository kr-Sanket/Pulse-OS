"""Audit-anchor adapter and service tests.

These tests pin the blockchain boundary without requiring a network:
- only bare SHA-256 digests cross the adapter boundary;
- the local adapter is deterministic and network-scoped;
- anchoring is idempotent;
- verification detects event and anchor tampering;
- patient verification remains scoped to the caller's own audit trail.
"""

import asyncio
import datetime as dt
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest

from app.modules.auth.domain import AuthenticatedUser, Role
from app.modules.auth.models import User
from app.modules.consent.anchor_service import (
    AuditAnchorService,
    IntegrityStatus,
)
from app.modules.consent.anchoring import (
    AnchorReceipt,
    InvalidDigestError,
    LocalChainAuditAnchor,
    LOCAL_DEV_NETWORK,
    require_digest,
)
from app.modules.consent.errors import AuditEventNotFoundError
from app.modules.consent.models import AuditAnchorEntry, AuditAction, AuditLog
from app.modules.consent.repository import AuditAnchorRepository, AuditLogRepository
from app.modules.consent.service import (
    HASH_SCHEME_V2,
    recompute_event_hash,
    sha256_event_hash,
)
from app.modules.patients.directory import PatientDirectoryService
from app.modules.patients.models import Patient
from app.modules.patients.repository import PatientRepository
from tests.support import sqlite_session


DIGEST = "a" * 64
OTHER_DIGEST = "b" * 64
NOW = dt.datetime(2026, 9, 1, 10, 0, tzinfo=dt.UTC)


class FixedClock:
    def __init__(self, now: dt.datetime) -> None:
        self.now = now

    def __call__(self) -> dt.datetime:
        return self.now


class RecordingAnchor:
    """Test provider proving that only the digest crosses the anchor boundary."""

    def __init__(self) -> None:
        self.network = "test-network"
        self.submitted: list[str] = []
        self.verified: list[tuple[str, AnchorReceipt]] = []

    async def submit(self, digest: str) -> AnchorReceipt:
        self.submitted.append(digest)
        return AnchorReceipt(
            network=self.network,
            reference=f"ref:{digest}",
            anchored_at=NOW,
        )

    async def verify(self, digest: str, receipt: AnchorReceipt) -> bool:
        self.verified.append((digest, receipt))
        return (
            receipt.network == self.network
            and receipt.reference == f"ref:{digest}"
        )


class FailingAnchor:
    network = "test-network"

    async def submit(self, digest: str) -> AnchorReceipt:
        raise OSError("anchor unavailable")

    async def verify(self, digest: str, receipt: AnchorReceipt) -> bool:
        return False


@dataclass
class AuditFixture:
    session: object
    audit: AuditLogRepository
    anchors: AuditAnchorRepository
    service: AuditAnchorService
    patient: Patient
    other_patient: Patient
    patient_user: User
    other_user: User
    event: AuditLog


async def _fixture(session) -> AuditFixture:
    patient_user = User(
        firebase_uid=f"fb-p-{uuid4()}",
        role=Role.PATIENT,
    )
    other_user = User(
        firebase_uid=f"fb-o-{uuid4()}",
        role=Role.PATIENT,
    )

    session.add_all([patient_user, other_user])
    await session.flush()

    patient = Patient(
        user_id=patient_user.id,
        health_id="PHI-IND-2026-1QE8DVR",
        full_name="Patient One",
    )
    other_patient = Patient(
        user_id=other_user.id,
        health_id="PHI-IND-2026-5WD2FD4",
        full_name="Patient Two",
    )

    session.add_all([patient, other_patient])
    await session.flush()

    event = AuditLog(
        actor_user_id=patient_user.id,
        actor_role=Role.PATIENT,
        action=AuditAction.RECORD_VIEWED,
        patient_id=patient.id,
        target_record_id=None,
        target_category_id=None,
        target_request_id=None,
        request_context=None,
        occurred_at=NOW,
        event_hash="",
        hash_version=HASH_SCHEME_V2,
        actor_hospital_id=None,
    )

    session.add(event)
    await session.flush()
    event.event_hash = recompute_event_hash(event)
    await session.flush()

    audit = AuditLogRepository(session)
    anchors = AuditAnchorRepository(session)
    provider = LocalChainAuditAnchor(
        clock=FixedClock(NOW),
    )

    service = AuditAnchorService(
        audit=audit,
        anchors=anchors,
        anchor_provider=provider,
        patients=PatientDirectoryService(PatientRepository(session)),
    )

    return AuditFixture(
        session=session,
        audit=audit,
        anchors=anchors,
        service=service,
        patient=patient,
        other_patient=other_patient,
        patient_user=patient_user,
        other_user=other_user,
        event=event,
    )


# ---------------------------------------------------------------------------
# Digest boundary
# ---------------------------------------------------------------------------


def test_require_digest_accepts_valid_lowercase_hex() -> None:
    assert require_digest(DIGEST) == DIGEST


@pytest.mark.parametrize(
    "value",
    [
        "",
        "a" * 63,
        "a" * 65,
        "A" * 64,
        "g" * 64,
        "0x" + "a" * 62,
    ],
)
def test_require_digest_rejects_non_canonical_values(value: str) -> None:
    with pytest.raises(InvalidDigestError):
        require_digest(value)


# ---------------------------------------------------------------------------
# Local adapter
# ---------------------------------------------------------------------------


def test_local_anchor_is_deterministic() -> None:
    async def scenario() -> None:
        provider = LocalChainAuditAnchor(clock=FixedClock(NOW))

        first = await provider.submit(DIGEST)
        second = await provider.submit(DIGEST)

        assert first.network == LOCAL_DEV_NETWORK
        assert first.reference == second.reference
        assert first.anchored_at == NOW
        assert second.anchored_at == NOW

    asyncio.run(scenario())


def test_local_anchor_changes_reference_for_different_digest() -> None:
    async def scenario() -> None:
        provider = LocalChainAuditAnchor(clock=FixedClock(NOW))

        first = await provider.submit(DIGEST)
        second = await provider.submit(OTHER_DIGEST)

        assert first.reference != second.reference

    asyncio.run(scenario())


def test_local_anchor_verifies_matching_receipt() -> None:
    async def scenario() -> None:
        provider = LocalChainAuditAnchor(clock=FixedClock(NOW))
        receipt = await provider.submit(DIGEST)

        assert await provider.verify(DIGEST, receipt) is True

    asyncio.run(scenario())


def test_local_anchor_rejects_wrong_network() -> None:
    async def scenario() -> None:
        provider = LocalChainAuditAnchor(clock=FixedClock(NOW))
        receipt = await provider.submit(DIGEST)

        foreign = AnchorReceipt(
            network="polygon-amoy",
            reference=receipt.reference,
            anchored_at=receipt.anchored_at,
        )

        assert await provider.verify(DIGEST, foreign) is False

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


def test_unanchored_event_reports_not_anchored() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            fixture = await _fixture(session)

            report = await fixture.service.verify(fixture.event)

            assert report.status is IntegrityStatus.NOT_ANCHORED
            assert report.anchor is None

    asyncio.run(scenario())


def test_anchor_event_creates_persistent_anchor() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            fixture = await _fixture(session)

            outcome = await fixture.service.anchor_event(fixture.event)

            assert outcome.created is True
            assert outcome.anchor.audit_log_id == fixture.event.id
            assert outcome.anchor.digest == fixture.event.event_hash
            assert outcome.anchor.network == LOCAL_DEV_NETWORK

            stored = await fixture.anchors.get_by_audit_log_id(fixture.event.id)

            assert stored is not None
            assert stored.id == outcome.anchor.id

    asyncio.run(scenario())


def test_anchor_event_is_idempotent() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            fixture = await _fixture(session)

            first = await fixture.service.anchor_event(fixture.event)
            second = await fixture.service.anchor_event(fixture.event)

            assert first.created is True
            assert second.created is False
            assert second.anchor.id == first.anchor.id

    asyncio.run(scenario())


def test_matching_anchor_verifies() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            fixture = await _fixture(session)

            await fixture.service.anchor_event(fixture.event)

            report = await fixture.service.verify(fixture.event)

            assert report.status is IntegrityStatus.VERIFIED
            assert report.anchor is not None
            assert report.anchor.digest == fixture.event.event_hash

    asyncio.run(scenario())


def test_modified_event_is_reported_as_event_altered() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            fixture = await _fixture(session)

            await fixture.service.anchor_event(fixture.event)

            # Mutate a field covered by the canonical audit hash.
            fixture.event.request_context = None
            fixture.event.occurred_at = NOW + dt.timedelta(seconds=1)
            await session.flush()

            report = await fixture.service.verify(fixture.event)

            assert report.status is IntegrityStatus.EVENT_ALTERED

    asyncio.run(scenario())


def test_modified_anchor_reference_is_reported_as_anchor_altered() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            fixture = await _fixture(session)

            await fixture.service.anchor_event(fixture.event)

            anchor = await fixture.anchors.get_by_audit_log_id(fixture.event.id)
            assert anchor is not None

            anchor.reference = "0x" + "0" * 64
            await session.flush()

            report = await fixture.service.verify(fixture.event)

            assert report.status is IntegrityStatus.ANCHOR_ALTERED

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Boundary / provider behaviour
# ---------------------------------------------------------------------------


def test_anchor_service_sends_only_event_digest_to_provider() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            fixture = await _fixture(session)
            provider = RecordingAnchor()

            service = AuditAnchorService(
                audit=fixture.audit,
                anchors=fixture.anchors,
                anchor_provider=provider,
                patients=PatientDirectoryService(
                    PatientRepository(session)
                ),
            )

            await service.anchor_event(fixture.event)

            assert provider.submitted == [fixture.event.event_hash]

    asyncio.run(scenario())


def test_anchor_pending_counts_provider_failure_and_leaves_event_unanchored() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            fixture = await _fixture(session)

            service = AuditAnchorService(
                audit=fixture.audit,
                anchors=fixture.anchors,
                anchor_provider=FailingAnchor(),
                patients=PatientDirectoryService(
                    PatientRepository(session)
                ),
            )

            result = await service.anchor_pending(limit=10)

            assert result.anchored == 0
            assert result.failed == 1
            assert result.remaining == 1

            assert (
                await fixture.anchors.get_by_audit_log_id(fixture.event.id)
            ) is None

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Patient scoping
# ---------------------------------------------------------------------------


def test_patient_can_verify_own_audit_event() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            fixture = await _fixture(session)

            await fixture.service.anchor_event(fixture.event)

            caller = AuthenticatedUser(
                user_id=fixture.patient_user.id,
                firebase_uid=fixture.patient_user.firebase_uid,
                role=Role.PATIENT,
            )

            report = await fixture.service.verify_for_caller(
                caller,
                fixture.event.id,
            )

            assert report.status is IntegrityStatus.VERIFIED

    asyncio.run(scenario())


def test_patient_cannot_verify_another_patients_event() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            fixture = await _fixture(session)

            await fixture.service.anchor_event(fixture.event)

            caller = AuthenticatedUser(
                user_id=fixture.other_user.id,
                firebase_uid=fixture.other_user.firebase_uid,
                role=Role.PATIENT,
            )

            with pytest.raises(AuditEventNotFoundError):
                await fixture.service.verify_for_caller(
                    caller,
                    fixture.event.id,
                )

    asyncio.run(scenario())


def test_anchored_event_ids_returns_only_anchored_reports() -> None:
    from app.modules.consent.anchor_service import anchored_event_ids, IntegrityReport

    first = uuid4()
    second = uuid4()

    reports = [
        IntegrityReport(
            audit_log_id=first,
            status=IntegrityStatus.VERIFIED,
            anchor=None,
        ),
        IntegrityReport(
            audit_log_id=second,
            status=IntegrityStatus.VERIFIED,
            anchor=AuditAnchorEntry(
                audit_log_id=second,
                digest=DIGEST,
                hash_version=HASH_SCHEME_V2,
                network=LOCAL_DEV_NETWORK,
                reference="0x" + "1" * 64,
                anchored_at=NOW,
            ),
        ),
    ]

    assert anchored_event_ids(reports) == {second}