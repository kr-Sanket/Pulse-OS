"""HospitalService unit tests: onboarding (ADR-015), verification, doctor management."""

import asyncio
from collections.abc import Iterator
from uuid import uuid4

import pytest
from app.modules.auth.accounts import UserAccountService
from app.modules.auth.domain import Role
from app.modules.auth.fake import FakeAuthProvider
from app.modules.auth.provider import VerifiedToken
from app.modules.auth.repository import UserRepository
from app.modules.auth.service import ROLE_CLAIM, USER_ID_CLAIM
from app.modules.records.errors import (
    DoctorNotFoundError,
    HidAllocationError,
    HospitalNotFoundError,
    HospitalNotVerifiedError,
    OrgRegistrationConflictError,
    ProfileNotFoundError,
)
from app.modules.records.models import DoctorStatus, HospitalVerificationStatus
from app.modules.records.organizations import HospitalService, generate_hid
from app.modules.records.repository import (
    DoctorRepository,
    HospitalAdminRepository,
    HospitalRepository,
)
from app.modules.records.seed import seed_reference_data
from sqlalchemy.ext.asyncio import AsyncSession

from tests.support import sqlite_session

ADMIN_IDENTITY = VerifiedToken(
    firebase_uid="fb-admin", claims={"email": "admin@example.test", "phone_number": "+911111111111"}
)
DOCTOR_IDENTITY = VerifiedToken(firebase_uid="fb-doc", claims={"email": "doc@example.test"})


def _service(
    session: AsyncSession,
    provider: FakeAuthProvider,
    hids: Iterator[str] | None = None,
) -> HospitalService:
    accounts = UserAccountService(UserRepository(session), provider)
    hospitals = HospitalRepository(session)
    admins = HospitalAdminRepository(session)
    doctors = DoctorRepository(session)
    if hids is None:
        return HospitalService(
            accounts=accounts, hospitals=hospitals, admins=admins, doctors=doctors
        )
    return HospitalService(
        accounts=accounts,
        hospitals=hospitals,
        admins=admins,
        doctors=doctors,
        hid_factory=lambda: next(hids),
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
            verified = await service.verify_hospital(outcome.hospital.hid.lower())  # sloppy input
            assert verified.verification_status is HospitalVerificationStatus.VERIFIED
            again = await service.verify_hospital(outcome.hospital.hid)
            assert again.verification_status is HospitalVerificationStatus.VERIFIED

            with pytest.raises(HospitalNotFoundError):
                await service.verify_hospital("HID-9999")

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
            await service.verify_hospital(admin.hospital.hid)
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
            await service.verify_hospital(h1.hospital.hid)

            verified_after = await service.list_hospitals(
                verification_status=HospitalVerificationStatus.VERIFIED
            )
            assert [h.hid for h in verified_after] == [h1.hospital.hid]

            pending_after = await service.list_hospitals(
                verification_status=HospitalVerificationStatus.PENDING
            )
            assert [h.hid for h in pending_after] == [h2.hospital.hid]

    asyncio.run(scenario())
