"""HospitalService unit tests: onboarding (ADR-015), verification, doctor management."""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from app.modules.auth.accounts import UserAccountService
from app.modules.auth.domain import Role
from app.modules.auth.fake import FakeAuthProvider
from app.modules.auth.models import User
from app.modules.auth.provider import VerifiedToken
from app.modules.auth.repository import UserRepository
from app.modules.auth.service import ROLE_CLAIM, USER_ID_CLAIM
from app.modules.records.errors import (
    DoctorNotFoundError,
    HidAllocationError,
    HospitalNotFoundError,
    HospitalNotVerifiedError,
    InvalidHospitalStatusTransitionError,
    OrgRegistrationConflictError,
    ProfileNotFoundError,
)
from app.modules.records.models import (
    DoctorStatus,
    Hospital,
    HospitalAuditLog,
    HospitalLifecycleAction,
    HospitalVerificationStatus,
)
from app.modules.records.organizations import (
    HospitalLifecycleAuditor,
    HospitalService,
    generate_hid,
)
from app.modules.records.repository import (
    DoctorRepository,
    HospitalAdminRepository,
    HospitalRepository,
)
from app.modules.records.seed import seed_reference_data
from app.shared.pagination import CursorKey
from sqlalchemy.ext.asyncio import AsyncSession

from tests.support import sqlite_session

ADMIN_IDENTITY = VerifiedToken(
    firebase_uid="fb-admin", claims={"email": "admin@example.test", "phone_number": "+911111111111"}
)
DOCTOR_IDENTITY = VerifiedToken(firebase_uid="fb-doc", claims={"email": "doc@example.test"})


class FakeHospitalLifecycleAuditor:
    def __init__(self) -> None:
        self.events: list[tuple[UUID, UUID, HospitalLifecycleAction, str | None]] = []
        self.logs: list[HospitalAuditLog] = []

    async def record_lifecycle_event(
        self,
        *,
        hospital_id: UUID,
        actor_user_id: UUID,
        action: HospitalLifecycleAction,
        reason: str | None = None,
    ) -> HospitalAuditLog:
        self.events.append((hospital_id, actor_user_id, action, reason))
        log = HospitalAuditLog(
            hospital_id=hospital_id,
            actor_user_id=actor_user_id,
            action=action,
            reason=reason,
            occurred_at=datetime.now(UTC),
        )
        self.logs.append(log)
        return log

    async def list_by_hospital_id(
        self,
        hospital_id: UUID,
        *,
        after: CursorKey | None = None,
        limit: int | None = None,
    ) -> list[HospitalAuditLog]:
        filtered = [e for e in self.logs if e.hospital_id == hospital_id]
        sorted_logs = sorted(filtered, key=lambda x: (x.occurred_at, x.id), reverse=True)
        if after is not None:
            sorted_logs = [
                e
                for e in sorted_logs
                if (e.occurred_at < after.created_at)
                or (e.occurred_at == after.created_at and e.id < after.item_id)
            ]
        if limit is not None:
            sorted_logs = sorted_logs[:limit]
        return sorted_logs


def _service(
    session: AsyncSession,
    provider: FakeAuthProvider,
    hids: Iterator[str] | None = None,
    auditor: HospitalLifecycleAuditor | None = None,
) -> HospitalService:
    accounts = UserAccountService(UserRepository(session), provider)
    hospitals = HospitalRepository(session)
    admins = HospitalAdminRepository(session)
    doctors = DoctorRepository(session)
    if hids is None:
        return HospitalService(
            accounts=accounts,
            hospitals=hospitals,
            admins=admins,
            doctors=doctors,
            auditor=auditor,
        )
    return HospitalService(
        accounts=accounts,
        hospitals=hospitals,
        admins=admins,
        doctors=doctors,
        hid_factory=lambda: next(hids),
        auditor=auditor,
    )


def test_generate_hid_shape() -> None:
    for _ in range(50):
        hid = generate_hid()
        assert len(hid) == 8 and hid.startswith("HID-") and hid[4:].isdigit()


def test_register_hospital_creates_everything_and_provisions_claims() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            provider = FakeAuthProvider()
            outcome = await _service(session, provider).register_hospital(
                ADMIN_IDENTITY,
                hospital_name="Sunrise Clinic",
                hospital_address="Pune",
                admin_full_name="Rita Admin",
            )
            assert outcome.created is True
            assert outcome.hospital.verification_status is HospitalVerificationStatus.PENDING
            assert outcome.admin.hospital_id == outcome.hospital.id

            user = await UserRepository(session).get_by_firebase_uid("fb-admin")
            assert user is not None and user.role is Role.HOSPITAL_ADMIN
            assert user.email == "admin@example.test"
            claims = provider.custom_claims["fb-admin"]
            assert claims[ROLE_CLAIM] == "HOSPITAL_ADMIN"
            assert str(claims[USER_ID_CLAIM]) == str(user.id)

    asyncio.run(scenario())


def test_register_hospital_is_idempotent_and_never_creates_a_second_hospital() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            provider = FakeAuthProvider()
            service = _service(session, provider)
            first = await service.register_hospital(
                ADMIN_IDENTITY, hospital_name="A", hospital_address=None, admin_full_name="R"
            )
            second = await service.register_hospital(
                ADMIN_IDENTITY, hospital_name="B", hospital_address=None, admin_full_name="S"
            )
            assert second.created is False
            assert second.hospital.id == first.hospital.id
            assert second.hospital.name == "A"  # repeat call changes nothing

    asyncio.run(scenario())


def test_register_hospital_conflicts_with_a_different_role() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            provider = FakeAuthProvider()
            accounts = UserAccountService(UserRepository(session), provider)
            await accounts.create_user(firebase_uid="fb-admin", role=Role.PATIENT)
            with pytest.raises(OrgRegistrationConflictError):
                await _service(session, provider).register_hospital(
                    ADMIN_IDENTITY, hospital_name="A", hospital_address=None, admin_full_name="R"
                )

    asyncio.run(scenario())


def test_hid_collision_redraws_and_exhaustion_fails() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            provider = FakeAuthProvider()
            taken_then_fresh = iter(["HID-0009", "HID-0009", "HID-0042"])
            service = _service(session, provider, hids=taken_then_fresh)
            first = await service.register_hospital(
                ADMIN_IDENTITY, hospital_name="A", hospital_address=None, admin_full_name="R"
            )
            assert first.hospital.hid == "HID-0009"

            other = VerifiedToken(firebase_uid="fb-admin-2", claims={})
            second = await service.register_hospital(
                other, hospital_name="B", hospital_address=None, admin_full_name="S"
            )
            assert second.hospital.hid == "HID-0042"  # collided once, redrew

        async with sqlite_session() as session:
            provider = FakeAuthProvider()
            always_taken = iter(["HID-0001"] * 20)
            service = _service(session, provider, hids=always_taken)
            await service.register_hospital(
                ADMIN_IDENTITY, hospital_name="A", hospital_address=None, admin_full_name="R"
            )
            with pytest.raises(HidAllocationError):
                await service.register_hospital(
                    VerifiedToken(firebase_uid="fb-x", claims={}),
                    hospital_name="B",
                    hospital_address=None,
                    admin_full_name="S",
                )

    asyncio.run(scenario())


def test_verify_hospital_is_idempotent_and_404s_unknown() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            provider = FakeAuthProvider()
            service = _service(session, provider)
            outcome = await service.register_hospital(
                ADMIN_IDENTITY, hospital_name="A", hospital_address=None, admin_full_name="R"
            )
            admin_1_id = uuid4()
            admin_2_id = uuid4()
            await UserRepository(session).add(
                User(id=admin_1_id, firebase_uid="fb-sys-1", role=Role.SYSTEM_ADMIN)
            )
            await UserRepository(session).add(
                User(id=admin_2_id, firebase_uid="fb-sys-2", role=Role.SYSTEM_ADMIN)
            )

            # 1. Verification records administrator UUID and UTC timestamp
            verified = await service.verify_hospital(
                outcome.hospital.hid.lower(), verifier_user_id=admin_1_id
            )
            assert verified.verification_status is HospitalVerificationStatus.VERIFIED
            assert verified.verified_by_user_id == admin_1_id
            assert verified.verified_at is not None
            assert verified.verified_at.tzinfo is not None
            first_verified_at = verified.verified_at

            # 2. Repeated verification preserves original verifier UUID and timestamp (idempotency)
            again = await service.verify_hospital(outcome.hospital.hid, verifier_user_id=admin_2_id)
            assert again.verification_status is HospitalVerificationStatus.VERIFIED
            assert again.verified_by_user_id == admin_1_id
            # The locked re-read refreshes the row from the database (populate_existing), and
            # SQLite hands timestamps back naive; the instant itself must be unchanged.
            assert again.verified_at is not None
            assert again.verified_at.replace(tzinfo=UTC) == first_verified_at

            # 3. 404 for unknown hospital
            with pytest.raises(HospitalNotFoundError):
                await service.verify_hospital("HID-9999", verifier_user_id=admin_1_id)

            # 4. Legacy already-VERIFIED hospital without attribution is not falsely attributed
            legacy_hospital = await HospitalRepository(session).add(
                Hospital(
                    id=uuid4(),
                    hid="HID-0050",
                    name="Legacy Hospital",
                    address="Legacy Way",
                    verification_status=HospitalVerificationStatus.VERIFIED,
                )
            )
            assert legacy_hospital.verified_by_user_id is None
            assert legacy_hospital.verified_at is None

            re_verify = await service.verify_hospital(
                legacy_hospital.hid, verifier_user_id=admin_2_id
            )
            assert re_verify.verification_status is HospitalVerificationStatus.VERIFIED
            assert re_verify.verified_by_user_id is None
            assert re_verify.verified_at is None

            # 5. Existing hospitals with NULL metadata remain readable in list_hospitals
            hospitals = await service.list_hospitals()
            hids = {h.hid for h in hospitals}
            assert outcome.hospital.hid in hids
            assert "HID-0050" in hids

    asyncio.run(scenario())


def test_register_doctor_requires_a_verified_hospital() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            provider = FakeAuthProvider()
            service = _service(session, provider)
            pending = await service.register_hospital(
                ADMIN_IDENTITY, hospital_name="A", hospital_address=None, admin_full_name="R"
            )
            with pytest.raises(HospitalNotVerifiedError):
                await service.register_doctor(
                    DOCTOR_IDENTITY,
                    full_name="Dr. D",
                    specialty=None,
                    registration_number="R-1",
                    hospital_hid=pending.hospital.hid,
                )
            with pytest.raises(HospitalNotFoundError):
                await service.register_doctor(
                    DOCTOR_IDENTITY,
                    full_name="Dr. D",
                    specialty=None,
                    registration_number="R-1",
                    hospital_hid="HID-9999",
                )

    asyncio.run(scenario())


def test_register_doctor_happy_path_is_pending_and_idempotent() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            provider = FakeAuthProvider()
            await seed_reference_data(session)  # HID-0001..3 arrive VERIFIED
            service = _service(session, provider)
            first = await service.register_doctor(
                DOCTOR_IDENTITY,
                full_name="Dr. D",
                specialty="Cardiology",
                registration_number="R-1",
                hospital_hid="hid-0001",  # sloppy case tolerated
            )
            assert first.created is True
            assert first.doctor.status is DoctorStatus.PENDING
            assert first.hospital.hid == "HID-0001"
            assert provider.custom_claims["fb-doc"][ROLE_CLAIM] == "DOCTOR"

            second = await service.register_doctor(
                DOCTOR_IDENTITY,
                full_name="Someone Else",
                specialty=None,
                registration_number="R-2",
                hospital_hid="HID-0002",
            )
            assert second.created is False
            assert second.doctor.id == first.doctor.id
            assert second.hospital.hid == "HID-0001"  # affiliation unchanged by repeats

    asyncio.run(scenario())


def test_doctor_management_is_scoped_to_the_admins_hospital() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            provider = FakeAuthProvider()
            await seed_reference_data(session)
            service = _service(session, provider)
            admin = await service.register_hospital(
                ADMIN_IDENTITY, hospital_name="Mine", hospital_address=None, admin_full_name="R"
            )
            sys_admin_id = uuid4()
            await UserRepository(session).add(
                User(id=sys_admin_id, firebase_uid="fb-sys-doc-manage", role=Role.SYSTEM_ADMIN)
            )
            await service.verify_hospital(admin.hospital.hid, verifier_user_id=sys_admin_id)
            mine = await service.register_doctor(
                DOCTOR_IDENTITY,
                full_name="Dr. Mine",
                specialty=None,
                registration_number="R-1",
                hospital_hid=admin.hospital.hid,
            )
            elsewhere = await service.register_doctor(
                VerifiedToken(firebase_uid="fb-doc-2", claims={}),
                full_name="Dr. Elsewhere",
                specialty=None,
                registration_number="R-2",
                hospital_hid="HID-0001",
            )
            admin_user = await UserRepository(session).get_by_firebase_uid("fb-admin")
            assert admin_user is not None

            page = await service.list_own_hospital_doctors(admin_user.id, after=None, limit=10)
            assert [d.full_name for d in page.doctors] == ["Dr. Mine"]
            assert page.next_cursor is None

            activated = await service.set_doctor_status(
                admin_user.id, mine.doctor.id, DoctorStatus.ACTIVE
            )
            assert activated.status is DoctorStatus.ACTIVE

            # Another hospital's doctor is indistinguishable from a nonexistent one.
            with pytest.raises(DoctorNotFoundError):
                await service.set_doctor_status(
                    admin_user.id, elsewhere.doctor.id, DoctorStatus.DISABLED
                )
            with pytest.raises(DoctorNotFoundError):
                await service.set_doctor_status(admin_user.id, uuid4(), DoctorStatus.ACTIVE)

    asyncio.run(scenario())


def test_profile_lookups_without_rows_raise_profile_not_found() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            provider = FakeAuthProvider()
            service = _service(session, provider)
            with pytest.raises(ProfileNotFoundError):
                await service.get_own_hospital(uuid4())
            with pytest.raises(ProfileNotFoundError):
                await service.get_own_doctor_profile(uuid4())
            with pytest.raises(ProfileNotFoundError):
                await service.list_own_hospital_doctors(uuid4(), after=None, limit=10)

    asyncio.run(scenario())


def test_list_hospitals_empty_and_filtered() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            provider = FakeAuthProvider()
            service = _service(session, provider)

            # Initially empty
            assert await service.list_hospitals() == []

            # Register hospital 1 (PENDING)
            h1 = await service.register_hospital(
                VerifiedToken(firebase_uid="fb-h1", claims={}),
                hospital_name="Hospital Alpha",
                hospital_address="Alpha Street",
                admin_full_name="Admin One",
            )
            # Register hospital 2 (PENDING)
            h2 = await service.register_hospital(
                VerifiedToken(firebase_uid="fb-h2", claims={}),
                hospital_name="Hospital Beta",
                hospital_address="Beta Street",
                admin_full_name="Admin Two",
            )

            all_hospitals = await service.list_hospitals()
            assert len(all_hospitals) == 2
            assert {h.hid for h in all_hospitals} == {h1.hospital.hid, h2.hospital.hid}

            pending_only = await service.list_hospitals(
                verification_status=HospitalVerificationStatus.PENDING
            )
            assert len(pending_only) == 2

            verified_only = await service.list_hospitals(
                verification_status=HospitalVerificationStatus.VERIFIED
            )
            assert len(verified_only) == 0

            # Verify hospital 1
            sys_admin_id = uuid4()
            await UserRepository(session).add(
                User(id=sys_admin_id, firebase_uid="fb-sys-list-hosp", role=Role.SYSTEM_ADMIN)
            )
            await service.verify_hospital(h1.hospital.hid, verifier_user_id=sys_admin_id)

            verified_after = await service.list_hospitals(
                verification_status=HospitalVerificationStatus.VERIFIED
            )
            assert [h.hid for h in verified_after] == [h1.hospital.hid]

            pending_after = await service.list_hospitals(
                verification_status=HospitalVerificationStatus.PENDING
            )
            assert [h.hid for h in pending_after] == [h2.hospital.hid]

    asyncio.run(scenario())


def test_hospital_rejection_flow_and_idempotency() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            provider = FakeAuthProvider()
            auditor = FakeHospitalLifecycleAuditor()
            service = _service(session, provider, auditor=auditor)

            # Register hospital (starts PENDING)
            outcome = await service.register_hospital(
                ADMIN_IDENTITY,
                hospital_name="Pending Clinic",
                hospital_address="Goa",
                admin_full_name="Sam Admin",
            )
            assert outcome.hospital.verification_status is HospitalVerificationStatus.PENDING

            admin_user_id = uuid4()
            await UserRepository(session).add(
                User(id=admin_user_id, firebase_uid="fb-sys-reject", role=Role.SYSTEM_ADMIN)
            )

            # 1. PENDING -> REJECTED with reason
            rejected = await service.reject_hospital(
                outcome.hospital.hid,
                actor_user_id=admin_user_id,
                reason="Incomplete medical registration documentation.",
            )
            assert rejected.verification_status is HospitalVerificationStatus.REJECTED
            assert len(auditor.events) == 1
            h_id, actor_id, action, reason = auditor.events[0]
            assert h_id == outcome.hospital.id
            assert actor_id == admin_user_id
            assert action is HospitalLifecycleAction.REJECTED
            assert reason == "Incomplete medical registration documentation."

            # 2. Idempotent repeated rejection does not add duplicate audit event
            again = await service.reject_hospital(
                outcome.hospital.hid,
                actor_user_id=admin_user_id,
                reason="Different reason that should be ignored on idempotency",
            )
            assert again.verification_status is HospitalVerificationStatus.REJECTED
            assert len(auditor.events) == 1

            # 3. 404 for unknown hospital
            with pytest.raises(HospitalNotFoundError):
                await service.reject_hospital("HID-9999", actor_user_id=admin_user_id)

    asyncio.run(scenario())


def test_hospital_rejection_is_terminal() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            provider = FakeAuthProvider()
            auditor = FakeHospitalLifecycleAuditor()
            service = _service(session, provider, auditor=auditor)

            outcome = await service.register_hospital(
                ADMIN_IDENTITY,
                hospital_name="Terminal Clinic",
                hospital_address="Kerala",
                admin_full_name="Rita Admin",
            )
            admin_user_id = uuid4()
            await UserRepository(session).add(
                User(id=admin_user_id, firebase_uid="fb-sys-term", role=Role.SYSTEM_ADMIN)
            )

            await service.reject_hospital(outcome.hospital.hid, actor_user_id=admin_user_id)
            assert outcome.hospital.verification_status is HospitalVerificationStatus.REJECTED

            # REJECTED -> VERIFIED is prohibited (rejection is terminal)
            with pytest.raises(InvalidHospitalStatusTransitionError) as exc_info:
                await service.verify_hospital(outcome.hospital.hid, verifier_user_id=admin_user_id)
            assert exc_info.value.current_status is HospitalVerificationStatus.REJECTED
            assert exc_info.value.target_status is HospitalVerificationStatus.VERIFIED

            # REJECTED -> SUSPENDED is prohibited
            with pytest.raises(InvalidHospitalStatusTransitionError) as exc_info:
                await service.suspend_hospital(outcome.hospital.hid, actor_user_id=admin_user_id)
            assert exc_info.value.current_status is HospitalVerificationStatus.REJECTED
            assert exc_info.value.target_status is HospitalVerificationStatus.SUSPENDED

            # REJECTED -> REINSTATED is prohibited
            with pytest.raises(InvalidHospitalStatusTransitionError) as exc_info:
                await service.reinstate_hospital(outcome.hospital.hid, actor_user_id=admin_user_id)
            assert exc_info.value.current_status is HospitalVerificationStatus.REJECTED
            assert exc_info.value.target_status is HospitalVerificationStatus.VERIFIED

            # Only the initial rejection event was written
            assert len(auditor.events) == 1
            assert auditor.events[0][2] is HospitalLifecycleAction.REJECTED

    asyncio.run(scenario())


def test_hospital_suspension_and_reinstatement_flow() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            provider = FakeAuthProvider()
            auditor = FakeHospitalLifecycleAuditor()
            service = _service(session, provider, auditor=auditor)

            outcome = await service.register_hospital(
                ADMIN_IDENTITY,
                hospital_name="Active Clinic",
                hospital_address="Delhi",
                admin_full_name="Dev Admin",
            )
            admin_1_id = uuid4()
            admin_2_id = uuid4()
            await UserRepository(session).add(
                User(id=admin_1_id, firebase_uid="fb-sys-susp-1", role=Role.SYSTEM_ADMIN)
            )
            await UserRepository(session).add(
                User(id=admin_2_id, firebase_uid="fb-sys-susp-2", role=Role.SYSTEM_ADMIN)
            )

            # 1. PENDING -> VERIFIED
            verified = await service.verify_hospital(
                outcome.hospital.hid, verifier_user_id=admin_1_id
            )
            assert verified.verification_status is HospitalVerificationStatus.VERIFIED
            assert verified.verified_by_user_id == admin_1_id
            assert len(auditor.events) == 1
            assert auditor.events[0][2] is HospitalLifecycleAction.VERIFIED

            # 2. VERIFIED -> SUSPENDED with reason
            suspended = await service.suspend_hospital(
                outcome.hospital.hid,
                actor_user_id=admin_2_id,
                reason="Temporary compliance review.",
            )
            assert suspended.verification_status is HospitalVerificationStatus.SUSPENDED
            assert len(auditor.events) == 2
            assert auditor.events[1][2] is HospitalLifecycleAction.SUSPENDED
            assert auditor.events[1][3] == "Temporary compliance review."
            # Initial verification attribution is preserved
            assert suspended.verified_by_user_id == admin_1_id

            # 3. Idempotent suspension does not duplicate audit event
            again_susp = await service.suspend_hospital(
                outcome.hospital.hid, actor_user_id=admin_2_id
            )
            assert again_susp.verification_status is HospitalVerificationStatus.SUSPENDED
            assert len(auditor.events) == 2

            # 4. SUSPENDED -> VERIFIED via reinstate_hospital records REINSTATED
            reinstated = await service.reinstate_hospital(
                outcome.hospital.hid,
                actor_user_id=admin_1_id,
                reason="Compliance review passed.",
            )
            assert reinstated.verification_status is HospitalVerificationStatus.VERIFIED
            assert len(auditor.events) == 3
            assert auditor.events[2][2] is HospitalLifecycleAction.REINSTATED
            assert auditor.events[2][3] == "Compliance review passed."
            assert reinstated.verified_by_user_id == admin_1_id

            # 5. Idempotent reinstatement returns VERIFIED without duplicate audit event
            again_reinstate = await service.reinstate_hospital(
                outcome.hospital.hid, actor_user_id=admin_1_id
            )
            assert again_reinstate.verification_status is HospitalVerificationStatus.VERIFIED
            assert len(auditor.events) == 3

            # 6. Reinstatement via verify_hospital on SUSPENDED also records REINSTATED
            await service.suspend_hospital(outcome.hospital.hid, actor_user_id=admin_2_id)
            assert len(auditor.events) == 4
            assert auditor.events[3][2] is HospitalLifecycleAction.SUSPENDED

            re_via_verify = await service.verify_hospital(
                outcome.hospital.hid, verifier_user_id=admin_1_id
            )
            assert re_via_verify.verification_status is HospitalVerificationStatus.VERIFIED
            assert len(auditor.events) == 5
            assert auditor.events[4][2] is HospitalLifecycleAction.REINSTATED

    asyncio.run(scenario())


def test_prohibited_transitions() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            provider = FakeAuthProvider()
            auditor = FakeHospitalLifecycleAuditor()
            service = _service(session, provider, auditor=auditor)

            outcome = await service.register_hospital(
                ADMIN_IDENTITY,
                hospital_name="Rules Clinic",
                hospital_address="Mumbai",
                admin_full_name="Raj Admin",
            )
            sys_admin_id = uuid4()
            await UserRepository(session).add(
                User(id=sys_admin_id, firebase_uid="fb-sys-rules", role=Role.SYSTEM_ADMIN)
            )

            # PENDING -> SUSPENDED is prohibited
            with pytest.raises(InvalidHospitalStatusTransitionError) as exc_info:
                await service.suspend_hospital(outcome.hospital.hid, actor_user_id=sys_admin_id)
            assert exc_info.value.current_status is HospitalVerificationStatus.PENDING
            assert exc_info.value.target_status is HospitalVerificationStatus.SUSPENDED

            # PENDING -> REINSTATED is prohibited
            with pytest.raises(InvalidHospitalStatusTransitionError) as exc_info:
                await service.reinstate_hospital(outcome.hospital.hid, actor_user_id=sys_admin_id)
            assert exc_info.value.current_status is HospitalVerificationStatus.PENDING
            assert exc_info.value.target_status is HospitalVerificationStatus.VERIFIED

            # Move to VERIFIED
            await service.verify_hospital(outcome.hospital.hid, verifier_user_id=sys_admin_id)

            # VERIFIED -> REJECTED is prohibited
            with pytest.raises(InvalidHospitalStatusTransitionError) as exc_info:
                await service.reject_hospital(outcome.hospital.hid, actor_user_id=sys_admin_id)
            assert exc_info.value.current_status is HospitalVerificationStatus.VERIFIED
            assert exc_info.value.target_status is HospitalVerificationStatus.REJECTED

            # Move to SUSPENDED
            await service.suspend_hospital(outcome.hospital.hid, actor_user_id=sys_admin_id)

            # SUSPENDED -> REJECTED is prohibited
            with pytest.raises(InvalidHospitalStatusTransitionError) as exc_info:
                await service.reject_hospital(outcome.hospital.hid, actor_user_id=sys_admin_id)
            assert exc_info.value.current_status is HospitalVerificationStatus.SUSPENDED
            assert exc_info.value.target_status is HospitalVerificationStatus.REJECTED

    asyncio.run(scenario())


def test_reason_handling_and_normalization() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            provider = FakeAuthProvider()
            auditor = FakeHospitalLifecycleAuditor()
            service = _service(session, provider, auditor=auditor)

            outcome = await service.register_hospital(
                ADMIN_IDENTITY,
                hospital_name="Reason Clinic",
                hospital_address="Kolkata",
                admin_full_name="Anu Admin",
            )
            sys_admin_id = uuid4()
            await UserRepository(session).add(
                User(id=sys_admin_id, firebase_uid="fb-sys-reason", role=Role.SYSTEM_ADMIN)
            )

            # Whitespace string normalizes to None
            await service.reject_hospital(
                outcome.hospital.hid, actor_user_id=sys_admin_id, reason="   \t\n  "
            )
            assert auditor.events[0][3] is None

            # Reason exceeding 255 chars raises ValueError
            h2 = await service.register_hospital(
                VerifiedToken(firebase_uid="fb-h-long", claims={}),
                hospital_name="Long Reason Clinic",
                hospital_address=None,
                admin_full_name="Admin L",
            )
            with pytest.raises(ValueError, match="must not exceed 255 characters"):
                await service.reject_hospital(
                    h2.hospital.hid, actor_user_id=sys_admin_id, reason="x" * 256
                )

    asyncio.run(scenario())


def test_suspended_and_pending_hospitals_block_doctor_activation() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            provider = FakeAuthProvider()
            service = _service(session, provider)

            admin = await service.register_hospital(
                ADMIN_IDENTITY, hospital_name="Hospital", hospital_address=None, admin_full_name="A"
            )
            admin_user = await UserRepository(session).get_by_firebase_uid("fb-admin")
            assert admin_user is not None
            sys_admin_id = uuid4()
            await UserRepository(session).add(
                User(id=sys_admin_id, firebase_uid="fb-sys-doc-manage-2", role=Role.SYSTEM_ADMIN)
            )

            # 1. PENDING hospital cannot activate doctors
            with pytest.raises(HospitalNotVerifiedError):
                await service.set_doctor_status(admin_user.id, uuid4(), DoctorStatus.ACTIVE)

            # 2. Verify hospital
            await service.verify_hospital(admin.hospital.hid, verifier_user_id=sys_admin_id)

            # Register a doctor
            doc = await service.register_doctor(
                DOCTOR_IDENTITY,
                full_name="Dr. Test",
                specialty="General",
                registration_number="REG-100",
                hospital_hid=admin.hospital.hid,
            )

            # Now activation succeeds
            activated = await service.set_doctor_status(
                admin_user.id, doc.doctor.id, DoctorStatus.ACTIVE
            )
            assert activated.status is DoctorStatus.ACTIVE

            # 3. Suspend hospital
            await service.suspend_hospital(admin.hospital.hid, actor_user_id=sys_admin_id)

            # Activation is blocked for suspended hospital
            with pytest.raises(HospitalNotVerifiedError):
                await service.set_doctor_status(admin_user.id, doc.doctor.id, DoctorStatus.ACTIVE)

            # Deactivation remains possible during suspension (ADR-034 review correction)
            deactivated = await service.set_doctor_status(
                admin_user.id, doc.doctor.id, DoctorStatus.DISABLED
            )
            assert deactivated.status is DoctorStatus.DISABLED

            # Existing validation/isolation rules remain intact during suspension
            # (404 for unknown doctor)
            with pytest.raises(DoctorNotFoundError):
                await service.set_doctor_status(admin_user.id, uuid4(), DoctorStatus.DISABLED)

            # Activation remains blocked during suspension
            with pytest.raises(HospitalNotVerifiedError):
                await service.set_doctor_status(admin_user.id, doc.doctor.id, DoctorStatus.ACTIVE)

            # 4. Reinstate hospital -> activation succeeds again
            await service.reinstate_hospital(admin.hospital.hid, actor_user_id=sys_admin_id)
            re_activated = await service.set_doctor_status(
                admin_user.id, doc.doctor.id, DoctorStatus.ACTIVE
            )
            assert re_activated.status is DoctorStatus.ACTIVE

    asyncio.run(scenario())


def test_auditor_failure_propagates_cleanly() -> None:
    class FailingAuditor:
        async def record_lifecycle_event(
            self,
            *,
            hospital_id: UUID,
            actor_user_id: UUID,
            action: HospitalLifecycleAction,
            reason: str | None = None,
        ) -> None:
            raise RuntimeError("Database connection lost during audit write")

        async def list_by_hospital_id(
            self,
            hospital_id: UUID,
            *,
            after: CursorKey | None = None,
            limit: int | None = None,
        ) -> list[HospitalAuditLog]:
            return []

    async def scenario() -> None:
        async with sqlite_session() as session:
            provider = FakeAuthProvider()
            service = _service(session, provider, auditor=FailingAuditor())

            outcome = await service.register_hospital(
                ADMIN_IDENTITY,
                hospital_name="Failing Clinic",
                hospital_address=None,
                admin_full_name="Failing Admin",
            )
            sys_admin_id = uuid4()
            await UserRepository(session).add(
                User(id=sys_admin_id, firebase_uid="fb-sys-fail", role=Role.SYSTEM_ADMIN)
            )

            with pytest.raises(RuntimeError, match="Database connection lost"):
                await service.verify_hospital(outcome.hospital.hid, verifier_user_id=sys_admin_id)
            assert outcome.hospital.verification_status is HospitalVerificationStatus.PENDING

            with pytest.raises(RuntimeError, match="Database connection lost"):
                await service.reject_hospital(outcome.hospital.hid, actor_user_id=sys_admin_id)
            assert outcome.hospital.verification_status is HospitalVerificationStatus.PENDING

    asyncio.run(scenario())
