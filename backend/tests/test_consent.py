"""Consent domain, repository, and enforcement unit tests."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.modules.auth.accounts import UserAccountService
from app.modules.auth.domain import Role
from app.modules.auth.fake import FakeAuthProvider
from app.modules.auth.models import User
from app.modules.auth.repository import UserRepository
from app.modules.consent.errors import (
    AccessRequestNotFoundError,
    ConsentDeniedError,
    ConsentGrantNotFoundError,
    InvalidAccessRequestError,
    InvalidConsentStateError,
    UnauthorizedConsentActionError,
)
from app.modules.consent.models import (
    DecisionType,
    RequestStatus,
)
from app.modules.consent.repository import ConsentRepository
from app.modules.consent.schemas import CategoryDecisionItem
from app.modules.consent.service import ConsentService
from app.modules.doctors.models import Doctor
from app.modules.doctors.repository import DoctorRepository
from app.modules.doctors.service import DoctorService
from app.modules.hospitals.models import Hospital
from app.modules.hospitals.repository import HospitalRepository
from app.modules.hospitals.service import HospitalService
from app.modules.patients.models import Patient
from app.modules.patients.repository import PatientRepository
from app.modules.patients.service import PatientService
from app.modules.records.models import RecordCategory
from app.modules.records.repository import (
    MedicalRecordRepository,
    RecordCategoryRepository,
)
from app.modules.records.service import RecordService
from sqlalchemy.ext.asyncio import AsyncSession

from tests.support import sqlite_session


def _make_consent_service(session: AsyncSession) -> ConsentService:
    auth_provider = FakeAuthProvider()
    user_repo = UserRepository(session)
    accounts = UserAccountService(user_repo, auth_provider)

    patient_repo = PatientRepository(session)
    patients = PatientService(accounts=accounts, patients=patient_repo)

    hospital_repo = HospitalRepository(session)
    hospitals = HospitalService(hospital_repo)

    doctor_repo = DoctorRepository(session)
    doctors = DoctorService(doctors=doctor_repo, accounts=accounts, hospitals=hospitals)

    records = MedicalRecordRepository(session)
    categories = RecordCategoryRepository(session)
    record_service = RecordService(
        records=records,
        categories=categories,
        patients=patients,
        hospitals=hospitals,
        doctors=doctors,
    )

    consent_repo = ConsentRepository(session)

    return ConsentService(
        consent=consent_repo,
        accounts=accounts,
        patients=patients,
        doctors=doctors,
        hospitals=hospitals,
        records=record_service,
    )


async def _setup_fixture(
    session: AsyncSession,
) -> tuple[User, Patient, Hospital, User, Doctor, RecordCategory, RecordCategory]:
    """Helper to set up Patient, Hospital, Doctor, and 2 RecordCategories."""
    # 1. Patient
    u_pat = await UserRepository(session).add(User(firebase_uid="fb-pat", role=Role.PATIENT))
    patient = await PatientRepository(session).add(
        Patient(user_id=u_pat.id, health_id="PHI-IND-2026-7K3M99X", full_name="Asha Rao")
    )

    # 2. Hospital & Doctor
    hospital = await HospitalRepository(session).add(
        Hospital(hospital_id="HID-0001", name="Tata Main Hospital")
    )
    u_doc = await UserRepository(session).add(User(firebase_uid="fb-doc", role=Role.DOCTOR))
    doctor = await DoctorRepository(session).add(
        Doctor(
            user_id=u_doc.id,
            hospital_id=hospital.id,
            full_name="Dr. Sharma",
            registration_number="REG-101",
            specialty="Cardiology",
        )
    )

    # 3. Categories
    cat_repo = RecordCategoryRepository(session)
    cat_cbc = await cat_repo.add(RecordCategory(code="CBC", display_name="Blood Count"))
    cat_mri = await cat_repo.add(RecordCategory(code="MRI", display_name="MRI Scan"))

    return u_pat, patient, hospital, u_doc, doctor, cat_cbc, cat_mri


# --- AccessRequest Tests ---


def test_create_access_request_success() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            _, patient, hospital, u_doc, doctor, cat_cbc, cat_mri = await _setup_fixture(session)
            service = _make_consent_service(session)

            request = await service.create_access_request(
                doctor_user_id=u_doc.id,
                patient_id=patient.id,
                purpose="Pre-op evaluation for cardiac bypass",
                category_ids=[cat_cbc.id, cat_mri.id],
                expires_in_days=7,
            )

            assert request.id is not None
            assert request.patient_id == patient.id
            assert request.doctor_id == doctor.id
            assert request.hospital_id == hospital.id
            assert request.purpose == "Pre-op evaluation for cardiac bypass"
            assert request.status is RequestStatus.PENDING
            assert request.expires_at > datetime.now(UTC)

            # Check lookup
            fetched = await service.get_access_request(request.id)
            assert fetched is not None
            req_obj, cat_ids = fetched
            assert req_obj.id == request.id
            assert set(cat_ids) == {cat_cbc.id, cat_mri.id}

    asyncio.run(scenario())


def test_create_access_request_validation_failures() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            u_pat, patient, _, u_doc, _, cat_cbc, _ = await _setup_fixture(session)
            service = _make_consent_service(session)

            # 1. Blank purpose
            with pytest.raises(InvalidAccessRequestError, match="Purpose"):
                await service.create_access_request(
                    doctor_user_id=u_doc.id,
                    patient_id=patient.id,
                    purpose="   ",
                    category_ids=[cat_cbc.id],
                )

            # 2. Empty categories
            with pytest.raises(InvalidAccessRequestError, match="category"):
                await service.create_access_request(
                    doctor_user_id=u_doc.id,
                    patient_id=patient.id,
                    purpose="Valid purpose",
                    category_ids=[],
                )

            # 3. Non-doctor user creating request
            with pytest.raises(UnauthorizedConsentActionError):
                await service.create_access_request(
                    doctor_user_id=u_pat.id,  # Patient role
                    patient_id=patient.id,
                    purpose="Valid purpose",
                    category_ids=[cat_cbc.id],
                )

            # 4. Non-existent patient
            with pytest.raises(InvalidAccessRequestError, match="patient"):
                await service.create_access_request(
                    doctor_user_id=u_doc.id,
                    patient_id=uuid4(),
                    purpose="Valid purpose",
                    category_ids=[cat_cbc.id],
                )

            # 5. Non-existent category
            with pytest.raises(InvalidAccessRequestError, match="category"):
                await service.create_access_request(
                    doctor_user_id=u_doc.id,
                    patient_id=patient.id,
                    purpose="Valid purpose",
                    category_ids=[uuid4()],
                )

    asyncio.run(scenario())


# --- Decision & Grant Tests ---


def test_patient_decision_creates_immutable_history_and_active_grants() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            u_pat, patient, _, u_doc, doctor, cat_cbc, cat_mri = await _setup_fixture(session)
            service = _make_consent_service(session)

            request = await service.create_access_request(
                doctor_user_id=u_doc.id,
                patient_id=patient.id,
                purpose="Cardiology review",
                category_ids=[cat_cbc.id, cat_mri.id],
            )

            # Patient approves CBC but rejects MRI
            custom_expiry = datetime.now(UTC) + timedelta(days=30)
            decisions = [
                CategoryDecisionItem(
                    category_id=cat_cbc.id,
                    decision=DecisionType.APPROVED,
                    expires_at=custom_expiry,
                ),
                CategoryDecisionItem(
                    category_id=cat_mri.id,
                    decision=DecisionType.REJECTED,
                ),
            ]

            updated_req, dec_list, grant_list = await service.decide_access_request(
                patient_user_id=u_pat.id,
                request_id=request.id,
                decisions=decisions,
            )

            assert updated_req.status is RequestStatus.DECIDED
            assert len(dec_list) == 2
            assert len(grant_list) == 1

            # Assert decisions are recorded immutably
            cbc_dec = next(d for d in dec_list if d.category_id == cat_cbc.id)
            assert cbc_dec.decision is DecisionType.APPROVED
            mri_dec = next(d for d in dec_list if d.category_id == cat_mri.id)
            assert mri_dec.decision is DecisionType.REJECTED

            # Assert active grant was spawned for CBC with custom expiry
            cbc_grant = grant_list[0]
            assert cbc_grant.patient_id == patient.id
            assert cbc_grant.doctor_id == doctor.id
            assert cbc_grant.category_id == cat_cbc.id
            assert cbc_grant.decision_id == cbc_dec.id
            assert cbc_grant.revoked_at is None
            assert cbc_grant.expires_at == custom_expiry

            # Check active grant lookup
            active_cbc = await service.get_active_grant(
                patient_id=patient.id, doctor_id=doctor.id, category_id=cat_cbc.id
            )
            assert active_cbc is not None
            assert active_cbc.id == cbc_grant.id

            # Check that rejected MRI has NO active grant
            active_mri = await service.get_active_grant(
                patient_id=patient.id, doctor_id=doctor.id, category_id=cat_mri.id
            )
            assert active_mri is None

    asyncio.run(scenario())


def test_patient_decision_validation_and_ownership() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            u_pat1, patient1, _, u_doc, _, cat_cbc, cat_mri = await _setup_fixture(session)

            # Another patient
            u_pat2 = await UserRepository(session).add(
                User(firebase_uid="fb-pat-2", role=Role.PATIENT)
            )
            await PatientRepository(session).add(
                Patient(user_id=u_pat2.id, health_id="PHI-IND-2026-9999999", full_name="Other")
            )

            service = _make_consent_service(session)
            request = await service.create_access_request(
                doctor_user_id=u_doc.id,
                patient_id=patient1.id,
                purpose="Review",
                category_ids=[cat_cbc.id, cat_mri.id],
            )

            # 1. Non-patient user trying to decide
            with pytest.raises(UnauthorizedConsentActionError):
                await service.decide_access_request(
                    patient_user_id=u_doc.id,
                    request_id=request.id,
                    decisions=[
                        CategoryDecisionItem(category_id=cat_cbc.id, decision=DecisionType.APPROVED)
                    ],
                )

            # 2. Patient 2 trying to decide Patient 1's request
            with pytest.raises(UnauthorizedConsentActionError):
                await service.decide_access_request(
                    patient_user_id=u_pat2.id,
                    request_id=request.id,
                    decisions=[
                        CategoryDecisionItem(category_id=cat_cbc.id, decision=DecisionType.APPROVED)
                    ],
                )

            # 3. Incomplete decisions (only 1 of 2 requested categories provided)
            with pytest.raises(InvalidConsentStateError, match="All requested categories"):
                await service.decide_access_request(
                    patient_user_id=u_pat1.id,
                    request_id=request.id,
                    decisions=[
                        CategoryDecisionItem(category_id=cat_cbc.id, decision=DecisionType.APPROVED)
                    ],
                )

            # 4. Non-existent request
            with pytest.raises(AccessRequestNotFoundError):
                await service.decide_access_request(
                    patient_user_id=u_pat1.id,
                    request_id=uuid4(),
                    decisions=[
                        CategoryDecisionItem(category_id=cat_cbc.id, decision=DecisionType.APPROVED)
                    ],
                )

    asyncio.run(scenario())


def test_consent_revocation_stops_enforcement_immediately() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            u_pat, patient, _, u_doc, doctor, cat_cbc, _ = await _setup_fixture(session)
            service = _make_consent_service(session)

            request = await service.create_access_request(
                doctor_user_id=u_doc.id,
                patient_id=patient.id,
                purpose="Cardiology review",
                category_ids=[cat_cbc.id],
            )
            await service.decide_access_request(
                patient_user_id=u_pat.id,
                request_id=request.id,
                decisions=[
                    CategoryDecisionItem(category_id=cat_cbc.id, decision=DecisionType.APPROVED)
                ],
            )

            # Verified active before revocation
            assert (
                await service.enforce(
                    requester_user_id=u_doc.id,
                    patient_id=patient.id,
                    category_id=cat_cbc.id,
                )
                is True
            )

            # Patient revokes consent
            revoked_grant = await service.revoke_consent(
                patient_user_id=u_pat.id,
                doctor_id=doctor.id,
                category_id=cat_cbc.id,
            )
            assert revoked_grant.revoked_at is not None

            # Immediate denial on next enforce() attempt
            with pytest.raises(ConsentDeniedError, match="no active consent grant"):
                await service.enforce(
                    requester_user_id=u_doc.id,
                    patient_id=patient.id,
                    category_id=cat_cbc.id,
                )

            # Revoking already-revoked grant raises error
            with pytest.raises(ConsentGrantNotFoundError):
                await service.revoke_consent(
                    patient_user_id=u_pat.id,
                    doctor_id=doctor.id,
                    category_id=cat_cbc.id,
                )

    asyncio.run(scenario())


# --- Comprehensive Enforcement Choke Point Tests ---


def test_enforce_patient_self_access_allowed() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            u_pat, patient, _, _, _, cat_cbc, _ = await _setup_fixture(session)
            service = _make_consent_service(session)

            # Patient reading own records passes trivially (ADR-013)
            assert (
                await service.enforce(
                    requester_user_id=u_pat.id,
                    patient_id=patient.id,
                    category_id=cat_cbc.id,
                )
                is True
            )

    asyncio.run(scenario())


def test_enforce_cross_patient_access_denied() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            u_pat1, _, _, _, _, cat_cbc, _ = await _setup_fixture(session)

            # Patient 2
            u_pat2 = await UserRepository(session).add(
                User(firebase_uid="fb-pat-2", role=Role.PATIENT)
            )
            p2 = await PatientRepository(session).add(
                Patient(user_id=u_pat2.id, health_id="PHI-IND-2026-8888888", full_name="Patient 2")
            )

            service = _make_consent_service(session)

            # Patient 1 attempting to access Patient 2's records
            with pytest.raises(ConsentDeniedError, match="Patient cannot access another patient"):
                await service.enforce(
                    requester_user_id=u_pat1.id,
                    patient_id=p2.id,
                    category_id=cat_cbc.id,
                )

    asyncio.run(scenario())


def test_enforce_granular_category_and_doctor_scoping() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            u_pat, patient, hospital, u_doc1, doctor1, cat_cbc, cat_mri = await _setup_fixture(
                session
            )

            # Doctor 2
            u_doc2 = await UserRepository(session).add(
                User(firebase_uid="fb-doc-2", role=Role.DOCTOR)
            )
            doctor2 = await DoctorRepository(session).add(
                Doctor(
                    user_id=u_doc2.id,
                    hospital_id=hospital.id,
                    full_name="Dr. Second",
                    registration_number="REG-202",
                    specialty="Neurology",
                )
            )

            service = _make_consent_service(session)

            # Doctor 1 requests CBC and MRI -> Patient approves only CBC
            req = await service.create_access_request(
                doctor_user_id=u_doc1.id,
                patient_id=patient.id,
                purpose="Review",
                category_ids=[cat_cbc.id, cat_mri.id],
            )
            await service.decide_access_request(
                patient_user_id=u_pat.id,
                request_id=req.id,
                decisions=[
                    CategoryDecisionItem(category_id=cat_cbc.id, decision=DecisionType.APPROVED),
                    CategoryDecisionItem(category_id=cat_mri.id, decision=DecisionType.REJECTED),
                ],
            )

            # 1. Doctor 1 + CBC -> ALLOWED
            assert (
                await service.enforce(
                    requester_user_id=u_doc1.id,
                    patient_id=patient.id,
                    category_id=cat_cbc.id,
                )
                is True
            )
            assert (
                await service.enforce_doctor_access(
                    doctor_id=doctor1.id,
                    patient_id=patient.id,
                    category_id=cat_cbc.id,
                )
            ) is not None

            # 2. Doctor 1 + MRI -> DENIED (rejected category)
            with pytest.raises(ConsentDeniedError, match="no active consent grant"):
                await service.enforce(
                    requester_user_id=u_doc1.id,
                    patient_id=patient.id,
                    category_id=cat_mri.id,
                )

            # 3. Doctor 2 + CBC -> DENIED (grant is scoped to Doctor 1, not hospital)
            with pytest.raises(ConsentDeniedError, match="no active consent grant"):
                await service.enforce(
                    requester_user_id=u_doc2.id,
                    patient_id=patient.id,
                    category_id=cat_cbc.id,
                )
            with pytest.raises(ConsentDeniedError):
                await service.enforce_doctor_access(
                    doctor_id=doctor2.id,
                    patient_id=patient.id,
                    category_id=cat_cbc.id,
                )

    asyncio.run(scenario())


def test_enforce_system_admin_strictly_denied() -> None:
    """Security Invariant (ADR-013, SECURITY.md):
    System Admin has zero access to medical content. No break-glass bypass exists.
    """

    async def scenario() -> None:
        async with sqlite_session() as session:
            _, patient, _, _, _, cat_cbc, _ = await _setup_fixture(session)

            u_admin = await UserRepository(session).add(
                User(firebase_uid="fb-sysadmin", role=Role.SYSTEM_ADMIN)
            )

            service = _make_consent_service(session)

            with pytest.raises(
                ConsentDeniedError, match="System administrators are strictly forbidden"
            ):
                await service.enforce(
                    requester_user_id=u_admin.id,
                    patient_id=patient.id,
                    category_id=cat_cbc.id,
                )

    asyncio.run(scenario())


def test_enforce_hospital_admin_denied_via_consent() -> None:
    """Security Invariant: Hospital Admin cannot access medical content through consent."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            _, patient, _, _, _, cat_cbc, _ = await _setup_fixture(session)

            u_hosp_admin = await UserRepository(session).add(
                User(firebase_uid="fb-hospadmin", role=Role.HOSPITAL_ADMIN)
            )

            service = _make_consent_service(session)

            with pytest.raises(ConsentDeniedError, match="Hospital administrators cannot access"):
                await service.enforce(
                    requester_user_id=u_hosp_admin.id,
                    patient_id=patient.id,
                    category_id=cat_cbc.id,
                )

    asyncio.run(scenario())


def test_enforce_expired_grant_denied() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            u_pat, patient, _, u_doc, _, cat_cbc, _ = await _setup_fixture(session)
            service = _make_consent_service(session)

            req = await service.create_access_request(
                doctor_user_id=u_doc.id,
                patient_id=patient.id,
                purpose="Review",
                category_ids=[cat_cbc.id],
            )

            # Grant expired 1 hour ago
            past_expiry = datetime.now(UTC) - timedelta(hours=1)
            await service.decide_access_request(
                patient_user_id=u_pat.id,
                request_id=req.id,
                decisions=[
                    CategoryDecisionItem(
                        category_id=cat_cbc.id,
                        decision=DecisionType.APPROVED,
                        expires_at=past_expiry,
                    )
                ],
            )

            with pytest.raises(ConsentDeniedError, match="no active consent grant"):
                await service.enforce(
                    requester_user_id=u_doc.id,
                    patient_id=patient.id,
                    category_id=cat_cbc.id,
                )

    asyncio.run(scenario())
