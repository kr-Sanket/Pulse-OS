"""Doctor domain and service unit tests."""

import asyncio
from uuid import uuid4

import pytest
from app.modules.auth.accounts import UserAccountService
from app.modules.auth.domain import Role
from app.modules.auth.fake import FakeAuthProvider
from app.modules.auth.models import User
from app.modules.auth.repository import UserRepository
from app.modules.doctors.errors import (
    DoctorValidationError,
    DuplicateDoctorError,
    DuplicateRegistrationNumberError,
    InvalidDoctorUserError,
    InvalidHospitalError,
)
from app.modules.doctors.repository import DoctorRepository
from app.modules.doctors.service import DoctorService
from app.modules.hospitals.models import Hospital
from app.modules.hospitals.repository import HospitalRepository
from app.modules.hospitals.service import HospitalService
from sqlalchemy.ext.asyncio import AsyncSession

from tests.support import sqlite_session


def _make_doctor_service(session: AsyncSession) -> DoctorService:
    accounts = UserAccountService(UserRepository(session), FakeAuthProvider())
    hospitals = HospitalService(HospitalRepository(session))
    doctors = DoctorRepository(session)
    return DoctorService(doctors=doctors, accounts=accounts, hospitals=hospitals)


def test_create_doctor_success() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            users = UserRepository(session)
            doctor_user = await users.add(
                User(firebase_uid="fb-doc-1", role=Role.DOCTOR, email="doc@tmh.test")
            )

            hospitals = HospitalRepository(session)
            hospital = await hospitals.add(
                Hospital(hospital_id="HID-0001", name="Tata Main Hospital")
            )

            service = _make_doctor_service(session)
            doctor = await service.create_doctor(
                user_id=doctor_user.id,
                hospital_id=hospital.id,
                full_name="Dr. Aarti Sharma",
                registration_number="MCI-12345",
                specialty="Cardiology",
            )

            assert doctor.id is not None
            assert doctor.user_id == doctor_user.id
            assert doctor.hospital_id == hospital.id
            assert doctor.full_name == "Dr. Aarti Sharma"
            assert doctor.registration_number == "MCI-12345"
            assert doctor.specialty == "Cardiology"

            # Verify retrieval
            by_user = await service.get_by_user_id(doctor_user.id)
            assert by_user is not None and by_user.id == doctor.id

            by_id = await service.get_by_id(doctor.id)
            assert by_id is not None and by_id.registration_number == "MCI-12345"

            by_reg = await service.get_by_registration_number("MCI-12345")
            assert by_reg is not None and by_reg.id == doctor.id

    asyncio.run(scenario())


def test_list_doctors_by_hospital() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            users = UserRepository(session)
            doc1_user = await users.add(User(firebase_uid="fb-doc-1", role=Role.DOCTOR))
            doc2_user = await users.add(User(firebase_uid="fb-doc-2", role=Role.DOCTOR))
            doc3_user = await users.add(User(firebase_uid="fb-doc-3", role=Role.DOCTOR))

            hospitals = HospitalRepository(session)
            hosp1 = await hospitals.add(Hospital(hospital_id="HID-0001", name="Hospital 1"))
            hosp2 = await hospitals.add(Hospital(hospital_id="HID-0002", name="Hospital 2"))

            service = _make_doctor_service(session)
            await service.create_doctor(
                user_id=doc1_user.id,
                hospital_id=hosp1.id,
                full_name="Dr. B",
                registration_number="REG-1",
                specialty="Neurology",
            )
            await service.create_doctor(
                user_id=doc2_user.id,
                hospital_id=hosp1.id,
                full_name="Dr. A",
                registration_number="REG-2",
                specialty="Cardiology",
            )
            await service.create_doctor(
                user_id=doc3_user.id,
                hospital_id=hosp2.id,
                full_name="Dr. C",
                registration_number="REG-3",
                specialty="Pediatrics",
            )

            hosp1_docs = await service.list_by_hospital(hosp1.id)
            assert len(hosp1_docs) == 2
            assert hosp1_docs[0].full_name == "Dr. A"
            assert hosp1_docs[1].full_name == "Dr. B"

            hosp2_docs = await service.list_by_hospital(hosp2.id)
            assert len(hosp2_docs) == 1
            assert hosp2_docs[0].full_name == "Dr. C"

    asyncio.run(scenario())


def test_create_doctor_rejects_nonexistent_user() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            hospitals = HospitalRepository(session)
            hospital = await hospitals.add(Hospital(hospital_id="HID-0001", name="Hospital 1"))

            service = _make_doctor_service(session)
            with pytest.raises(InvalidDoctorUserError, match="User not found"):
                await service.create_doctor(
                    user_id=uuid4(),
                    hospital_id=hospital.id,
                    full_name="Dr. Aarti",
                    registration_number="REG-1",
                    specialty="Cardiology",
                )

    asyncio.run(scenario())


def test_create_doctor_rejects_non_doctor_roles() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            users = UserRepository(session)
            patient_user = await users.add(User(firebase_uid="fb-p", role=Role.PATIENT))
            admin_user = await users.add(User(firebase_uid="fb-adm", role=Role.HOSPITAL_ADMIN))
            sysadmin_user = await users.add(User(firebase_uid="fb-sys", role=Role.SYSTEM_ADMIN))

            hospitals = HospitalRepository(session)
            hospital = await hospitals.add(Hospital(hospital_id="HID-0001", name="Hospital 1"))

            service = _make_doctor_service(session)

            for non_doc_user in [patient_user, admin_user, sysadmin_user]:
                with pytest.raises(InvalidDoctorUserError, match="DOCTOR role"):
                    await service.create_doctor(
                        user_id=non_doc_user.id,
                        hospital_id=hospital.id,
                        full_name="Dr. Test",
                        registration_number=f"REG-{non_doc_user.id}",
                        specialty="General",
                    )

    asyncio.run(scenario())


def test_create_doctor_rejects_nonexistent_hospital() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            users = UserRepository(session)
            doctor_user = await users.add(User(firebase_uid="fb-doc", role=Role.DOCTOR))

            service = _make_doctor_service(session)
            with pytest.raises(InvalidHospitalError, match="Hospital not found"):
                await service.create_doctor(
                    user_id=doctor_user.id,
                    hospital_id=uuid4(),
                    full_name="Dr. Aarti",
                    registration_number="REG-1",
                    specialty="Cardiology",
                )

    asyncio.run(scenario())


def test_create_doctor_rejects_duplicate_user_relationship() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            users = UserRepository(session)
            doctor_user = await users.add(User(firebase_uid="fb-doc", role=Role.DOCTOR))

            hospitals = HospitalRepository(session)
            hosp1 = await hospitals.add(Hospital(hospital_id="HID-0001", name="Hospital 1"))
            hosp2 = await hospitals.add(Hospital(hospital_id="HID-0002", name="Hospital 2"))

            service = _make_doctor_service(session)
            await service.create_doctor(
                user_id=doctor_user.id,
                hospital_id=hosp1.id,
                full_name="Dr. Aarti",
                registration_number="REG-1",
                specialty="Cardiology",
            )

            # Second attempt for same user (even with different hospital or reg number) must fail
            with pytest.raises(DuplicateDoctorError):
                await service.create_doctor(
                    user_id=doctor_user.id,
                    hospital_id=hosp2.id,
                    full_name="Dr. Aarti Second",
                    registration_number="REG-2",
                    specialty="Neurology",
                )

    asyncio.run(scenario())


def test_create_doctor_rejects_duplicate_registration_number() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            users = UserRepository(session)
            doc1_user = await users.add(User(firebase_uid="fb-doc-1", role=Role.DOCTOR))
            doc2_user = await users.add(User(firebase_uid="fb-doc-2", role=Role.DOCTOR))

            hospitals = HospitalRepository(session)
            hospital = await hospitals.add(Hospital(hospital_id="HID-0001", name="Hospital 1"))

            service = _make_doctor_service(session)
            await service.create_doctor(
                user_id=doc1_user.id,
                hospital_id=hospital.id,
                full_name="Dr. One",
                registration_number="MCI-SHARED-123",
                specialty="Cardiology",
            )

            with pytest.raises(DuplicateRegistrationNumberError):
                await service.create_doctor(
                    user_id=doc2_user.id,
                    hospital_id=hospital.id,
                    full_name="Dr. Two",
                    registration_number="MCI-SHARED-123",
                    specialty="Pediatrics",
                )

    asyncio.run(scenario())


def test_doctor_validation_errors() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            service = _make_doctor_service(session)
            with pytest.raises(DoctorValidationError, match="full name"):
                await service.create_doctor(
                    user_id=uuid4(),
                    hospital_id=uuid4(),
                    full_name="   ",
                    registration_number="REG-1",
                    specialty="Cardiology",
                )
            with pytest.raises(DoctorValidationError, match="Registration number"):
                await service.create_doctor(
                    user_id=uuid4(),
                    hospital_id=uuid4(),
                    full_name="Dr. Name",
                    registration_number="   ",
                    specialty="Cardiology",
                )
            with pytest.raises(DoctorValidationError, match="Specialty"):
                await service.create_doctor(
                    user_id=uuid4(),
                    hospital_id=uuid4(),
                    full_name="Dr. Name",
                    registration_number="REG-1",
                    specialty="   ",
                )

    asyncio.run(scenario())
