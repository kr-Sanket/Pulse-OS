"""ConsentService tests: the request → decision → grant → revocation lifecycle and the
enforcement choke point.

The M3 invariants live here: only the target patient decides, a decision is permanent, a
grant is what enforcement reads, revocation and suspension both cut access immediately, and
**every** one of those events appends to the audit trail in the same transaction.
"""

import asyncio
import datetime as dt
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
from app.modules.consent.models import AuditAction, ConsentDecisionStatus, ConsentRequestStatus
from app.modules.consent.repository import (
    AuditLogRepository,
    ConsentDecisionRepository,
    ConsentGrantRepository,
    ConsentRequestCategoryRepository,
    ConsentRequestRepository,
)
from app.modules.consent.service import ConsentGrantState, ConsentService
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
