"""consent repository tests: constraint translation, keyset pagination, bounded fetches.

Every constraint migration 0004 declares is exercised here through the repository that
translates it, so a mapping that reports a foreign-key violation as a duplicate cannot pass.
"""

import asyncio
import datetime as dt
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from app.modules.auth.domain import Role
from app.modules.auth.models import User
from app.modules.consent.errors import (
    DuplicateDecisionError,
    DuplicateGrantError,
    DuplicateRequestCategoryError,
    UnrequestedCategoryError,
)
from app.modules.consent.models import (
    AuditAction,
    AuditLog,
    ConsentDecision,
    ConsentDecisionStatus,
    ConsentGrant,
    ConsentRequest,
    ConsentRequestCategory,
    ConsentRequestStatus,
)
from app.modules.consent.repository import (
    AuditLogRepository,
    ConsentDecisionRepository,
    ConsentGrantRepository,
    ConsentRequestCategoryRepository,
    ConsentRequestRepository,
)
from app.modules.patients.models import Patient
from app.modules.records.models import (
    Doctor,
    DoctorStatus,
    Hospital,
    HospitalVerificationStatus,
    RecordCategory,
)
from app.shared.pagination import CursorKey
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.support import sqlite_session

NOW = dt.datetime(2026, 9, 1, 10, 0, tzinfo=dt.UTC)


@dataclass
class Fixtures:
    session: AsyncSession
    requests: ConsentRequestRepository
    categories: ConsentRequestCategoryRepository
    decisions: ConsentDecisionRepository
    grants: ConsentGrantRepository
    audit: AuditLogRepository
    doctor_user_id: UUID
    doctor_id: UUID
    hospital_id: UUID
    patient_id: UUID
    cbc_id: UUID
    mri_id: UUID


async def _arrange(session: AsyncSession) -> Fixtures:
    doctor_user = User(firebase_uid=f"fb-d-{uuid4()}", role=Role.DOCTOR)
    patient_user = User(firebase_uid=f"fb-p-{uuid4()}", role=Role.PATIENT)
    session.add_all([doctor_user, patient_user])
    hospital = Hospital(
        hid="HID-9001", name="Test", verification_status=HospitalVerificationStatus.VERIFIED
    )
    session.add(hospital)
    await session.flush()
    doctor = Doctor(
        user_id=doctor_user.id,
        hospital_id=hospital.id,
        full_name="Dr Test",
        registration_number="R1",
        status=DoctorStatus.ACTIVE,
    )
    patient = Patient(
        user_id=patient_user.id, health_id="PHI-IND-2026-1QE8DVR", full_name="Patient"
    )
    cbc = RecordCategory(code="CBC", display_name="CBC")
    mri = RecordCategory(code="MRI", display_name="MRI")
    session.add_all([doctor, patient, cbc, mri])
    await session.flush()
    return Fixtures(
        session=session,
        requests=ConsentRequestRepository(session),
        categories=ConsentRequestCategoryRepository(session),
        decisions=ConsentDecisionRepository(session),
        grants=ConsentGrantRepository(session),
        audit=AuditLogRepository(session),
        doctor_user_id=doctor_user.id,
        doctor_id=doctor.id,
        hospital_id=hospital.id,
        patient_id=patient.id,
        cbc_id=cbc.id,
        mri_id=mri.id,
    )


async def _add_request(f: Fixtures, *, purpose: str = "p") -> ConsentRequest:
    return await f.requests.add(
        ConsentRequest(
            patient_id=f.patient_id,
            requester_doctor_id=f.doctor_id,
            requester_hospital_id=f.hospital_id,
            purpose=purpose,
            status=ConsentRequestStatus.PENDING,
            expires_at=NOW + dt.timedelta(days=7),
        )
    )


def test_duplicate_requested_category_is_translated() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            f = await _arrange(session)
            request = await _add_request(f)
            await f.categories.add(
                ConsentRequestCategory(request_id=request.id, category_id=f.cbc_id)
            )
            with pytest.raises(DuplicateRequestCategoryError):
                await f.categories.add(
                    ConsentRequestCategory(request_id=request.id, category_id=f.cbc_id)
                )

    asyncio.run(scenario())


def test_decision_on_an_unrequested_category_is_refused_by_the_composite_key() -> None:
    """The database, not the service, is what keeps a decision tied to the ask."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            f = await _arrange(session)
            request = await _add_request(f)
            await f.categories.add(
                ConsentRequestCategory(request_id=request.id, category_id=f.cbc_id)
            )
            with pytest.raises(UnrequestedCategoryError):
                await f.decisions.add(
                    ConsentDecision(
                        request_id=request.id,
                        category_id=f.mri_id,  # never requested
                        status=ConsentDecisionStatus.APPROVED,
                    )
                )

    asyncio.run(scenario())


def test_duplicate_decision_and_duplicate_grant_are_translated() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            f = await _arrange(session)
            request = await _add_request(f)
            await f.categories.add(
                ConsentRequestCategory(request_id=request.id, category_id=f.cbc_id)
            )
            decision = await f.decisions.add(
                ConsentDecision(
                    request_id=request.id,
                    category_id=f.cbc_id,
                    status=ConsentDecisionStatus.APPROVED,
                )
            )
            with pytest.raises(DuplicateDecisionError):
                await f.decisions.add(
                    ConsentDecision(
                        request_id=request.id,
                        category_id=f.cbc_id,
                        status=ConsentDecisionStatus.REJECTED,
                    )
                )

            def grant() -> ConsentGrant:
                return ConsentGrant(
                    decision_id=decision.id,
                    patient_id=f.patient_id,
                    grantee_doctor_id=f.doctor_id,
                    category_id=f.cbc_id,
                    expires_at=NOW + dt.timedelta(days=90),
                )

            await f.grants.add(grant())
            with pytest.raises(DuplicateGrantError):
                await f.grants.add(grant())

    asyncio.run(scenario())


def test_session_stays_usable_after_contained_constraint_failures() -> None:
    """Savepoints, not luck: a caught IntegrityError must not poison the transaction."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            f = await _arrange(session)
            request = await _add_request(f)
            await f.categories.add(
                ConsentRequestCategory(request_id=request.id, category_id=f.cbc_id)
            )
            for _ in range(3):
                with pytest.raises(DuplicateRequestCategoryError):
                    await f.categories.add(
                        ConsentRequestCategory(request_id=request.id, category_id=f.cbc_id)
                    )
            page = await f.requests.list_page_by_patient(f.patient_id, after=None, limit=10)
            assert [row.id for row in page] == [request.id]

    asyncio.run(scenario())


def test_get_active_respects_revocation_expiry_grantee_and_category() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            f = await _arrange(session)
            request = await _add_request(f)
            await f.categories.add(
                ConsentRequestCategory(request_id=request.id, category_id=f.cbc_id)
            )
            decision = await f.decisions.add(
                ConsentDecision(
                    request_id=request.id,
                    category_id=f.cbc_id,
                    status=ConsentDecisionStatus.APPROVED,
                )
            )
            grant = await f.grants.add(
                ConsentGrant(
                    decision_id=decision.id,
                    patient_id=f.patient_id,
                    grantee_doctor_id=f.doctor_id,
                    category_id=f.cbc_id,
                    expires_at=NOW + dt.timedelta(days=90),
                )
            )

            async def active(**overrides: object) -> bool:
                scope = {
                    "patient_id": f.patient_id,
                    "grantee_doctor_id": f.doctor_id,
                    "category_id": f.cbc_id,
                    "at": NOW,
                    **overrides,
                }
                return await f.grants.get_active(**scope) is not None  # type: ignore[arg-type]

            assert await active() is True
            assert await active(at=NOW + dt.timedelta(days=91)) is False  # expired
            assert await active(grantee_doctor_id=uuid4()) is False  # wrong grantee
            assert await active(category_id=f.mri_id) is False  # wrong category
            assert await active(patient_id=uuid4()) is False  # wrong patient
            grant.revoked_at = NOW
            await session.flush()
            assert await active() is False  # revoked

    asyncio.run(scenario())


def test_request_pages_walk_by_patient_and_by_requester_without_overlap() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            f = await _arrange(session)
            created = {(await _add_request(f, purpose=f"p{index}")).id for index in range(5)}

            listings = (
                (f.requests.list_page_by_patient, f.patient_id),
                (f.requests.list_page_by_requester, f.doctor_id),
            )
            for lister, scope in listings:
                seen: set[UUID] = set()
                after: CursorKey | None = None
                pages = 0
                while True:
                    rows = await lister(scope, after=after, limit=3)
                    page = rows[:2]
                    seen.update(row.id for row in page)
                    pages += 1
                    if len(rows) <= 2:
                        break
                    after = CursorKey(created_at=page[-1].created_at, item_id=page[-1].id)
                assert seen == created
                assert pages == 3  # 2 + 2 + 1

    asyncio.run(scenario())


def test_audit_pages_walk_on_occurred_at_newest_first() -> None:
    """The trail is ordered on the application-assigned event time, matching its index."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            f = await _arrange(session)
            for index in range(5):
                await f.audit.add(
                    AuditLog(
                        actor_user_id=f.doctor_user_id,
                        actor_role=Role.DOCTOR,
                        action=AuditAction.ACCESS_REQUESTED,
                        patient_id=f.patient_id,
                        occurred_at=NOW + dt.timedelta(seconds=index),
                        event_hash=f"{index:064d}",
                    )
                )
            first = await f.audit.list_page_by_patient(f.patient_id, after=None, limit=2)
            assert [row.occurred_at.second for row in first] == [4, 3]
            cursor = CursorKey(created_at=first[-1].occurred_at, item_id=first[-1].id)
            rest = await f.audit.list_page_by_patient(f.patient_id, after=cursor, limit=10)
            assert len(rest) == 3
            assert not {row.id for row in first} & {row.id for row in rest}

    asyncio.run(scenario())


def test_bounded_child_fetches_are_scoped_and_ordered() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            f = await _arrange(session)
            first, second = await _add_request(f), await _add_request(f)
            for category_id in (f.mri_id, f.cbc_id):
                await f.categories.add(
                    ConsentRequestCategory(request_id=first.id, category_id=category_id)
                )
            await f.categories.add(
                ConsentRequestCategory(request_id=second.id, category_id=f.cbc_id)
            )
            asked = await f.categories.list_by_request(first.id)
            assert [row.category_id for row in asked] == sorted([f.mri_id, f.cbc_id], key=str)
            assert len(await f.categories.list_by_request(second.id)) == 1
            assert await f.decisions.list_by_request(first.id) == []

    asyncio.run(scenario())


def test_unknown_ids_return_none_rather_than_raising() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            f = await _arrange(session)
            assert await f.requests.get_by_id(uuid4()) is None
            assert await f.decisions.get_by_id(uuid4()) is None
            assert await f.grants.get_by_id(uuid4()) is None

    asyncio.run(scenario())


def test_grant_history_pages_include_revoked_and_expired_rows() -> None:
    """The patient's "who has access" view is history, not the enforcement view."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            f = await _arrange(session)
            request = await _add_request(f)
            grants = []
            for category_id in (f.cbc_id, f.mri_id):
                await f.categories.add(
                    ConsentRequestCategory(request_id=request.id, category_id=category_id)
                )
                decision = await f.decisions.add(
                    ConsentDecision(
                        request_id=request.id,
                        category_id=category_id,
                        status=ConsentDecisionStatus.APPROVED,
                    )
                )
                grants.append(
                    await f.grants.add(
                        ConsentGrant(
                            decision_id=decision.id,
                            patient_id=f.patient_id,
                            grantee_doctor_id=f.doctor_id,
                            category_id=category_id,
                            expires_at=NOW + dt.timedelta(days=90),
                        )
                    )
                )
            grants[0].revoked_at = NOW
            await session.flush()

            page = await f.grants.list_page_by_patient(f.patient_id, after=None, limit=10)
            assert {row.id for row in page} == {row.id for row in grants}
            assert await f.grants.list_page_by_patient(uuid4(), after=None, limit=10) == []

    asyncio.run(scenario())


def test_active_category_ids_answer_the_same_predicate_get_active_does() -> None:
    """``list_active_category_ids`` is the scope form of ``get_active`` (ADR-020).

    The two must agree exactly, or a clinician listing would offer a record the read that
    follows it refuses — so revocation, expiry, the grantee and the patient are all tested
    against the set the same way they are tested against the single lookup.
    """

    async def scenario() -> None:
        async with sqlite_session() as session:
            f = await _arrange(session)
            request = await _add_request(f)

            async def grant(category_id: UUID, *, expires_at: dt.datetime) -> ConsentGrant:
                await f.categories.add(
                    ConsentRequestCategory(request_id=request.id, category_id=category_id)
                )
                decision = await f.decisions.add(
                    ConsentDecision(
                        request_id=request.id,
                        category_id=category_id,
                        status=ConsentDecisionStatus.APPROVED,
                    )
                )
                return await f.grants.add(
                    ConsentGrant(
                        decision_id=decision.id,
                        patient_id=f.patient_id,
                        grantee_doctor_id=f.doctor_id,
                        category_id=category_id,
                        expires_at=expires_at,
                    )
                )

            cbc_grant = await grant(f.cbc_id, expires_at=NOW + dt.timedelta(days=90))
            await grant(f.mri_id, expires_at=NOW - dt.timedelta(seconds=1))  # already expired

            async def scope(**overrides: object) -> set[UUID]:
                arguments = {
                    "patient_id": f.patient_id,
                    "grantee_doctor_id": f.doctor_id,
                    "at": NOW,
                    **overrides,
                }
                return set(await f.grants.list_active_category_ids(**arguments))  # type: ignore[arg-type]

            assert await scope() == {f.cbc_id}  # the expired MRI grant is absent
            assert await scope(at=NOW + dt.timedelta(days=91)) == set()  # both expired
            assert await scope(grantee_doctor_id=uuid4()) == set()  # wrong grantee
            assert await scope(patient_id=uuid4()) == set()  # wrong patient

            # The boundary matches get_active's strict `expires_at > at` exactly.
            assert await scope(at=cbc_grant.expires_at) == set()
            assert await scope(at=cbc_grant.expires_at - dt.timedelta(microseconds=1)) == {f.cbc_id}

            cbc_grant.revoked_at = NOW
            await session.flush()
            assert await scope() == set()  # revoked

    asyncio.run(scenario())


def test_active_category_ids_report_a_category_once_however_often_it_was_granted() -> None:
    """A category can be re-granted after an expiry, so several rows can cover it. The
    caller wants the category, not its history."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            f = await _arrange(session)
            for _ in range(2):
                request = await _add_request(f)
                await f.categories.add(
                    ConsentRequestCategory(request_id=request.id, category_id=f.cbc_id)
                )
                decision = await f.decisions.add(
                    ConsentDecision(
                        request_id=request.id,
                        category_id=f.cbc_id,
                        status=ConsentDecisionStatus.APPROVED,
                    )
                )
                await f.grants.add(
                    ConsentGrant(
                        decision_id=decision.id,
                        patient_id=f.patient_id,
                        grantee_doctor_id=f.doctor_id,
                        category_id=f.cbc_id,
                        expires_at=NOW + dt.timedelta(days=90),
                    )
                )

            found = await f.grants.list_active_category_ids(
                patient_id=f.patient_id, grantee_doctor_id=f.doctor_id, at=NOW
            )
            assert found == [f.cbc_id]

    asyncio.run(scenario())


# -- duplicate guards (authorization and audit correctness, 2026-10-15) ----------------


def test_open_category_ids_counts_only_unanswered_categories_of_open_requests() -> None:
    """Open = PENDING and unexpired; a category already answered on it is not open."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            f = await _arrange(session)
            request = await _add_request(f)
            for category_id in (f.cbc_id, f.mri_id):
                await f.categories.add(
                    ConsentRequestCategory(request_id=request.id, category_id=category_id)
                )
            await f.decisions.add(
                ConsentDecision(
                    request_id=request.id,
                    category_id=f.mri_id,
                    status=ConsentDecisionStatus.REJECTED,
                )
            )

            async def open_at(at: dt.datetime) -> set[UUID]:
                return await f.requests.open_category_ids(
                    patient_id=f.patient_id, requester_doctor_id=f.doctor_id, at=at
                )

            assert await open_at(NOW) == {f.cbc_id}
            # At the deadline the request is no longer open (expiry is `now >= expires_at`).
            assert await open_at(NOW + dt.timedelta(days=7)) == set()

            request.status = ConsentRequestStatus.EXPIRED
            await session.flush()
            assert await open_at(NOW) == set()

    asyncio.run(scenario())


def test_the_pair_lock_is_a_no_op_on_sqlite() -> None:
    """Only PostgreSQL takes an advisory lock; the harness must not fail on it."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            f = await _arrange(session)
            await f.requests.lock_pair(patient_id=f.patient_id, requester_doctor_id=f.doctor_id)

    asyncio.run(scenario())


def test_a_non_unique_integrity_failure_is_not_reported_as_a_duplicate() -> None:
    """Only a UNIQUE violation means "already recorded" (409). A grant pointing at a
    decision that does not exist is a foreign-key failure — a bug, not a duplicate — and
    must surface as itself."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            f = await _arrange(session)
            with pytest.raises(IntegrityError):
                await f.grants.add(
                    ConsentGrant(
                        decision_id=uuid4(),
                        patient_id=f.patient_id,
                        grantee_doctor_id=f.doctor_id,
                        category_id=f.cbc_id,
                        expires_at=NOW + dt.timedelta(days=90),
                    )
                )

    asyncio.run(scenario())
