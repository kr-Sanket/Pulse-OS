"""ConsentService tests: the request → decision → grant → revocation lifecycle and the
enforcement choke point.

The M3 invariants live here: only the target patient decides, a decision is permanent, a
grant is what enforcement reads, revocation and suspension both cut access immediately, and
**every** one of those events appends to the audit trail in the same transaction.
"""

import asyncio
import datetime as dt
import hashlib
from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest
from app.modules.auth.domain import AuthenticatedUser, Role
from app.modules.auth.models import User
from app.modules.consent.dependencies import RecordsStaffDirectory
from app.modules.consent.errors import (
    AccessDeniedError,
    ClinicianNotActiveError,
    ClinicianProfileNotFoundError,
    EmptyCategorySelectionError,
    GrantNotFoundError,
    PatientProfileNotFoundError,
    RequestNotDecidableError,
    RequestNotFoundError,
    UnknownPatientError,
    UnrequestedCategoryError,
)
from app.modules.consent.models import (
    AuditAction,
    AuditLog,
    ConsentDecisionStatus,
    ConsentRequest,
    ConsentRequestStatus,
)
from app.modules.consent.repository import (
    AuditLogRepository,
    ConsentDecisionRepository,
    ConsentGrantRepository,
    ConsentRequestCategoryRepository,
    ConsentRequestRepository,
)
from app.modules.notifications.models import Notification, NotificationEventType
from app.modules.notifications.repository import NotificationRepository
from app.modules.consent.service import (
    CURRENT_HASH_SCHEME,
    HASH_SCHEME_V1,
    HASH_SCHEME_V2,
    HASH_SCHEME_V3,
    ConsentGrantState,
    ConsentService,
    UnsupportedHashSchemeError,
    as_utc,
    canonical_event_payload,
    event_hasher_for,
    keccak256_event_hash,
    recompute_event_hash,
    sha256_event_hash,
)
from app.modules.patients.directory import PatientDirectoryService
from app.modules.patients.models import Patient
from app.modules.patients.repository import PatientRepository
from app.modules.records.directory import staff_directory
from app.modules.records.models import (
    Doctor,
    DoctorStatus,
    Hospital,
    HospitalVerificationStatus,
    MedicalRecord,
    RecordCategory,
    RecordOrigin,
)
from app.shared.pagination import CursorKey, decode_cursor
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.support import FakeClinicianDirectory, sqlite_session

HEALTH_ID = "PHI-IND-2026-1QE8DVR"
OTHER_HEALTH_ID = "PHI-IND-2026-5WD2FD4"
START = dt.datetime(2026, 9, 1, 10, 0, tzinfo=dt.UTC)


class Clock:
    """A clock the tests move, so expiry is deterministic rather than slept for."""

    def __init__(self, now: dt.datetime) -> None:
        self.now = now

    def __call__(self) -> dt.datetime:
        return self.now

    def advance(self, delta: dt.timedelta) -> None:
        self.now += delta


@dataclass
class Harness:
    session: AsyncSession
    service: ConsentService
    audit: AuditLogRepository
    grants: ConsentGrantRepository
    clinicians: FakeClinicianDirectory
    clock: Clock
    doctor: AuthenticatedUser
    patient: AuthenticatedUser
    other_patient: AuthenticatedUser
    patient_id: UUID
    doctor_id: UUID
    record_id: UUID
    categories: dict[str, UUID] = field(default_factory=dict)
    notifications: NotificationRepository = field(default=None)  # type: ignore

    async def actions(self) -> list[str]:
        """The audited actions for this patient, sorted.

        Deliberately not in trail order: these tests freeze the clock, so every event
        shares one ``occurred_at`` and the keyset tiebreaker is a random UUID — ordering
        among *simultaneous* events is unspecified by design. Ordering by event time is
        covered deterministically in test_consent_repositories.py, where the timestamps
        differ.
        """
        rows = await self.audit.list_page_by_patient(self.patient_id, after=None, limit=99)
        return sorted(row.action.value for row in rows)


async def _harness(session: AsyncSession) -> Harness:
    doctor_user = User(firebase_uid=f"fb-d-{uuid4()}", role=Role.DOCTOR)
    patient_user = User(firebase_uid=f"fb-p-{uuid4()}", role=Role.PATIENT)
    other_user = User(firebase_uid=f"fb-o-{uuid4()}", role=Role.PATIENT)
    session.add_all([doctor_user, patient_user, other_user])
    hospital = Hospital(
        hid="HID-0001", name="TMH", verification_status=HospitalVerificationStatus.VERIFIED
    )
    session.add(hospital)
    await session.flush()
    doctor = Doctor(
        user_id=doctor_user.id,
        hospital_id=hospital.id,
        full_name="Dr Verma",
        registration_number="R1",
        status=DoctorStatus.ACTIVE,
    )
    patient = Patient(user_id=patient_user.id, health_id=HEALTH_ID, full_name="Aarav")
    other = Patient(user_id=other_user.id, health_id=OTHER_HEALTH_ID, full_name="Meera")
    categories = {
        code: RecordCategory(code=code, display_name=code) for code in ("CBC", "MRI", "XRAY")
    }
    session.add_all([doctor, patient, other, *categories.values()])
    await session.flush()
    record = MedicalRecord(
        patient_id=patient.id,
        category_id=categories["CBC"].id,
        origin=RecordOrigin.HOSPITAL_UPLOAD,
        uploaded_by_hospital_id=hospital.id,
        date_of_service=dt.date(2026, 3, 1),
        original_filename="cbc.pdf",
        content_type="application/pdf",
        size_bytes=10,
        s3_key=f"records/{patient.id}/{uuid4()}",
    )
    session.add(record)
    await session.flush()

    clinicians = FakeClinicianDirectory()
    clinicians.register(doctor_user.id, doctor_id=doctor.id, hospital_id=hospital.id)
    clock = Clock(START)
    notifications = NotificationRepository(session)
    return Harness(
        session=session,
        service=ConsentService(
            requests=ConsentRequestRepository(session),
            request_categories=ConsentRequestCategoryRepository(session),
            decisions=ConsentDecisionRepository(session),
            grants=ConsentGrantRepository(session),
            audit=AuditLogRepository(session),
            patients=PatientDirectoryService(PatientRepository(session)),
            clinicians=clinicians,
            # The real adapter, against the same SQLite session: the projection's joins
            # are worth exercising here rather than faking away.
            staff=RecordsStaffDirectory(staff_directory(session)),
            notifications=notifications,
            clock=clock,
        ),
        audit=AuditLogRepository(session),
        grants=ConsentGrantRepository(session),
        clinicians=clinicians,
        clock=clock,
        doctor=AuthenticatedUser(
            user_id=doctor_user.id, firebase_uid=doctor_user.firebase_uid, role=Role.DOCTOR
        ),
        patient=AuthenticatedUser(
            user_id=patient_user.id, firebase_uid=patient_user.firebase_uid, role=Role.PATIENT
        ),
        other_patient=AuthenticatedUser(
            user_id=other_user.id, firebase_uid=other_user.firebase_uid, role=Role.PATIENT
        ),
        patient_id=patient.id,
        doctor_id=doctor.id,
        record_id=record.id,
        categories={code: category.id for code, category in categories.items()},
        notifications=notifications,
    )


async def _request(h: Harness, *codes: str) -> UUID:
    view = await h.service.create_request(
        h.doctor,
        patient_health_id=HEALTH_ID,
        category_ids=[h.categories[code] for code in codes],
        purpose="follow-up",
    )
    return view.request.id


# -- creating requests -----------------------------------------------------------------


def test_create_request_records_the_ask_and_audits_it() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            view = await h.service.create_request(
                h.doctor,
                patient_health_id=f"  {HEALTH_ID.lower()} ",  # desk-typed input tolerated
                category_ids=[h.categories["CBC"], h.categories["MRI"]],
                purpose="follow-up",
            )
            assert view.request.status is ConsentRequestStatus.PENDING
            assert view.request.patient_id == h.patient_id
            assert view.request.requester_doctor_id == h.doctor_id
            assert view.request.expires_at == START + dt.timedelta(days=7)
            assert set(view.requested_category_ids) == {h.categories["CBC"], h.categories["MRI"]}
            assert await h.actions() == ["ACCESS_REQUESTED"]

    asyncio.run(scenario())


def test_duplicate_categories_are_collapsed_not_rejected() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            view = await h.service.create_request(
                h.doctor,
                patient_health_id=HEALTH_ID,
                category_ids=[h.categories["CBC"], h.categories["CBC"], h.categories["MRI"]],
                purpose="p",
            )
            assert len(view.requested_category_ids) == 2

    asyncio.run(scenario())


def test_create_request_rejects_an_empty_selection_and_an_unknown_patient() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            with pytest.raises(EmptyCategorySelectionError):
                await h.service.create_request(
                    h.doctor, patient_health_id=HEALTH_ID, category_ids=[], purpose="p"
                )
            with pytest.raises(UnknownPatientError):
                await h.service.create_request(
                    h.doctor,
                    patient_health_id="PHI-IND-2026-ZZZZZZZ",
                    category_ids=[h.categories["CBC"]],
                    purpose="p",
                )
            assert await h.actions() == []  # nothing refused is ever audited as done

    asyncio.run(scenario())


def test_only_an_active_clinician_with_a_profile_may_ask() -> None:
    """ADR-015: a non-ACTIVE clinician fails the relationship layer for every capability."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            h.clinicians.suspend(h.doctor.user_id)
            with pytest.raises(ClinicianNotActiveError):
                await _request(h, "CBC")

            stranger = AuthenticatedUser(user_id=uuid4(), firebase_uid="fb-x", role=Role.DOCTOR)
            with pytest.raises(ClinicianProfileNotFoundError):
                await h.service.create_request(
                    stranger,
                    patient_health_id=HEALTH_ID,
                    category_ids=[h.categories["CBC"]],
                    purpose="p",
                )

    asyncio.run(scenario())


# -- listings --------------------------------------------------------------------------


def test_inbox_and_sent_listings_are_scoped_to_the_caller() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            request_id = await _request(h, "CBC", "MRI")

            inbox = await h.service.list_inbox(h.patient, after=None, limit=10)
            assert [item.request.id for item in inbox.items] == [request_id]
            assert len(inbox.items[0].requested_category_ids) == 2

            # Another patient's inbox never shows it.
            assert (await h.service.list_inbox(h.other_patient, after=None, limit=10)).items == []

            sent = await h.service.list_sent_requests(h.doctor, after=None, limit=10)
            assert [item.request.id for item in sent.items] == [request_id]

    asyncio.run(scenario())


def test_listings_require_the_caller_to_have_a_profile() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            ghost = AuthenticatedUser(user_id=uuid4(), firebase_uid="fb-g", role=Role.PATIENT)
            with pytest.raises(PatientProfileNotFoundError):
                await h.service.list_inbox(ghost, after=None, limit=10)

    asyncio.run(scenario())


def test_the_sent_listing_names_the_patient_each_request_is_about() -> None:
    """A clinician cannot tell one patient's request from another's without this; the
    inbox needs no such field, because every row there is about the reader."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            await _request(h, "CBC")

            sent = await h.service.list_sent_requests(h.doctor, after=None, limit=10)
            inbox = await h.service.list_inbox(h.patient, after=None, limit=10)

            assert sent.items[0].patient_health_id == HEALTH_ID
            # Unchanged: the inbox projection carries no subject.
            assert inbox.items[0].patient_health_id is None

    asyncio.run(scenario())


def test_creating_a_request_carries_no_subject_projection() -> None:
    """The write path answers the requester, who just supplied the Health ID."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            view = await h.service.create_request(
                h.doctor,
                patient_health_id=HEALTH_ID,
                category_ids=[h.categories["CBC"]],
                purpose="follow-up",
            )

            assert view.patient_health_id is None

    asyncio.run(scenario())


def test_a_suspended_clinician_may_still_read_their_own_sent_requests() -> None:
    """Seeing what you asked for is not a clinical capability."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            await _request(h, "CBC")
            h.clinicians.suspend(h.doctor.user_id)
            sent = await h.service.list_sent_requests(h.doctor, after=None, limit=10)
            assert len(sent.items) == 1

    asyncio.run(scenario())


def test_inbox_pagination_walks_every_request_without_overlap() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            created = {await _request(h, "CBC") for _ in range(5)}
            seen: set[UUID] = set()
            after: CursorKey | None = None
            pages = 0
            while True:
                page = await h.service.list_inbox(h.patient, after=after, limit=2)
                seen.update(item.request.id for item in page.items)
                pages += 1
                if page.next_cursor is None:
                    break
                after = decode_cursor(page.next_cursor)
            assert seen == created
            assert pages == 3

    asyncio.run(scenario())


# -- decisions -------------------------------------------------------------------------


def test_partial_approval_leaves_the_request_open() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            request_id = await _request(h, "CBC", "MRI")
            outcome = await h.service.approve_categories(
                h.patient, request_id, [h.categories["CBC"]]
            )
            assert outcome.request.status is ConsentRequestStatus.PENDING
            assert len(outcome.decisions) == 1
            assert outcome.decisions[0].status is ConsentDecisionStatus.APPROVED
            assert len(outcome.grants) == 1
            assert outcome.grants[0].expires_at == START + dt.timedelta(days=90)
            assert outcome.grants[0].revoked_at is None
            assert await h.actions() == ["ACCESS_REQUESTED", "CONSENT_APPROVED"]

    asyncio.run(scenario())


def test_answering_every_category_closes_the_request() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            request_id = await _request(h, "CBC", "MRI")
            await h.service.approve_categories(h.patient, request_id, [h.categories["CBC"]])
            outcome = await h.service.reject_categories(
                h.patient, request_id, [h.categories["MRI"]]
            )
            assert outcome.request.status is ConsentRequestStatus.DECIDED
            assert outcome.grants == ()  # a rejection grants nothing
            assert outcome.decisions[0].status is ConsentDecisionStatus.REJECTED

    asyncio.run(scenario())


def test_full_approval_in_one_call_closes_the_request_and_grants_each_category() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            request_id = await _request(h, "CBC", "MRI")
            outcome = await h.service.approve_categories(
                h.patient, request_id, [h.categories["CBC"], h.categories["MRI"]]
            )
            assert outcome.request.status is ConsentRequestStatus.DECIDED
            assert len(outcome.grants) == 2
            assert await h.actions() == [
                "ACCESS_REQUESTED",
                "CONSENT_APPROVED",
                "CONSENT_APPROVED",
            ]

    asyncio.run(scenario())


def test_only_the_target_patient_may_decide_and_a_stranger_sees_nothing() -> None:
    """404-not-403: another patient's request must be indistinguishable from missing."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            request_id = await _request(h, "CBC")
            with pytest.raises(RequestNotFoundError):
                await h.service.approve_categories(
                    h.other_patient, request_id, [h.categories["CBC"]]
                )
            with pytest.raises(RequestNotFoundError):
                await h.service.approve_categories(h.patient, uuid4(), [h.categories["CBC"]])

    asyncio.run(scenario())


def test_a_closed_request_refuses_further_decisions() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            request_id = await _request(h, "CBC")
            await h.service.approve_categories(h.patient, request_id, [h.categories["CBC"]])
            with pytest.raises(RequestNotDecidableError) as excinfo:
                await h.service.reject_categories(h.patient, request_id, [h.categories["CBC"]])
            assert excinfo.value.status == "DECIDED"

    asyncio.run(scenario())


def test_an_expired_request_is_closed_lazily_on_the_next_decision() -> None:
    """No sweep has to run: a late decision cannot slip through between sweeps."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            request_id = await _request(h, "CBC")
            h.clock.advance(dt.timedelta(days=8))
            with pytest.raises(RequestNotDecidableError) as excinfo:
                await h.service.approve_categories(h.patient, request_id, [h.categories["CBC"]])
            assert excinfo.value.status == "EXPIRED"
            inbox = await h.service.list_inbox(h.patient, after=None, limit=10)
            assert inbox.items[0].request.status is ConsentRequestStatus.EXPIRED

    asyncio.run(scenario())


def test_a_category_the_request_never_asked_for_cannot_be_decided() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            request_id = await _request(h, "CBC")
            with pytest.raises(UnrequestedCategoryError):
                await h.service.approve_categories(h.patient, request_id, [h.categories["XRAY"]])

    asyncio.run(scenario())


# -- enforcement -----------------------------------------------------------------------


async def _granted(h: Harness) -> UUID:
    request_id = await _request(h, "CBC", "MRI")
    outcome = await h.service.approve_categories(h.patient, request_id, [h.categories["CBC"]])
    return outcome.grants[0].id


async def _reads(h: Harness, category: str) -> bool:
    try:
        await h.service.enforce(
            h.doctor,
            patient_id=h.patient_id,
            category_id=h.categories[category],
            action=AuditAction.RECORD_VIEWED,
            record_id=h.record_id,
        )
        return True
    except AccessDeniedError:
        return False


def test_an_active_clinician_reads_only_the_approved_category_and_the_read_is_logged() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            await _granted(h)
            assert await _reads(h, "CBC") is True
            assert await _reads(h, "MRI") is False
            assert await h.actions() == [
                "ACCESS_DENIED",  # the MRI attempt
                "ACCESS_REQUESTED",
                "CONSENT_APPROVED",
                "RECORD_VIEWED",  # the CBC read
            ]

    asyncio.run(scenario())


def test_a_denied_read_is_audited_before_the_error_is_raised() -> None:
    """The M3 gate: unauthorized reads are denied AND logged."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            with pytest.raises(AccessDeniedError):
                await h.service.enforce(
                    h.doctor,
                    patient_id=h.patient_id,
                    category_id=h.categories["CBC"],
                    action=AuditAction.RECORD_DOWNLOADED,
                    record_id=h.record_id,
                )
            rows = await h.audit.list_page_by_patient(h.patient_id, after=None, limit=10)
            assert [row.action for row in rows] == [AuditAction.ACCESS_DENIED]
            assert rows[0].target_record_id == h.record_id

    asyncio.run(scenario())


# -- listing grants --------------------------------------------------------------------


def test_grant_listing_returns_every_grant_the_patient_has_ever_been_given() -> None:
    """Set equality, not order: ``created_at`` is DB-assigned and SQLite resolves it to the
    second, so grants made inside one test tick are genuinely simultaneous. Newest-first is
    the repository's contract and is asserted where the timestamps differ
    (test_consent_repositories.py)."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            created = {await _granted(h), await _granted(h)}

            page = await h.service.list_grants(h.patient, after=None, limit=10)

            assert {view.grant.id for view in page.items} == created
            assert page.next_cursor is None

    asyncio.run(scenario())


def test_each_listed_grant_carries_the_state_enforcement_would_apply() -> None:
    """ACTIVE, REVOKED and EXPIRED, read from the service's own clock."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            revoked = await _granted(h)
            h.clock.advance(dt.timedelta(minutes=1))
            active = await _granted(h)
            await h.service.revoke_grant(h.patient, revoked)

            states = {
                view.grant.id: view.state
                for view in (await h.service.list_grants(h.patient, after=None, limit=10)).items
            }
            assert states == {
                active: ConsentGrantState.ACTIVE,
                revoked: ConsentGrantState.REVOKED,
            }

            # Past the 90-day default TTL the unrevoked grant lapses on its own; the
            # revoked one is still reported as revoked, which outranks the deadline.
            h.clock.advance(dt.timedelta(days=91))
            lapsed = {
                view.grant.id: view.state
                for view in (await h.service.list_grants(h.patient, after=None, limit=10)).items
            }
            assert lapsed == {
                active: ConsentGrantState.EXPIRED,
                revoked: ConsentGrantState.REVOKED,
            }

    asyncio.run(scenario())


def test_a_listed_state_agrees_with_what_enforcement_does() -> None:
    """The listing must never claim a grant is ACTIVE that a read would be refused on."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            await _granted(h)
            assert await _reads(h, "CBC") is True

            h.clock.advance(dt.timedelta(days=91))

            page = await h.service.list_grants(h.patient, after=None, limit=10)
            assert [view.state for view in page.items] == [ConsentGrantState.EXPIRED]
            assert await _reads(h, "CBC") is False

    asyncio.run(scenario())


def test_grant_listing_is_scoped_to_the_calling_patient() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            await _granted(h)

            page = await h.service.list_grants(h.other_patient, after=None, limit=10)

            assert page.items == []

    asyncio.run(scenario())


def test_grant_listing_needs_a_patient_profile() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            ghost = AuthenticatedUser(user_id=uuid4(), firebase_uid="fb-g", role=Role.PATIENT)
            with pytest.raises(PatientProfileNotFoundError):
                await h.service.list_grants(ghost, after=None, limit=10)

    asyncio.run(scenario())


def test_grant_pagination_walks_every_grant_without_overlap() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            created = set()
            for _ in range(5):
                created.add(await _granted(h))
                h.clock.advance(dt.timedelta(minutes=1))

            seen: set[UUID] = set()
            after: CursorKey | None = None
            pages = 0
            while True:
                page = await h.service.list_grants(h.patient, after=after, limit=2)
                seen.update(view.grant.id for view in page.items)
                pages += 1
                if page.next_cursor is None:
                    break
                after = decode_cursor(page.next_cursor)
            assert seen == created
            assert pages == 3

    asyncio.run(scenario())


def test_every_listing_names_the_people_behind_the_ids() -> None:
    """One projection, three listings: the inbox names the requester, the grants listing
    names the grantee, and the trail names the actor — all from the same directory."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            await _granted(h)

            inbox = await h.service.list_inbox(h.patient, after=None, limit=10)
            requester = inbox.items[0].requester
            assert requester is not None
            assert requester.full_name == "Dr Verma"
            assert requester.hospital_name == "TMH"
            assert inbox.items[0].requester_hospital_name == "TMH"

            grants = await h.service.list_grants(h.patient, after=None, limit=10)
            grantee = grants.items[0].grantee
            assert grantee is not None
            assert grantee.full_name == "Dr Verma"

            trail = await h.service.list_audit_events(h.patient, after=None, limit=10)
            by_action = {view.entry.action: view.actor for view in trail.items}
            asked = by_action[AuditAction.ACCESS_REQUESTED]
            assert asked is not None and asked.full_name == "Dr Verma"
            # The patient's own approval is not named: the role already says it was them.
            assert by_action[AuditAction.CONSENT_APPROVED] is None

    asyncio.run(scenario())


# -- listing the trail -----------------------------------------------------------------


def test_the_trail_lists_the_patients_events_most_recent_first() -> None:
    """Ordering is deterministic here because ``occurred_at`` is application-assigned: the
    harness clock moves between events, so they are genuinely sequential."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            request_id = await _request(h, "CBC")
            h.clock.advance(dt.timedelta(seconds=1))
            outcome = await h.service.approve_categories(
                h.patient, request_id, [h.categories["CBC"]]
            )
            h.clock.advance(dt.timedelta(seconds=1))
            await h.service.revoke_grant(h.patient, outcome.grants[0].id)

            page = await h.service.list_audit_events(h.patient, after=None, limit=10)

            assert [view.entry.action for view in page.items] == [
                AuditAction.CONSENT_REVOKED,
                AuditAction.CONSENT_APPROVED,
                AuditAction.ACCESS_REQUESTED,
            ]
            assert page.next_cursor is None

    asyncio.run(scenario())


def test_the_trail_carries_the_actor_and_the_role_they_held() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            await _request(h, "CBC")

            page = await h.service.list_audit_events(h.patient, after=None, limit=10)

            entry = page.items[0].entry
            assert entry.action is AuditAction.ACCESS_REQUESTED
            assert entry.actor_user_id == h.doctor.user_id
            assert entry.actor_role is Role.DOCTOR
            assert entry.target_request_id is not None
            assert entry.event_hash != ""

    asyncio.run(scenario())


def test_a_refused_read_is_visible_to_the_patient_it_concerns() -> None:
    """The point of the log: denials are in it, and the subject can see them."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            assert await _reads(h, "CBC") is False

            page = await h.service.list_audit_events(h.patient, after=None, limit=10)

            assert [view.entry.action for view in page.items] == [AuditAction.ACCESS_DENIED]
            assert page.items[0].entry.target_record_id == h.record_id

    asyncio.run(scenario())


def test_the_trail_is_scoped_to_the_calling_patient() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            await _request(h, "CBC")

            page = await h.service.list_audit_events(h.other_patient, after=None, limit=10)

            assert page.items == []

    asyncio.run(scenario())


def test_the_trail_needs_a_patient_profile() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            ghost = AuthenticatedUser(user_id=uuid4(), firebase_uid="fb-g", role=Role.PATIENT)
            with pytest.raises(PatientProfileNotFoundError):
                await h.service.list_audit_events(ghost, after=None, limit=10)

    asyncio.run(scenario())


def test_reading_the_trail_does_not_append_to_it() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            await _request(h, "CBC")
            before = await h.actions()

            await h.service.list_audit_events(h.patient, after=None, limit=10)

            assert await h.actions() == before

    asyncio.run(scenario())


def test_trail_pagination_walks_every_event_without_overlap() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            for _ in range(5):
                await _request(h, "CBC")
                h.clock.advance(dt.timedelta(seconds=1))

            seen: set[UUID] = set()
            after: CursorKey | None = None
            pages = 0
            while True:
                page = await h.service.list_audit_events(h.patient, after=after, limit=2)
                seen.update(view.entry.id for view in page.items)
                pages += 1
                if page.next_cursor is None:
                    break
                after = decode_cursor(page.next_cursor)
            assert len(seen) == 5
            assert pages == 3

    asyncio.run(scenario())


def test_suspending_a_clinician_cuts_access_even_though_the_grant_survives() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            grant_id = await _granted(h)
            assert await _reads(h, "CBC") is True
            h.clinicians.suspend(h.doctor.user_id)
            assert await _reads(h, "CBC") is False
            grant = await h.grants.get_by_id(grant_id)
            assert grant is not None and grant.revoked_at is None  # the grant is untouched

    asyncio.run(scenario())


def test_a_patient_reads_their_own_data_trivially_and_it_still_logs() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            await h.service.enforce(
                h.patient,
                patient_id=h.patient_id,
                category_id=h.categories["XRAY"],  # never requested by anyone
                action=AuditAction.RECORD_VIEWED,
                record_id=h.record_id,
            )
            assert await h.actions() == ["RECORD_VIEWED"]
            # ...but not somebody else's data.
            with pytest.raises(AccessDeniedError):
                await h.service.enforce(
                    h.other_patient,
                    patient_id=h.patient_id,
                    category_id=h.categories["XRAY"],
                    action=AuditAction.RECORD_VIEWED,
                )

    asyncio.run(scenario())


def test_admin_roles_are_refused_by_enforce_and_the_refusal_is_logged() -> None:
    """docs/SECURITY.md: no admin break-glass exists, and attempts leave a trail."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            for role in (Role.HOSPITAL_ADMIN, Role.SYSTEM_ADMIN):
                actor = AuthenticatedUser(user_id=h.doctor.user_id, firebase_uid="fb-a", role=role)
                with pytest.raises(AccessDeniedError):
                    await h.service.enforce(
                        actor,
                        patient_id=h.patient_id,
                        category_id=h.categories["CBC"],
                        action=AuditAction.RECORD_VIEWED,
                    )
            assert await h.actions() == ["ACCESS_DENIED", "ACCESS_DENIED"]

    asyncio.run(scenario())


def test_an_expired_grant_stops_authorizing_without_being_revoked() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            await _granted(h)
            assert await _reads(h, "CBC") is True
            h.clock.advance(dt.timedelta(days=91))
            assert await _reads(h, "CBC") is False

    asyncio.run(scenario())


# -- revocation ------------------------------------------------------------------------


def test_revocation_cuts_access_immediately_and_is_audited_once() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            grant_id = await _granted(h)
            assert await _reads(h, "CBC") is True

            revoked = await h.service.revoke_grant(h.patient, grant_id)
            assert revoked.revoked_at == START
            assert await _reads(h, "CBC") is False
            before = await h.actions()
            assert before.count("CONSENT_REVOKED") == 1

            # Idempotent: nothing changed, so nothing is recorded a second time.
            again = await h.service.revoke_grant(h.patient, grant_id)
            assert again.revoked_at == START
            assert (await h.actions()).count("CONSENT_REVOKED") == 1

    asyncio.run(scenario())


def test_only_the_owning_patient_may_revoke() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            grant_id = await _granted(h)
            with pytest.raises(GrantNotFoundError):
                await h.service.revoke_grant(h.other_patient, grant_id)
            with pytest.raises(GrantNotFoundError):
                await h.service.revoke_grant(h.patient, uuid4())

    asyncio.run(scenario())


# -- audit properties ------------------------------------------------------------------


def test_every_audit_row_is_hashed_distinctly_and_carries_a_capped_context() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            request_id = await h.service.create_request(
                h.doctor,
                patient_health_id=HEALTH_ID,
                category_ids=[h.categories["CBC"]],
                purpose="p",
                request_context="A" * 5_000 + "\n\x00bad",
            )
            await h.service.approve_categories(
                h.patient, request_id.request.id, [h.categories["CBC"]], request_context="req-1"
            )
            rows = await h.audit.list_page_by_patient(h.patient_id, after=None, limit=10)
            assert len(rows) == 2
            assert all(len(row.event_hash) == 64 for row in rows)
            assert len({row.event_hash for row in rows}) == 2
            contexts = {row.request_context for row in rows}
            assert "req-1" in contexts
            oversized = next(value for value in contexts if value != "req-1")
            assert oversized is not None
            assert len(oversized) == 200  # capped, control characters stripped
            assert "\x00" not in oversized

    asyncio.run(scenario())


def test_the_hash_covers_the_payload_so_two_identical_looking_events_differ() -> None:
    """Same actor, action and subject at the same instant still hash differently, because
    the row id is part of the canonical payload (ADR-004)."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            for _ in range(2):
                with pytest.raises(AccessDeniedError):
                    await h.service.enforce(
                        h.doctor,
                        patient_id=h.patient_id,
                        category_id=h.categories["CBC"],
                        action=AuditAction.RECORD_VIEWED,
                    )
            rows = await h.audit.list_page_by_patient(h.patient_id, after=None, limit=10)
            assert len(rows) == 2
            assert rows[0].occurred_at == rows[1].occurred_at
            assert rows[0].event_hash != rows[1].event_hash

    asyncio.run(scenario())


def test_a_caller_without_a_patient_profile_cannot_decide_or_revoke() -> None:
    """Valid PATIENT claims with no profile row is a 404-class condition, not a crash."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            request_id = await _request(h, "CBC")
            ghost = AuthenticatedUser(user_id=uuid4(), firebase_uid="fb-ghost", role=Role.PATIENT)
            with pytest.raises(PatientProfileNotFoundError):
                await h.service.approve_categories(ghost, request_id, [h.categories["CBC"]])
            with pytest.raises(PatientProfileNotFoundError):
                await h.service.revoke_grant(ghost, uuid4())

    asyncio.run(scenario())


# -- scope resolution and listing audit (ADR-020) ---------------------------------------


async def _approve(h: Harness, *codes: str) -> UUID:
    request_id = await _request(h, *codes)
    outcome = await h.service.approve_categories(
        h.patient, request_id, [h.categories[code] for code in codes]
    )
    return outcome.grants[0].id


def test_scope_reports_exactly_the_categories_enforce_would_admit() -> None:
    """``granted_category_ids`` and ``enforce`` must never disagree — a listing that
    offered a record the next read refuses would make the choke point a lie."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            request_id = await _request(h, "CBC", "MRI")
            await h.service.approve_categories(h.patient, request_id, [h.categories["CBC"]])
            await h.service.reject_categories(h.patient, request_id, [h.categories["MRI"]])

            scope = await h.service.granted_category_ids(
                h.doctor, patient_id=h.patient_id, at=h.clock.now
            )

            assert scope == {h.categories["CBC"]}
            await h.service.enforce(
                h.doctor,
                patient_id=h.patient_id,
                category_id=h.categories["CBC"],
                action=AuditAction.RECORD_VIEWED,
            )
            with pytest.raises(AccessDeniedError):
                await h.service.enforce(
                    h.doctor,
                    patient_id=h.patient_id,
                    category_id=h.categories["MRI"],
                    action=AuditAction.RECORD_VIEWED,
                )

    asyncio.run(scenario())


def test_scope_is_empty_for_a_suspended_clinician_and_for_everyone_else() -> None:
    """ADR-015 applies to the scope query as much as to the verdict; and a scope is a
    clinician's notion, so no other role can obtain one for another person's data."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            await _approve(h, "CBC")

            async def scope(caller: AuthenticatedUser) -> frozenset[UUID]:
                return await h.service.granted_category_ids(
                    caller, patient_id=h.patient_id, at=h.clock.now
                )

            assert await scope(h.doctor) == {h.categories["CBC"]}
            # The patient's own records are reached by ownership, never by a grant.
            assert await scope(h.patient) == frozenset()
            assert await scope(h.other_patient) == frozenset()

            h.clinicians.suspend(h.doctor.user_id)
            assert await scope(h.doctor) == frozenset()

    asyncio.run(scenario())


def test_scope_is_empty_for_an_unknown_clinician_and_writes_nothing() -> None:
    """The query is side-effect free: it is safe to ask before knowing whether a listing
    will be served, which is why it can be reused wherever consent-scoped retrieval is
    needed."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            await _approve(h, "CBC")
            before = await h.actions()
            stranger = AuthenticatedUser(
                user_id=uuid4(), firebase_uid="fb-nobody", role=Role.DOCTOR
            )

            assert (
                await h.service.granted_category_ids(
                    stranger, patient_id=h.patient_id, at=h.clock.now
                )
                == frozenset()
            )
            assert await h.service.granted_category_ids(
                h.doctor, patient_id=h.patient_id, at=h.clock.now
            ) == {h.categories["CBC"]}
            assert await h.actions() == before  # neither call touched the trail

    asyncio.run(scenario())


def test_scope_expires_with_the_grant_behind_it() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            grant_id = await _approve(h, "CBC")

            h.clock.advance(dt.timedelta(days=91))
            assert (
                await h.service.granted_category_ids(
                    h.doctor, patient_id=h.patient_id, at=h.clock.now
                )
                == frozenset()
            )

            h.clock.advance(-dt.timedelta(days=91))
            await h.service.revoke_grant(h.patient, grant_id)
            assert (
                await h.service.granted_category_ids(
                    h.doctor, patient_id=h.patient_id, at=h.clock.now
                )
                == frozenset()
            )

    asyncio.run(scenario())


def test_a_served_listing_is_recorded_as_records_listed_with_no_target() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)

            await h.service.record_listing(
                h.doctor,
                patient_id=h.patient_id,
                granted_category_ids=frozenset({h.categories["CBC"]}),
                at=h.clock.now,
                request_context="req-42",
            )

            (event,) = await h.audit.list_page_by_patient(h.patient_id, after=None, limit=9)
            assert event.action is AuditAction.RECORDS_LISTED
            assert event.actor_user_id == h.doctor.user_id
            assert event.actor_role is Role.DOCTOR
            assert event.patient_id == h.patient_id
            assert event.request_context == "req-42"
            # A scope-level event fills none of the three target columns (ADR-020).
            assert (
                event.target_record_id is None
                and event.target_category_id is None
                and event.target_request_id is None
            )
            assert event.event_hash  # hashed like every other event

    asyncio.run(scenario())


def test_a_listing_with_nothing_in_scope_is_recorded_as_a_refusal() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)

            await h.service.record_listing(
                h.doctor,
                patient_id=h.patient_id,
                granted_category_ids=frozenset(),
                at=h.clock.now,
            )

            (event,) = await h.audit.list_page_by_patient(h.patient_id, after=None, limit=9)
            assert event.action is AuditAction.ACCESS_DENIED
            assert event.target_record_id is None

    asyncio.run(scenario())


def test_a_summary_generated_is_recorded_with_no_target() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)

            await h.service.record_summary_generated(
                h.doctor,
                patient_id=h.patient_id,
                at=h.clock.now,
                request_context="req-ai-test",
            )

            (event,) = await h.audit.list_page_by_patient(h.patient_id, after=None, limit=9)
            assert event.action is AuditAction.SUMMARY_GENERATED
            assert event.actor_user_id == h.doctor.user_id
            assert event.actor_role is Role.DOCTOR
            assert event.patient_id == h.patient_id
            assert event.request_context == "req-ai-test"
            assert event.target_record_id is None
            assert event.target_category_id is None
            assert event.target_request_id is None
            assert event.event_hash
            assert event.actor_hospital_id == h.clinicians.by_user_id[h.doctor.user_id].hospital_id

    asyncio.run(scenario())


# -- ADR-023: historical hospital attribution and hash schemes -------------------------------


def test_v1_canonicalization_omits_the_hospital_key_entirely() -> None:
    """The property that keeps legacy rows verifiable. Emitting the key as null would change
    the bytes and fail every digest written before migration 0005."""
    fields = {"id": "x", "actor_hospital_id": None}

    v1 = canonical_event_payload(fields, scheme=HASH_SCHEME_V1)
    v2 = canonical_event_payload(fields, scheme=HASH_SCHEME_V2)

    assert "actor_hospital_id" not in v1
    assert "actor_hospital_id" in v2
    assert v1 != v2


def test_a_v1_payload_is_byte_identical_to_the_pre_0005_encoding() -> None:
    """Pinned literally: this is the encoding every legacy digest was computed over, so a
    change to it silently invalidates the whole existing trail."""
    fields = {
        "id": "11111111-1111-4111-8111-111111111111",
        "actor_user_id": "22222222-2222-4222-8222-222222222222",
        "actor_role": "DOCTOR",
        "action": "RECORD_VIEWED",
        "patient_id": "33333333-3333-4333-8333-333333333333",
        "target_record_id": None,
        "target_category_id": None,
        "target_request_id": None,
        "request_context": None,
        "occurred_at": "2026-03-01T00:00:00+00:00",
        "actor_hospital_id": "44444444-4444-4444-8444-444444444444",
    }

    assert canonical_event_payload(fields, scheme=HASH_SCHEME_V1) == (
        '{"action":"RECORD_VIEWED","actor_role":"DOCTOR",'
        '"actor_user_id":"22222222-2222-4222-8222-222222222222",'
        '"id":"11111111-1111-4111-8111-111111111111",'
        '"occurred_at":"2026-03-01T00:00:00+00:00",'
        '"patient_id":"33333333-3333-4333-8333-333333333333",'
        '"request_context":null,"target_category_id":null,'
        '"target_record_id":null,"target_request_id":null}'
    )


def test_a_scheme_mismatch_is_detectable_in_both_directions() -> None:
    """Why hash_version may sit outside the hashed payload: selecting the wrong scheme
    changes the key set, so a downgraded or upgraded row fails verification."""
    fields = {"id": "x", "actor_hospital_id": "hospital-1"}

    assert sha256_event_hash(canonical_event_payload(fields, scheme=HASH_SCHEME_V2)) != (
        sha256_event_hash(canonical_event_payload(fields, scheme=HASH_SCHEME_V1))
    )


def test_new_events_are_written_under_v3_and_verify_under_it() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            await _request(h, "CBC")

            row = (await h.audit.list_page_by_patient(h.patient_id, after=None, limit=9))[0]

            assert CURRENT_HASH_SCHEME == HASH_SCHEME_V3
            assert row.hash_version == HASH_SCHEME_V3
            recomputed = keccak256_event_hash(
                canonical_event_payload(
                    {
                        "id": str(row.id),
                        "actor_user_id": str(row.actor_user_id),
                        "actor_role": row.actor_role.value,
                        "action": row.action.value,
                        "patient_id": str(row.patient_id),
                        "target_record_id": None,
                        "target_category_id": None,
                        "target_request_id": str(row.target_request_id),
                        "request_context": row.request_context,
                        # as_utc: SQLite round-trips this column naive while the hash
                        # covered the aware value. Postgres needs no such repair; the
                        # same divergence the service documents for deadline checks.
                        "occurred_at": as_utc(row.occurred_at).isoformat(),
                        "actor_hospital_id": str(row.actor_hospital_id),
                    },
                    scheme=row.hash_version,
                )
            )
            assert recomputed == row.event_hash

    asyncio.run(scenario())


# -- ADR-019: Keccak-256 as scheme v3, beside the SHA-256 schemes it does not replace -----

#: Published Keccak-256 vectors (the original Keccak submission, as Ethereum uses it). The
#: empty-input digest is Ethereum's ``KECCAK_EMPTY`` constant; SHA3-256 of the same inputs
#: is listed beside each so a silent swap to ``hashlib.sha3_256`` cannot pass.
KECCAK_VECTORS = [
    (
        "",
        "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470",
        "a7ffc6f8bf1ed76651c14756a061d662f580ff4de43b49fa82d80a4b80f8434a",
    ),
    (
        "abc",
        "4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45",
        "3a985da74fe225b2045c172d6bd390bd855f086e3e9d525b46bfe24511431532",
    ),
    (
        "The quick brown fox jumps over the lazy dog",
        "4d741b6f1eb29cb2a9b9911c82f56fa8d73b04959d3d9d222895df6c0b28aa15",
        "69070dda01975c8c120c3aada1b282394e7f032fa9cf32f4cb2259a0897dfc04",
    ),
]

#: One fixed event, and the digests each scheme gives it — pinned literally, computed
#: independently from the canonical JSON strings rather than through the code under test.
#: v1 and v2 are what rows written before the keccak transition carry, so a change to any
#: of these silently invalidates part of the existing trail.
PINNED_FIELDS: dict[str, object] = {
    "id": "11111111-1111-4111-8111-111111111111",
    "actor_user_id": "22222222-2222-4222-8222-222222222222",
    "actor_role": "DOCTOR",
    "action": "RECORD_VIEWED",
    "patient_id": "33333333-3333-4333-8333-333333333333",
    "target_record_id": None,
    "target_category_id": None,
    "target_request_id": None,
    "request_context": None,
    "occurred_at": "2026-03-01T00:00:00+00:00",
    "actor_hospital_id": "44444444-4444-4444-8444-444444444444",
}
PINNED_DIGESTS = {
    HASH_SCHEME_V1: "da488dec30fd904f8d8452dc30dec38b28de64b4f35a8dc1cadec5bcef554c86",
    HASH_SCHEME_V2: "3a6b000ad492809810a311f4690f4d6b54120b218dfdd2c3185e65a2cee12f6f",
    HASH_SCHEME_V3: "47e2ee003111a0b4f9a7783b8ecd6bc70efd7a3960fec10f44a544d4df8653f1",
}


def _pinned_row(scheme: int) -> AuditLog:
    """``PINNED_FIELDS`` as an ``AuditLog`` row, carrying its pinned digest under ``scheme``."""
    return AuditLog(
        id=UUID("11111111-1111-4111-8111-111111111111"),
        actor_user_id=UUID("22222222-2222-4222-8222-222222222222"),
        actor_role=Role.DOCTOR,
        action=AuditAction.RECORD_VIEWED,
        patient_id=UUID("33333333-3333-4333-8333-333333333333"),
        target_record_id=None,
        target_category_id=None,
        target_request_id=None,
        request_context=None,
        occurred_at=dt.datetime(2026, 3, 1, tzinfo=dt.UTC),
        actor_hospital_id=UUID("44444444-4444-4444-8444-444444444444"),
        hash_version=scheme,
        event_hash=PINNED_DIGESTS[scheme],
    )


@pytest.mark.parametrize(("message", "expected", "sha3"), KECCAK_VECTORS)
def test_keccak256_matches_published_vectors_and_is_not_sha3(
    message: str, expected: str, sha3: str
) -> None:
    digest = keccak256_event_hash(message)

    assert digest == expected
    assert digest != sha3
    assert hashlib.sha3_256(message.encode()).hexdigest() == sha3


def test_each_scheme_resolves_to_its_own_algorithm() -> None:
    assert event_hasher_for(HASH_SCHEME_V1) is sha256_event_hash
    assert event_hasher_for(HASH_SCHEME_V2) is sha256_event_hash
    assert event_hasher_for(HASH_SCHEME_V3) is keccak256_event_hash


def test_v3_hashes_exactly_the_v2_payload() -> None:
    """v3 changes the algorithm and nothing else: same keys, same bytes."""
    assert canonical_event_payload(PINNED_FIELDS, scheme=HASH_SCHEME_V3) == (
        canonical_event_payload(PINNED_FIELDS, scheme=HASH_SCHEME_V2)
    )


@pytest.mark.parametrize("scheme", [HASH_SCHEME_V1, HASH_SCHEME_V2, HASH_SCHEME_V3])
def test_each_scheme_reproduces_its_pinned_digest(scheme: int) -> None:
    canonical = canonical_event_payload(PINNED_FIELDS, scheme=scheme)

    assert event_hasher_for(scheme)(canonical) == PINNED_DIGESTS[scheme]


def test_the_three_schemes_give_three_distinct_digests() -> None:
    assert len(set(PINNED_DIGESTS.values())) == 3


def test_v3_digest_is_deterministic_and_bare_lowercase_hex() -> None:
    first = keccak256_event_hash(canonical_event_payload(PINNED_FIELDS, scheme=HASH_SCHEME_V3))
    reordered = dict(reversed(list(PINNED_FIELDS.items())))
    second = keccak256_event_hash(canonical_event_payload(reordered, scheme=HASH_SCHEME_V3))

    assert first == second
    assert len(first) == 64
    assert set(first) <= set("0123456789abcdef")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("action", "CONSENT_REVOKED"),
        ("occurred_at", "2026-03-01T00:00:01+00:00"),
        ("actor_hospital_id", None),
        ("request_context", "req-1"),
    ],
)
def test_changing_a_hashed_field_changes_the_v3_digest(field: str, value: object) -> None:
    altered = {**PINNED_FIELDS, field: value}
    digest = keccak256_event_hash(canonical_event_payload(altered, scheme=HASH_SCHEME_V3))

    assert digest != PINNED_DIGESTS[HASH_SCHEME_V3]


@pytest.mark.parametrize("scheme", [HASH_SCHEME_V1, HASH_SCHEME_V2, HASH_SCHEME_V3])
def test_a_row_recomputes_under_its_own_scheme(scheme: int) -> None:
    assert recompute_event_hash(_pinned_row(scheme)) == PINNED_DIGESTS[scheme]


def test_a_relabelled_row_no_longer_recomputes_to_its_digest() -> None:
    """A v2 SHA-256 row relabelled v3 (or the reverse) fails: the version picks the
    algorithm, so it cannot be changed without the digest diverging."""
    v2_as_v3 = _pinned_row(HASH_SCHEME_V2)
    v2_as_v3.hash_version = HASH_SCHEME_V3
    v3_as_v2 = _pinned_row(HASH_SCHEME_V3)
    v3_as_v2.hash_version = HASH_SCHEME_V2

    assert recompute_event_hash(v2_as_v3) != v2_as_v3.event_hash
    assert recompute_event_hash(v3_as_v2) != v3_as_v2.event_hash


@pytest.mark.parametrize("scheme", [0, 4, -1, 99])
def test_an_unknown_scheme_is_refused_rather_than_defaulted(scheme: int) -> None:
    with pytest.raises(UnsupportedHashSchemeError):
        event_hasher_for(scheme)
    with pytest.raises(UnsupportedHashSchemeError):
        canonical_event_payload(PINNED_FIELDS, scheme=scheme)
    row = _pinned_row(HASH_SCHEME_V2)
    row.hash_version = scheme
    with pytest.raises(UnsupportedHashSchemeError):
        recompute_event_hash(row)


def test_legacy_rows_are_left_untouched_when_new_events_are_written() -> None:
    """Writing v3 events never rehashes or relabels v1/v2 rows already in the trail, and
    each generation keeps verifying under its own scheme beside the others."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            legacy: list[AuditLog] = []
            for scheme, offset in ((HASH_SCHEME_V1, 2), (HASH_SCHEME_V2, 1)):
                row = AuditLog(
                    id=uuid4(),
                    actor_user_id=h.patient.user_id,
                    actor_role=Role.PATIENT,
                    action=AuditAction.RECORDS_LISTED,
                    patient_id=h.patient_id,
                    request_context=None,
                    occurred_at=START - dt.timedelta(days=offset),
                    actor_hospital_id=None,
                    hash_version=scheme,
                    event_hash="",
                )
                row.event_hash = recompute_event_hash(row)
                session.add(row)
                legacy.append(row)
            await session.flush()
            before = {row.id: (row.hash_version, row.event_hash) for row in legacy}

            await _request(h, "CBC")
            session.expire_all()

            rows = await h.audit.list_page_by_patient(h.patient_id, after=None, limit=9)
            by_id = {row.id: row for row in rows}
            for row_id, (scheme, digest) in before.items():
                assert (by_id[row_id].hash_version, by_id[row_id].event_hash) == (
                    scheme,
                    digest,
                )
            assert {row.hash_version for row in rows} == {
                HASH_SCHEME_V1,
                HASH_SCHEME_V2,
                HASH_SCHEME_V3,
            }
            assert all(recompute_event_hash(row) == row.event_hash for row in rows)

    asyncio.run(scenario())


def test_a_doctors_event_is_attributed_to_the_hospital_they_acted_for() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            await _request(h, "CBC")

            row = (await h.audit.list_page_by_patient(h.patient_id, after=None, limit=9))[0]
            assert row.actor_hospital_id == h.clinicians.by_user_id[h.doctor.user_id].hospital_id

    asyncio.run(scenario())


def test_a_patients_own_event_carries_no_hospital() -> None:
    """A patient belongs to no hospital; NULL is the honest value, not a gap."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            request_id = await _request(h, "CBC")
            await h.service.approve_categories(h.patient, request_id, [h.categories["CBC"]])

            rows = await h.audit.list_page_by_patient(h.patient_id, after=None, limit=9)
            approval = next(r for r in rows if r.actor_role is Role.PATIENT)
            assert approval.actor_hospital_id is None

    asyncio.run(scenario())


def test_a_transfer_does_not_move_historical_attribution() -> None:
    """The anti-join test, and the reason this column exists at all: re-registering the
    clinician at another hospital must not retro-attribute what they already did."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            original = h.clinicians.by_user_id[h.doctor.user_id]
            first_request = await _request(h, "CBC")

            # A real row: actor_hospital_id carries a foreign key, so the hospital a
            # clinician moves to has to exist.
            elsewhere = Hospital(
                hid="HID-9999",
                name="Elsewhere General",
                verification_status=HospitalVerificationStatus.VERIFIED,
            )
            session.add(elsewhere)
            await session.flush()
            moved_to = elsewhere.id
            h.clinicians.register(h.doctor.user_id, doctor_id=original.id, hospital_id=moved_to)
            # The harness clock is frozen, so without this both events share one
            # `occurred_at` and "the later event" would be decided by a random uuid4
            # tiebreaker. Move it so the two are genuinely ordered.
            h.clock.advance(dt.timedelta(minutes=1))
            second_request = await _request(h, "MRI")

            rows = await h.audit.list_page_by_patient(h.patient_id, after=None, limit=9)
            # Selected by the request each event targets rather than by position: the
            # assertion is about *which* event carries which hospital, and pinning that to
            # list order would make it depend on a tiebreaker instead of on the attribution.
            before = next(row for row in rows if row.target_request_id == first_request)
            after = next(row for row in rows if row.target_request_id == second_request)

            assert before.actor_hospital_id == original.hospital_id
            assert after.actor_hospital_id == moved_to
            # The earlier event is unchanged — history stayed where it happened.
            assert before.actor_hospital_id != moved_to

    asyncio.run(scenario())


def test_the_hospital_listing_is_scoped_paginated_and_isolated() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            mine = h.clinicians.by_user_id[h.doctor.user_id].hospital_id
            await _request(h, "CBC")
            await _request(h, "MRI")

            page = await h.audit.list_page_by_hospital(mine, after=None, limit=9)
            other = await h.audit.list_page_by_hospital(uuid4(), after=None, limit=9)

            assert len(page) == 2
            assert all(row.actor_hospital_id == mine for row in page)
            # Newest first, like the patient listing.
            assert page[0].occurred_at >= page[1].occurred_at
            # No cross-hospital leakage.
            assert other == []

    asyncio.run(scenario())


def test_unattributed_events_never_appear_in_a_hospital_listing() -> None:
    """Patient-actor events, and every legacy row, carry no hospital and are absent by
    construction rather than by an extra predicate."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            mine = h.clinicians.by_user_id[h.doctor.user_id].hospital_id
            request_id = await _request(h, "CBC")
            await h.service.approve_categories(h.patient, request_id, [h.categories["CBC"]])

            everything = await h.audit.list_page_by_patient(h.patient_id, after=None, limit=9)
            hospital_page = await h.audit.list_page_by_hospital(mine, after=None, limit=9)

            assert any(row.actor_hospital_id is None for row in everything)
            assert all(row.actor_hospital_id is not None for row in hospital_page)
            assert len(hospital_page) < len(everything)

    asyncio.run(scenario())


def test_the_hospital_listing_keyset_walks_without_repeating() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            mine = h.clinicians.by_user_id[h.doctor.user_id].hospital_id
            for code in ("CBC", "MRI", "XRAY"):
                await _request(h, code)

            first = await h.audit.list_page_by_hospital(mine, after=None, limit=2)
            cursor = CursorKey(created_at=first[-1].occurred_at, item_id=first[-1].id)
            second = await h.audit.list_page_by_hospital(mine, after=cursor, limit=2)

            assert len(first) == 2
            assert len(second) == 1
            assert {row.id for row in first}.isdisjoint({row.id for row in second})

    asyncio.run(scenario())


# -- ADR-025: the patient's trail groups on the historical hospital ------------------------


def test_the_patient_trail_reports_the_hospital_recorded_on_the_event() -> None:
    """**The regression test for ADR-025.**

    A clinician raises a request while employed at hospital A, then transfers to hospital
    B. The patient's trail must still attribute that event to **A**.

    The test deliberately asserts both halves. ``hospital`` is the historical attribution
    read from ``actor_hospital_id``; ``actor.hospital_name`` is the *current* affiliation the
    staff projection resolves, and it genuinely says **B** afterwards. Asserting only the
    first would pass even if the two were the same value; asserting both proves the response
    distinguishes them, which is the entire decision.
    """

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            original = h.clinicians.by_user_id[h.doctor.user_id]
            request_id = await _request(h, "CBC")

            elsewhere = Hospital(
                hid="HID-8888",
                name="Elsewhere General",
                verification_status=HospitalVerificationStatus.VERIFIED,
            )
            session.add(elsewhere)
            await session.flush()

            # Move the real Doctor row: the staff projection joins `doctors.hospital_id`,
            # so this is what makes the "current" answer differ from the historical one.
            doctor = await session.get(Doctor, original.id)
            assert doctor is not None
            doctor.hospital_id = elsewhere.id
            await session.flush()

            page = await h.service.list_audit_events(h.patient, after=None, limit=20)
            asked = next(view for view in page.items if view.entry.target_request_id == request_id)

            assert asked.hospital is not None
            assert asked.hospital.hid == "HID-0001"  # where the event happened
            assert asked.hospital.name == "TMH"
            # ...while the person is now somewhere else, and the response says so separately.
            assert asked.actor is not None
            assert asked.actor.hospital_name == "Elsewhere General"

    asyncio.run(scenario())


def test_a_patients_own_action_is_attributed_to_no_hospital() -> None:
    """A patient belongs to no organisation, so the trail must not invent one for them —
    the reason the column is nullable rather than defaulted."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            request_id = await _request(h, "CBC")
            await h.service.approve_categories(h.patient, request_id, [h.categories["CBC"]])

            page = await h.service.list_audit_events(h.patient, after=None, limit=20)
            approval = next(view for view in page.items if view.entry.actor_role is Role.PATIENT)
            assert approval.hospital is None
            assert approval.actor is None

    asyncio.run(scenario())


def test_an_unattributed_legacy_event_stays_unattributed() -> None:
    """Rows written before migration 0005 carry no hospital. The response must leave them
    empty rather than falling back to the actor's present employer — the fallback would be
    the very join ADR-023 refuses, and it would look indistinguishable from a real answer."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            request_id = await _request(h, "CBC")

            rows = await h.audit.list_page_by_patient(h.patient_id, after=None, limit=9)
            legacy = next(row for row in rows if row.target_request_id == request_id)
            legacy.actor_hospital_id = None  # as a pre-0005 row would be
            await session.flush()

            page = await h.service.list_audit_events(h.patient, after=None, limit=20)
            view = next(v for v in page.items if v.entry.target_request_id == request_id)
            assert view.hospital is None
            # The actor is still named — only the attribution is missing.
            assert view.actor is not None
            assert view.actor.hospital_name == "TMH"

    asyncio.run(scenario())


# ======================================================================================
# Notification Regression Tests (ADR-031 / Stage 3B)
# ======================================================================================


def test_consent_request_creation_emits_access_requested_notification() -> None:
    """Requirement A: In ConsentService.create_request:
    - Exactly one ACCESS_REQUESTED notification is created for the target patient.
    - Uses patient.user_id as recipient_user_id.
    - References the created consent request id.
    - Uses ADR-031's approved generic wording.
    """

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            request_id = await _request(h, "CBC")

            # Verify patient received exactly one notification
            items = await h.notifications.list_page_by_recipient(
                h.patient.user_id, after=None, limit=50
            )
            assert len(items) == 1

            n = items[0]
            assert n.recipient_user_id == h.patient.user_id
            assert n.event_type is NotificationEventType.ACCESS_REQUESTED
            assert n.reference_request_id == request_id
            assert n.actor_doctor_id == h.doctor_id
            assert n.actor_hospital_id is not None
            assert n.title == "Access Request Received"
            assert n.message == "A doctor requested access to your health records."
            assert n.is_read is False

            # Verify doctor and other patient received no notifications
            doc_items = await h.notifications.list_page_by_recipient(
                h.doctor.user_id, after=None, limit=50
            )
            assert len(doc_items) == 0
            other_items = await h.notifications.list_page_by_recipient(
                h.other_patient.user_id, after=None, limit=50
            )
            assert len(other_items) == 0

    asyncio.run(scenario())


def test_consent_approval_emits_single_notification_even_for_multiple_categories() -> None:
    """Requirement B: In ConsentService._decide (approval):
    - Emits CONSENT_APPROVED to requesting doctor's internal user_id.
    - Exactly ONE notification emitted even when approving multiple categories.
    - References the request id, doctor id, and hospital id.
    - Uses ADR-031's approved generic wording.
    """

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            request_id = await _request(h, "CBC", "MRI", "XRAY")

            # Patient approves all 3 categories in a single call
            await h.service.approve_categories(
                h.patient,
                request_id,
                [h.categories["CBC"], h.categories["MRI"], h.categories["XRAY"]],
            )

            # Requesting doctor received exactly ONE notification
            doc_items = await h.notifications.list_page_by_recipient(
                h.doctor.user_id, after=None, limit=50
            )
            assert len(doc_items) == 1

            n = doc_items[0]
            assert n.recipient_user_id == h.doctor.user_id
            assert n.event_type is NotificationEventType.CONSENT_APPROVED
            assert n.reference_request_id == request_id
            assert n.actor_doctor_id == h.doctor_id
            assert n.title == "Access Request Approved"
            assert n.message == "A patient approved your record access request."
            assert n.is_read is False

    asyncio.run(scenario())


def test_consent_rejection_emits_single_notification_even_for_multiple_categories() -> None:
    """Requirement C: In ConsentService._decide (rejection):
    - Emits CONSENT_REJECTED to requesting doctor's internal user_id.
    - Exactly ONE notification emitted even when rejecting multiple categories.
    - References the request id, doctor id, and hospital id.
    - Uses ADR-031's approved generic wording.
    """

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            request_id = await _request(h, "CBC", "MRI")

            # Patient rejects all categories in a single call
            await h.service.reject_categories(
                h.patient,
                request_id,
                [h.categories["CBC"], h.categories["MRI"]],
            )

            # Requesting doctor received exactly ONE notification
            doc_items = await h.notifications.list_page_by_recipient(
                h.doctor.user_id, after=None, limit=50
            )
            assert len(doc_items) == 1

            n = doc_items[0]
            assert n.recipient_user_id == h.doctor.user_id
            assert n.event_type is NotificationEventType.CONSENT_REJECTED
            assert n.reference_request_id == request_id
            assert n.actor_doctor_id == h.doctor_id
            assert n.title == "Access Request Declined"
            assert n.message == "A patient declined your record access request."
            assert n.is_read is False

    asyncio.run(scenario())


def test_consent_revocation_emits_notification_and_repeated_revocation_does_not_duplicate() -> None:
    """Requirement D: In ConsentService.revoke_grant:
    - Emits CONSENT_REVOKED to grantee doctor's internal user_id.
    - Emits only on newly revoked grant; repeated revocation attempts emit NO duplicates.
    - Uses generic copy from ADR-031 without disclosing clinical category.
    """

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            request_id = await _request(h, "CBC")
            outcome = await h.service.approve_categories(
                h.patient, request_id, [h.categories["CBC"]]
            )
            grant = outcome.grants[0]

            # Doctor currently has 1 notification (CONSENT_APPROVED)
            doc_items = await h.notifications.list_page_by_recipient(
                h.doctor.user_id, after=None, limit=50
            )
            assert len(doc_items) == 1

            # Revoke grant for the first time
            await h.service.revoke_grant(h.patient, grant.id)

            doc_items_after = await h.notifications.list_page_by_recipient(
                h.doctor.user_id, after=None, limit=50
            )
            assert len(doc_items_after) == 2

            # The new notification is CONSENT_REVOKED
            revoked_n = next(
                item
                for item in doc_items_after
                if item.event_type is NotificationEventType.CONSENT_REVOKED
            )
            assert revoked_n.recipient_user_id == h.doctor.user_id
            assert revoked_n.title == "Consent Grant Revoked"
            assert revoked_n.message == "A consent grant for patient records was revoked."
            assert revoked_n.actor_doctor_id == grant.grantee_doctor_id

            # Repeated revocation attempt (idempotency test)
            repeated_grant = await h.service.revoke_grant(h.patient, grant.id)
            assert repeated_grant.id == grant.id

            # Notification count must NOT increase
            doc_items_repeated = await h.notifications.list_page_by_recipient(
                h.doctor.user_id, after=None, limit=50
            )
            assert len(doc_items_repeated) == 2

    asyncio.run(scenario())


def test_consent_notifications_contain_no_phi_or_sensitive_identifiers() -> None:
    """Requirement E: Privacy compliance:
    - Notification title and message must NOT disclose patient name, health ID,
      clinical category names/codes, or document details.
    """

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            request_id = await _request(h, "CBC", "MRI")
            outcome = await h.service.approve_categories(
                h.patient, request_id, [h.categories["CBC"]]
            )
            await h.service.revoke_grant(h.patient, outcome.grants[0].id)
            await h.service.reject_categories(
                h.patient, request_id, [h.categories["MRI"]]
            )

            # Query all notifications in the session
            result = await session.execute(select(Notification))
            all_notifications = list(result.scalars())
            assert len(all_notifications) == 4  # request, approve, revoke, reject

            sensitive_terms = [
                "Aarav",  # patient name
                "Dr Verma",  # doctor name (not in message copy)
                HEALTH_ID,  # "PHI-IND-2026-1QE8DVR"
                "CBC",  # category code
                "MRI",  # category code
                "cbc.pdf",  # document filename
            ]

            for n in all_notifications:
                for term in sensitive_terms:
                    assert term not in n.title, f"Sensitive term '{term}' leaked in title: '{n.title}'"
                    assert term not in n.message, f"Sensitive term '{term}' leaked in message: '{n.message}'"

    asyncio.run(scenario())


def test_consent_mutation_and_notification_roll_back_together() -> None:
    """Requirement G: Transaction atomicity and rollback:
    - Proves notification and consent changes participate in the same session/transaction
      and roll back together when a transaction aborts.
    - Also proves that if notification creation fails, the exception is NOT swallowed
      and the consent request, audit log, and notification roll back.
    """

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)

            # 1. Rollback via savepoint: discards both consent request and notification
            async with session.begin_nested() as savepoint:
                await h.service.create_request(
                    h.doctor,
                    patient_health_id=HEALTH_ID,
                    category_ids=[h.categories["CBC"]],
                    purpose="follow-up",
                )
                # Verify rows exist in-flight within savepoint
                reqs = (await session.execute(select(ConsentRequest))).scalars().all()
                assert len(reqs) == 1
                notifs = (await session.execute(select(Notification))).scalars().all()
                assert len(notifs) == 1

                # Abort the savepoint
                await savepoint.rollback()

            # After rollback, neither consent request nor notification was persisted
            reqs_after = (await session.execute(select(ConsentRequest))).scalars().all()
            assert len(reqs_after) == 0
            notifs_after = (await session.execute(select(Notification))).scalars().all()
            assert len(notifs_after) == 0

            # 2. Simulated failure during notification insert:
            # Wrap notification repository to simulate database failure on add()
            class FailingNotificationRepository(NotificationRepository):
                async def add(self, notification: Notification) -> Notification:
                    raise RuntimeError("Simulated notification database failure")

            failing_service = ConsentService(
                requests=ConsentRequestRepository(session),
                request_categories=ConsentRequestCategoryRepository(session),
                decisions=ConsentDecisionRepository(session),
                grants=ConsentGrantRepository(session),
                audit=AuditLogRepository(session),
                patients=PatientDirectoryService(PatientRepository(session)),
                clinicians=h.clinicians,
                staff=RecordsStaffDirectory(staff_directory(session)),
                notifications=FailingNotificationRepository(session),
                clock=h.clock,
            )

            # Attempting request creation must raise and NOT swallow the exception
            with pytest.raises(RuntimeError, match="Simulated notification database failure"):
                async with session.begin_nested():
                    await failing_service.create_request(
                        h.doctor,
                        patient_health_id=HEALTH_ID,
                        category_ids=[h.categories["CBC"]],
                        purpose="follow-up",
                    )

            # The entire transaction rolled back: no request, no audit log, no notification
            reqs_fail = (await session.execute(select(ConsentRequest))).scalars().all()
            assert len(reqs_fail) == 0
            notifs_fail = (await session.execute(select(Notification))).scalars().all()
            assert len(notifs_fail) == 0
            audits_fail = (await session.execute(select(AuditLog))).scalars().all()
            assert len(audits_fail) == 0

    asyncio.run(scenario())
