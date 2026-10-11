"""Audit-anchor adapter and service tests.

These tests pin the blockchain boundary without requiring a network:
- only bare hex digests (SHA-256 for v1/v2, Keccak-256 for v3) cross the adapter boundary;
- the local adapter is deterministic and network-scoped;
- anchoring is idempotent;
- verification detects event and anchor tampering;
- each audit row verifies under its own hash scheme, alongside rows of other schemes;
- patient verification remains scoped to the caller's own audit trail.
"""

import asyncio
import datetime as dt
import hashlib
from dataclasses import dataclass
from uuid import uuid4

import pytest
from app.modules.auth.domain import AuthenticatedUser, Role
from app.modules.auth.models import User
from app.modules.consent.anchor_service import (
    AuditAnchorService,
    IntegrityStatus,
)
from app.modules.consent.anchoring import (
    LOCAL_DEV_NETWORK,
    AnchorReceipt,
    InvalidDigestError,
    LocalChainAuditAnchor,
    require_digest,
)
from app.modules.consent.errors import (
    AuditEventNotFoundError,
    BatchAnchoredEventError,
    UnanchorableAuditEventError,
)
from app.modules.consent.models import AuditAction, AuditAnchorEntry, AuditLog
from app.modules.consent.repository import AuditAnchorRepository, AuditLogRepository
from app.modules.consent.service import (
    HASH_SCHEME_V1,
    HASH_SCHEME_V2,
    HASH_SCHEME_V3,
    recompute_event_hash,
)
from app.modules.patients.directory import PatientDirectoryService
from app.modules.patients.models import Patient
from app.modules.patients.repository import PatientRepository
from sqlalchemy.ext.asyncio import AsyncSession

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
        return receipt.network == self.network and receipt.reference == f"ref:{digest}"


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


async def _fixture(session: AsyncSession, scheme: int = HASH_SCHEME_V2) -> AuditFixture:
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
        hash_version=scheme,
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
                patients=PatientDirectoryService(PatientRepository(session)),
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
                patients=PatientDirectoryService(PatientRepository(session)),
            )

            result = await service.anchor_pending(limit=10)

            assert result.anchored == 0
            assert result.failed == 1
            assert result.remaining == 1

            assert (await fixture.anchors.get_by_audit_log_id(fixture.event.id)) is None

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
    from app.modules.consent.anchor_service import IntegrityReport, anchored_event_ids

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


# ---------------------------------------------------------------------------
# Hash schemes (ADR-019, ADR-023)
# ---------------------------------------------------------------------------

ALL_SCHEMES = [HASH_SCHEME_V1, HASH_SCHEME_V2, HASH_SCHEME_V3]


async def _add_event(fixture: AuditFixture, scheme: int, *, seconds: int) -> AuditLog:
    """One more event in the fixture patient's trail, hashed under ``scheme``."""
    event = AuditLog(
        id=uuid4(),
        actor_user_id=fixture.patient_user.id,
        actor_role=Role.PATIENT,
        action=AuditAction.RECORD_VIEWED,
        patient_id=fixture.patient.id,
        request_context=None,
        occurred_at=NOW + dt.timedelta(seconds=seconds),
        actor_hospital_id=None,
        hash_version=scheme,
        event_hash="",
    )
    event.event_hash = recompute_event_hash(event)
    fixture.session.add(event)  # type: ignore[attr-defined]
    await fixture.session.flush()  # type: ignore[attr-defined]
    return event


def test_local_anchor_reference_derivation_is_unchanged() -> None:
    """Pinned against the documented rule, so the keccak transition provably left the
    local adapter alone: it still derives references with SHA-256 over its own domain."""

    async def scenario() -> None:
        provider = LocalChainAuditAnchor(clock=FixedClock(NOW))
        receipt = await provider.submit(DIGEST)

        expected = hashlib.sha256(
            f"pulseos:audit-anchor:local-dev:v1:{DIGEST}".encode()
        ).hexdigest()
        assert receipt.reference == "0x" + expected

    asyncio.run(scenario())


@pytest.mark.parametrize("scheme", [HASH_SCHEME_V1, HASH_SCHEME_V2])
def test_a_historical_event_anchors_per_event_and_verifies(scheme: int) -> None:
    """v1/v2 keep the per-event workflow; v3 is batch-anchored (ADR-027 decision 7)."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            fixture = await _fixture(session, scheme)
            original = (fixture.event.hash_version, fixture.event.event_hash)
            require_digest(fixture.event.event_hash)

            outcome = await fixture.service.anchor_event(fixture.event)
            report = await fixture.service.verify(fixture.event)

            assert outcome.anchor.hash_version == scheme
            assert outcome.anchor.digest == fixture.event.event_hash
            assert report.status is IntegrityStatus.VERIFIED
            # Anchoring reads the row and never rewrites it.
            assert (fixture.event.hash_version, fixture.event.event_hash) == original

    asyncio.run(scenario())


def test_a_mixed_scheme_trail_anchors_only_historical_rows_per_event() -> None:
    """The sweep anchors v1 and v2 and never queues v3; each row verifies independently."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            fixture = await _fixture(session, HASH_SCHEME_V1)
            v2 = await _add_event(fixture, HASH_SCHEME_V2, seconds=1)
            v3 = await _add_event(fixture, HASH_SCHEME_V3, seconds=2)
            events = [fixture.event, v2, v3]

            result = await fixture.service.anchor_pending(limit=10)
            reports = await fixture.service.verify_many(events)

            assert (result.anchored, result.failed, result.remaining) == (2, 0, 0)
            assert {event.hash_version for event in events} == set(ALL_SCHEMES)
            assert reports[fixture.event.id].status is IntegrityStatus.VERIFIED
            assert reports[v2.id].status is IntegrityStatus.VERIFIED
            assert reports[v3.id].status is IntegrityStatus.NOT_ANCHORED
            assert await fixture.anchors.get_by_audit_log_id(v3.id) is None

    asyncio.run(scenario())


def test_a_v2_event_relabelled_v3_is_reported_as_event_altered() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            fixture = await _fixture(session, HASH_SCHEME_V2)
            await fixture.service.anchor_event(fixture.event)

            fixture.event.hash_version = HASH_SCHEME_V3
            await session.flush()

            report = await fixture.service.verify(fixture.event)

            assert report.status is IntegrityStatus.EVENT_ALTERED

    asyncio.run(scenario())


@pytest.mark.parametrize("scheme", [0, 4, 99])
def test_an_unknown_scheme_is_reported_as_event_altered_not_raised(scheme: int) -> None:
    """Never VERIFIED, and never an exception that would fail a whole audit page."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            # Built on v2: per-event anchoring is a v1/v2 workflow since ADR-027.
            fixture = await _fixture(session, HASH_SCHEME_V2)
            healthy = await _add_event(fixture, HASH_SCHEME_V2, seconds=1)
            await fixture.service.anchor_pending(limit=10)

            fixture.event.hash_version = scheme
            await session.flush()

            single = await fixture.service.verify(fixture.event)
            page = await fixture.service.verify_many([fixture.event, healthy])

            assert single.status is IntegrityStatus.EVENT_ALTERED
            assert page[fixture.event.id].status is IntegrityStatus.EVENT_ALTERED
            assert page[healthy.id].status is IntegrityStatus.VERIFIED

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# ADR-027 decision 7: v3 events leave the per-event workflow
# ---------------------------------------------------------------------------


def test_a_v3_event_is_refused_by_per_event_anchoring() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            fixture = await _fixture(session, HASH_SCHEME_V3)
            provider = RecordingAnchor()
            service = AuditAnchorService(
                audit=fixture.audit,
                anchors=fixture.anchors,
                anchor_provider=provider,
                patients=PatientDirectoryService(PatientRepository(session)),
            )

            with pytest.raises(BatchAnchoredEventError):
                await service.anchor_event(fixture.event)

            assert provider.submitted == []
            assert await fixture.anchors.get_by_audit_log_id(fixture.event.id) is None

    asyncio.run(scenario())


def test_the_sweep_never_queues_v3_events() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            fixture = await _fixture(session, HASH_SCHEME_V3)
            await _add_event(fixture, HASH_SCHEME_V3, seconds=1)

            result = await fixture.service.anchor_pending(limit=10)

            assert (result.anchored, result.failed, result.remaining) == (0, 0, 0)

    asyncio.run(scenario())


def test_an_existing_per_event_v3_anchor_stays_readable() -> None:
    """A per-event anchor written for a v3 event before batching (between M6.1 and M6.3) is
    historical evidence: it is never deleted or rewritten and still verifies as before."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            fixture = await _fixture(session, HASH_SCHEME_V3)
            receipt = await LocalChainAuditAnchor(clock=FixedClock(NOW)).submit(
                fixture.event.event_hash
            )
            await fixture.anchors.add(
                AuditAnchorEntry(
                    audit_log_id=fixture.event.id,
                    digest=fixture.event.event_hash,
                    hash_version=HASH_SCHEME_V3,
                    network=receipt.network,
                    reference=receipt.reference,
                    anchored_at=receipt.anchored_at,
                )
            )

            report = await fixture.service.verify(fixture.event)

            assert report.status is IntegrityStatus.VERIFIED

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Per-event anchoring refuses inconsistent events (ADR-027 decision 7)
# ---------------------------------------------------------------------------


def _recording_service(fixture: AuditFixture, provider: RecordingAnchor) -> AuditAnchorService:
    return AuditAnchorService(
        audit=fixture.audit,
        anchors=fixture.anchors,
        anchor_provider=provider,
        patients=PatientDirectoryService(PatientRepository(fixture.session)),  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    ("scheme", "tamper", "reason"),
    [
        (HASH_SCHEME_V2, "edit", "digest_mismatch"),
        (HASH_SCHEME_V1, "edit", "digest_mismatch"),
        (HASH_SCHEME_V3, "relabel-to-v2", "digest_mismatch"),
        (HASH_SCHEME_V2, "unsupported-version", "unsupported_hash_version"),
    ],
)
def test_per_event_anchoring_refuses_an_inconsistent_event(
    scheme: int, tamper: str, reason: str
) -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            fixture = await _fixture(session, scheme)
            if tamper == "edit":
                fixture.event.request_context = "edited after writing"
            elif tamper == "relabel-to-v2":
                fixture.event.hash_version = HASH_SCHEME_V2
            else:
                fixture.event.hash_version = 4
            await session.flush()
            provider = RecordingAnchor()

            with pytest.raises(UnanchorableAuditEventError) as raised:
                await _recording_service(fixture, provider).anchor_event(fixture.event)

            assert raised.value.reason == reason
            assert fixture.event.event_hash not in str(raised.value)
            assert provider.submitted == []  # refused before the adapter is called
            assert await fixture.anchors.get_by_audit_log_id(fixture.event.id) is None

    asyncio.run(scenario())


def test_the_sweep_counts_an_inconsistent_event_as_failed_and_continues() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            fixture = await _fixture(session, HASH_SCHEME_V2)
            good = await _add_event(fixture, HASH_SCHEME_V2, seconds=1)
            fixture.event.request_context = "edited after writing"
            await session.flush()

            result = await fixture.service.anchor_pending(limit=10)

            assert (result.anchored, result.failed, result.remaining) == (1, 1, 1)
            assert await fixture.anchors.get_by_audit_log_id(fixture.event.id) is None
            assert await fixture.anchors.get_by_audit_log_id(good.id) is not None

    asyncio.run(scenario())


def test_an_existing_anchor_is_returned_as_is_and_verification_judges_the_row() -> None:
    """The check guards *creating* anchors only; an anchor that already exists is
    historical evidence and the verdict path reports the altered row."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            fixture = await _fixture(session, HASH_SCHEME_V2)
            first = await fixture.service.anchor_event(fixture.event)
            fixture.event.request_context = "edited after anchoring"
            await session.flush()

            again = await fixture.service.anchor_event(fixture.event)
            report = await fixture.service.verify(fixture.event)

            assert (again.created, again.anchor.id) == (False, first.anchor.id)
            assert report.status is IntegrityStatus.EVENT_ALTERED

    asyncio.run(scenario())
