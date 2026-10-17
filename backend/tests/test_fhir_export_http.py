"""HTTP integration tests for GET /api/v1/records/export/fhir (FHIR-01).

Tests end-to-end endpoint authorization, consent gating, role boundaries,
canonical FHIR R4 Bundle assembly, subject validation, and audit trail integrity.
"""

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from app.modules.auth.domain import AuthenticatedUser, Role
from app.modules.auth.fake import FakeAuthProvider
from app.modules.auth.models import User
from app.modules.consent.dependencies import RecordsStaffDirectory
from app.modules.consent.models import AuditAction, AuditLog, ConsentGrant
from app.modules.consent.repository import (
    AuditLogRepository,
    ConsentDecisionRepository,
    ConsentGrantRepository,
    ConsentRequestCategoryRepository,
    ConsentRequestRepository,
)
from app.modules.consent.service import ConsentService
from app.modules.patients.directory import PatientDirectoryService
from app.modules.patients.models import Patient
from app.modules.patients.repository import PatientRepository
from app.modules.records.directory import staff_directory
from app.modules.records.fake import FakeObjectStorage
from app.modules.records.fhir_import import RosterEntry, SyntheaImporter
from app.modules.records.models import (
    Doctor,
    DoctorStatus,
    HospitalAdmin,
    MedicalRecord,
    RecordCategory,
    RecordOrigin,
)
from app.modules.records.repository import (
    HospitalRepository,
)
from app.modules.records.seed import seed_reference_data
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.support import FakeClinicianDirectory, run_with_session

EXPORT_URL = "/api/v1/records/export/fhir"
FIXTURES = Path(__file__).parent / "fixtures" / "fhir"
FIXTURE_ENTRY = RosterEntry(
    filename="canonical.json",
    synthea_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
    health_id="PHI-IND-2026-J0TA0DK",
    email="fixture999@synthea.pulseos.test",
    expected_name="Fixture999 Testcase999",
)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def test_env(
    client: TestClient,
    fake_auth: FakeAuthProvider,
    fake_storage: FakeObjectStorage,
    sqlite_db: None,
    db_engine: AsyncEngine,
) -> dict[str, Any]:
    """Arranges the test fixture with imported Synthea patient, doctors, hospital, and tokens."""

    async def arrange(session: AsyncSession) -> dict[str, Any]:
        await seed_reference_data(session)

        # Import canonical fixture bundle
        raw_bundle = (FIXTURES / "canonical.json").read_bytes()
        await SyntheaImporter(session, storage=fake_storage).import_bundle(
            FIXTURE_ENTRY, raw_bundle
        )

        patient_repo = PatientRepository(session)
        imported_patient = await patient_repo.get_by_health_id(FIXTURE_ENTRY.health_id)
        assert imported_patient is not None
        patient_user = await session.get(User, imported_patient.user_id)
        assert patient_user is not None

        # Get seeded verified hospital
        hospital_repo = HospitalRepository(session)
        hospital = await hospital_repo.get_by_hid("HID-0001")
        assert hospital is not None

        # Create active doctor
        doc_user = User(firebase_uid="fb-doc-export", role=Role.DOCTOR)
        session.add(doc_user)
        await session.flush()
        doctor = Doctor(
            user_id=doc_user.id,
            hospital_id=hospital.id,
            full_name="Dr Priya Sharma",
            registration_number="REG-EXP-1",
            status=DoctorStatus.ACTIVE,
        )
        session.add(doctor)

        # Create suspended doctor
        susp_user = User(firebase_uid="fb-doc-suspended", role=Role.DOCTOR)
        session.add(susp_user)
        await session.flush()
        susp_doc = Doctor(
            user_id=susp_user.id,
            hospital_id=hospital.id,
            full_name="Dr Suspended",
            registration_number="REG-EXP-2",
            status=DoctorStatus.DISABLED,
        )
        session.add(susp_doc)

        # Create hospital admin
        admin_user = User(firebase_uid="fb-admin-export", role=Role.HOSPITAL_ADMIN)
        session.add(admin_user)
        await session.flush()
        session.add(
            HospitalAdmin(
                user_id=admin_user.id, hospital_id=hospital.id, full_name="Hospital Admin"
            )
        )

        # Create system admin
        sys_user = User(firebase_uid="fb-sys-export", role=Role.SYSTEM_ADMIN)
        session.add(sys_user)

        # Create second patient owning no records
        other_user = User(firebase_uid="fb-other-patient", role=Role.PATIENT)
        session.add(other_user)
        await session.flush()
        session.add(
            Patient(
                user_id=other_user.id,
                health_id="PHI-IND-2026-OTHER01",
                full_name="Other Patient",
            )
        )

        await session.flush()

        # Record categories map
        cats = {c.code: c.id for c in (await session.execute(select(RecordCategory))).scalars()}

        return {
            "patient_user": patient_user,
            "patient": imported_patient,
            "doctor_user": doc_user,
            "doctor": doctor,
            "suspended_doctor_user": susp_user,
            "hospital_admin_user": admin_user,
            "system_admin_user": sys_user,
            "other_patient_user": other_user,
            "categories": cats,
        }

    data = run_with_session(db_engine, arrange)

    # Register users in fake_auth
    fake_auth.register_user(
        "patient",
        user_id=data["patient_user"].id,
        firebase_uid=data["patient_user"].firebase_uid,
        role=Role.PATIENT,
    )
    fake_auth.register_user(
        "doctor",
        user_id=data["doctor_user"].id,
        firebase_uid=data["doctor_user"].firebase_uid,
        role=Role.DOCTOR,
    )
    fake_auth.register_user(
        "suspended_doctor",
        user_id=data["suspended_doctor_user"].id,
        firebase_uid=data["suspended_doctor_user"].firebase_uid,
        role=Role.DOCTOR,
    )
    fake_auth.register_user(
        "hospital_admin",
        user_id=data["hospital_admin_user"].id,
        firebase_uid=data["hospital_admin_user"].firebase_uid,
        role=Role.HOSPITAL_ADMIN,
    )
    fake_auth.register_user(
        "system_admin",
        user_id=data["system_admin_user"].id,
        firebase_uid=data["system_admin_user"].firebase_uid,
        role=Role.SYSTEM_ADMIN,
    )
    fake_auth.register_user(
        "other_patient",
        user_id=data["other_patient_user"].id,
        firebase_uid=data["other_patient_user"].firebase_uid,
        role=Role.PATIENT,
    )

    headers = {
        "patient": _bearer("patient"),
        "doctor": _bearer("doctor"),
        "suspended_doctor": _bearer("suspended_doctor"),
        "hospital_admin": _bearer("hospital_admin"),
        "system_admin": _bearer("system_admin"),
        "other_patient": _bearer("other_patient"),
    }

    return {
        "data": data,
        "headers": headers,
        "client": client,
        "storage": fake_storage,
        "db_engine": db_engine,
    }


def _grant_categories(
    db_engine: AsyncEngine,
    *,
    doctor_user: User,
    doctor: Doctor,
    patient_user: User,
    health_id: str,
    category_ids: list[UUID],
) -> None:
    async def run(session: AsyncSession) -> None:
        patients = PatientRepository(session)
        clinicians = FakeClinicianDirectory()
        clinicians.register(doctor_user.id, doctor_id=doctor.id, hospital_id=doctor.hospital_id)
        clock = Clock(datetime(2026, 9, 7, 12, 0, tzinfo=UTC))

        service = ConsentService(
            requests=ConsentRequestRepository(session),
            request_categories=ConsentRequestCategoryRepository(session),
            decisions=ConsentDecisionRepository(session),
            grants=ConsentGrantRepository(session),
            audit=AuditLogRepository(session),
            patients=PatientDirectoryService(patients),
            clinicians=clinicians,
            staff=RecordsStaffDirectory(staff_directory(session)),
            clock=clock,
        )

        doc_actor = AuthenticatedUser(
            user_id=doctor_user.id, firebase_uid=doctor_user.firebase_uid, role=Role.DOCTOR
        )
        patient_actor = AuthenticatedUser(
            user_id=patient_user.id, firebase_uid=patient_user.firebase_uid, role=Role.PATIENT
        )

        view = await service.create_request(
            doc_actor,
            patient_health_id=health_id,
            category_ids=category_ids,
            purpose="export test",
        )
        await service.approve_categories(patient_actor, view.request.id, category_ids)

    run_with_session(db_engine, run)


# -- Patient Self-Export ----------------------------------------------------------------


def test_patient_self_export_success(test_env: dict[str, Any]) -> None:
    client: TestClient = test_env["client"]
    headers = test_env["headers"]["patient"]
    patient = test_env["data"]["patient"]

    response = client.get(EXPORT_URL, headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/fhir+json")

    bundle = response.json()
    assert bundle["resourceType"] == "Bundle"
    assert bundle["type"] == "collection"

    # Entry 0 must be Patient
    entries = bundle["entry"]
    assert len(entries) == 8  # 1 Patient + 7 imported records
    assert entries[0]["fullUrl"] == f"urn:uuid:{patient.id}"
    assert entries[0]["resource"]["resourceType"] == "Patient"
    assert entries[0]["resource"]["id"] == str(patient.id)

    # Validate that every clinical resource has resource-specific patient reference
    for entry in entries[1:]:
        res = entry["resource"]
        res_type = res["resourceType"]
        expected_ref = {"reference": f"urn:uuid:{patient.id}", "display": patient.full_name}
        assert expected_ref["reference"] == entries[0]["fullUrl"]
        if res_type in ("Condition", "Procedure", "MedicationRequest", "DiagnosticReport"):
            assert res["subject"] == expected_ref
            assert "patient" not in res
            if res_type == "DiagnosticReport" and "result" in res and res["result"]:
                assert "contained" in res
                contained_ids = {c["id"] for c in res["contained"] if isinstance(c, dict)}
                for r in res["result"]:
                    assert r["reference"].startswith("#")
                    assert r["reference"][1:] in contained_ids
        elif res_type in ("Immunization", "AllergyIntolerance"):
            assert res["patient"] == expected_ref
            assert "subject" not in res

    # Verify audit row
    async def verify_audit(session: AsyncSession) -> None:
        audit_rows = (
            (
                await session.execute(
                    select(AuditLog).where(AuditLog.action == AuditAction.RECORD_EXPORTED)
                )
            )
            .scalars()
            .all()
        )
        assert len(audit_rows) == 1
        row = audit_rows[0]
        assert row.patient_id == patient.id
        assert row.actor_user_id == test_env["data"]["patient_user"].id
        assert row.actor_role is Role.PATIENT
        assert row.target_record_id is None
        assert row.target_category_id is None
        assert row.target_request_id is None
        assert row.actor_hospital_id is None

    run_with_session(test_env["db_engine"], verify_audit)


def test_patient_cannot_supply_patient_health_id(test_env: dict[str, Any]) -> None:
    client: TestClient = test_env["client"]
    headers = test_env["headers"]["patient"]

    # Attempting to specify patientHealthId as a patient must be rejected
    response = client.get(f"{EXPORT_URL}?patientHealthId=PHI-IND-2026-OTHER01", headers=headers)
    assert response.status_code == 422
    problem = response.json()
    assert "patientHealthId must not be provided" in problem["detail"]


def test_patient_self_export_includes_hidden_records(test_env: dict[str, Any]) -> None:
    client: TestClient = test_env["client"]
    headers = test_env["headers"]["patient"]
    patient = test_env["data"]["patient"]

    # Mark one record as hidden
    async def hide_one(session: AsyncSession) -> None:
        record = (
            (
                await session.execute(
                    select(MedicalRecord).where(MedicalRecord.patient_id == patient.id)
                )
            )
            .scalars()
            .first()
        )
        assert record is not None
        record.is_hidden = True
        await session.flush()

    run_with_session(test_env["db_engine"], hide_one)

    response = client.get(EXPORT_URL, headers=headers)
    assert response.status_code == 200
    bundle = response.json()
    # Patient self-export retains all 7 records + 1 patient
    assert len(bundle["entry"]) == 8


# -- Doctor Export with Consent -------------------------------------------------------


def test_doctor_export_with_valid_consent_is_category_scoped(test_env: dict[str, Any]) -> None:
    client: TestClient = test_env["client"]
    headers = test_env["headers"]["doctor"]
    patient = test_env["data"]["patient"]
    doctor = test_env["data"]["doctor"]
    doctor_user = test_env["data"]["doctor_user"]
    patient_user = test_env["data"]["patient_user"]
    categories = test_env["data"]["categories"]

    # Grant ONLY "CONDITION" category
    _grant_categories(
        test_env["db_engine"],
        doctor_user=doctor_user,
        doctor=doctor,
        patient_user=patient_user,
        health_id=patient.health_id,
        category_ids=[categories["CONDITION"]],
    )

    response = client.get(f"{EXPORT_URL}?patientHealthId={patient.health_id}", headers=headers)
    assert response.status_code == 200
    bundle = response.json()

    # Entry 0 is Patient, Entry 1 is the single Condition record
    assert len(bundle["entry"]) == 2
    assert bundle["entry"][0]["resource"]["resourceType"] == "Patient"
    assert bundle["entry"][1]["resource"]["resourceType"] == "Condition"

    # Verify audit row has hospital attribution
    async def verify_audit(session: AsyncSession) -> None:
        audit_rows = (
            (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.action == AuditAction.RECORD_EXPORTED,
                        AuditLog.actor_role == Role.DOCTOR,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(audit_rows) == 1
        row = audit_rows[0]
        assert row.patient_id == patient.id
        assert row.actor_user_id == doctor_user.id
        assert row.actor_hospital_id == doctor.hospital_id

    run_with_session(test_env["db_engine"], verify_audit)


def test_doctor_export_excludes_hidden_records(test_env: dict[str, Any]) -> None:
    client: TestClient = test_env["client"]
    headers = test_env["headers"]["doctor"]
    patient = test_env["data"]["patient"]
    doctor = test_env["data"]["doctor"]
    doctor_user = test_env["data"]["doctor_user"]
    patient_user = test_env["data"]["patient_user"]
    categories = test_env["data"]["categories"]

    # Grant "CONDITION"
    _grant_categories(
        test_env["db_engine"],
        doctor_user=doctor_user,
        doctor=doctor,
        patient_user=patient_user,
        health_id=patient.health_id,
        category_ids=[categories["CONDITION"]],
    )

    # Now hide the condition
    async def hide_condition(session: AsyncSession) -> None:
        rec = (
            (
                await session.execute(
                    select(MedicalRecord).where(
                        MedicalRecord.patient_id == patient.id,
                        MedicalRecord.category_id == categories["CONDITION"],
                    )
                )
            )
            .scalars()
            .first()
        )
        assert rec is not None
        rec.is_hidden = True
        await session.flush()

    run_with_session(test_env["db_engine"], hide_condition)

    # Doctor exports: condition is hidden, so export is empty of clinical records
    response = client.get(f"{EXPORT_URL}?patientHealthId={patient.health_id}", headers=headers)
    assert response.status_code == 200
    bundle = response.json()
    assert len(bundle["entry"]) == 1  # Patient only
    assert bundle["entry"][0]["resource"]["resourceType"] == "Patient"


def test_doctor_export_without_consent_refused_and_audited(test_env: dict[str, Any]) -> None:
    client: TestClient = test_env["client"]
    headers = test_env["headers"]["doctor"]
    patient = test_env["data"]["patient"]

    # Doctor has NO grant for this patient
    response = client.get(f"{EXPORT_URL}?patientHealthId={patient.health_id}", headers=headers)
    assert response.status_code == 403

    # Verify ACCESS_DENIED was audited
    async def verify_denial(session: AsyncSession) -> None:
        denial_rows = (
            (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.action == AuditAction.ACCESS_DENIED,
                        AuditLog.patient_id == patient.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(denial_rows) >= 1

    run_with_session(test_env["db_engine"], verify_denial)


def test_doctor_export_with_revoked_consent_refused(test_env: dict[str, Any]) -> None:
    client: TestClient = test_env["client"]
    headers = test_env["headers"]["doctor"]
    patient = test_env["data"]["patient"]
    doctor = test_env["data"]["doctor"]
    doctor_user = test_env["data"]["doctor_user"]
    patient_user = test_env["data"]["patient_user"]
    categories = test_env["data"]["categories"]

    # Grant CONDITION
    _grant_categories(
        test_env["db_engine"],
        doctor_user=doctor_user,
        doctor=doctor,
        patient_user=patient_user,
        health_id=patient.health_id,
        category_ids=[categories["CONDITION"]],
    )

    # Revoke grant in place
    async def revoke(session: AsyncSession) -> None:
        grant = (
            await session.execute(
                select(ConsentGrant).where(
                    ConsentGrant.patient_id == patient.id,
                    ConsentGrant.grantee_doctor_id == doctor.id,
                )
            )
        ).scalar_one()
        grant.revoked_at = datetime.now(UTC)
        await session.flush()

    run_with_session(test_env["db_engine"], revoke)

    response = client.get(f"{EXPORT_URL}?patientHealthId={patient.health_id}", headers=headers)
    assert response.status_code == 403


def test_doctor_requires_patient_health_id(test_env: dict[str, Any]) -> None:
    client: TestClient = test_env["client"]
    headers = test_env["headers"]["doctor"]

    # Missing patientHealthId
    response = client.get(EXPORT_URL, headers=headers)
    assert response.status_code == 422


def test_suspended_doctor_rejected(test_env: dict[str, Any]) -> None:
    client: TestClient = test_env["client"]
    headers = test_env["headers"]["suspended_doctor"]
    patient = test_env["data"]["patient"]

    response = client.get(f"{EXPORT_URL}?patientHealthId={patient.health_id}", headers=headers)
    assert response.status_code == 403


# -- RBAC / Role Isolation -------------------------------------------------------------


def test_hospital_admin_rejected_with_403(test_env: dict[str, Any]) -> None:
    client: TestClient = test_env["client"]
    headers = test_env["headers"]["hospital_admin"]

    response = client.get(EXPORT_URL, headers=headers)
    assert response.status_code == 403


def test_system_admin_rejected_with_403(test_env: dict[str, Any]) -> None:
    client: TestClient = test_env["client"]
    headers = test_env["headers"]["system_admin"]

    response = client.get(EXPORT_URL, headers=headers)
    assert response.status_code == 403


def test_unauthenticated_request_rejected_with_401(test_env: dict[str, Any]) -> None:
    client: TestClient = test_env["client"]
    response = client.get(EXPORT_URL)
    assert response.status_code == 401


# -- Non-FHIR Exclusion & Empty Exports ------------------------------------------------


def test_non_fhir_documents_are_excluded_from_export(test_env: dict[str, Any]) -> None:
    client: TestClient = test_env["client"]
    headers = test_env["headers"]["patient"]
    patient = test_env["data"]["patient"]
    storage: FakeObjectStorage = test_env["storage"]

    # Add a PDF record directly
    async def add_pdf(session: AsyncSession) -> None:
        categories = test_env["data"]["categories"]
        pdf_rec = MedicalRecord(
            patient_id=patient.id,
            category_id=categories["LAB_REPORT"],
            origin=RecordOrigin.PATIENT_LOCKER,
            date_of_service=date(2026, 3, 1),
            original_filename="scan.pdf",
            content_type="application/pdf",
            size_bytes=10,
            s3_key=f"records/{patient.id}/pdf-rec-1",
        )
        session.add(pdf_rec)
        await session.flush()
        await storage.put_object(pdf_rec.s3_key, b"%PDF-1.4 ...", content_type="application/pdf")

    run_with_session(test_env["db_engine"], add_pdf)

    response = client.get(EXPORT_URL, headers=headers)
    assert response.status_code == 200
    bundle = response.json()
    # 1 Patient + 7 FHIR records (the PDF is excluded)
    assert len(bundle["entry"]) == 8
    for entry in bundle["entry"]:
        res_type = entry["resource"]["resourceType"]
        assert res_type in (
            "Patient",
            "Condition",
            "Procedure",
            "MedicationRequest",
            "DiagnosticReport",
            "Immunization",
            "AllergyIntolerance",
        )


def test_empty_export_for_patient_with_no_records(test_env: dict[str, Any]) -> None:
    client: TestClient = test_env["client"]
    headers = test_env["headers"]["other_patient"]

    response = client.get(EXPORT_URL, headers=headers)
    assert response.status_code == 200
    bundle = response.json()
    assert bundle["resourceType"] == "Bundle"
    assert len(bundle["entry"]) == 1
    assert bundle["entry"][0]["resource"]["resourceType"] == "Patient"


def test_doctor_export_with_expired_consent_refused(test_env: dict[str, Any]) -> None:
    client: TestClient = test_env["client"]
    headers = test_env["headers"]["doctor"]
    patient = test_env["data"]["patient"]
    doctor = test_env["data"]["doctor"]
    doctor_user = test_env["data"]["doctor_user"]
    patient_user = test_env["data"]["patient_user"]
    categories = test_env["data"]["categories"]

    _grant_categories(
        test_env["db_engine"],
        doctor_user=doctor_user,
        doctor=doctor,
        patient_user=patient_user,
        health_id=patient.health_id,
        category_ids=[categories["CONDITION"]],
    )

    async def expire(session: AsyncSession) -> None:
        grant = (
            await session.execute(
                select(ConsentGrant).where(
                    ConsentGrant.patient_id == patient.id,
                    ConsentGrant.grantee_doctor_id == doctor.id,
                )
            )
        ).scalar_one()
        grant.expires_at = datetime(2020, 1, 1, tzinfo=UTC)
        await session.flush()

    run_with_session(test_env["db_engine"], expire)

    response = client.get(f"{EXPORT_URL}?patientHealthId={patient.health_id}", headers=headers)
    assert response.status_code == 403


def test_failed_serialization_emits_no_record_exported_audit(test_env: dict[str, Any]) -> None:
    client: TestClient = test_env["client"]
    headers = test_env["headers"]["patient"]
    patient = test_env["data"]["patient"]
    storage: FakeObjectStorage = test_env["storage"]

    async def corrupt_payload(session: AsyncSession) -> None:
        rec = (
            (
                await session.execute(
                    select(MedicalRecord).where(MedicalRecord.patient_id == patient.id)
                )
            )
            .scalars()
            .first()
        )
        assert rec is not None
        await storage.put_object(rec.s3_key, b"THIS IS NOT JSON", content_type="application/json")

    run_with_session(test_env["db_engine"], corrupt_payload)

    response = client.get(EXPORT_URL, headers=headers)
    assert response.status_code == 500

    async def verify_no_export_audit(session: AsyncSession) -> None:
        export_rows = (
            (
                await session.execute(
                    select(AuditLog).where(AuditLog.action == AuditAction.RECORD_EXPORTED)
                )
            )
            .scalars()
            .all()
        )
        assert len(export_rows) == 0

    run_with_session(test_env["db_engine"], verify_no_export_audit)
