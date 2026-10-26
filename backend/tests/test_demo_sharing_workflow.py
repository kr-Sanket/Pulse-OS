"""Demo workflow C — patient-controlled sharing, end to end over HTTP (docs/DEMO_GUIDE.md).

One test walks the whole script the demo guide describes, against the real ``create_app()``
router set with only the external providers faked (auth, object storage, queue):

    patient uploads a synthetic PDF to their own locker → a clinician at another hospital
    asks for three categories → the patient approves two and rejects one → the clinician
    lists, opens and downloads only what was approved, and exports a FHIR Bundle scoped to
    the same categories (uploaded file bytes never in it) → the patient revokes → every
    clinician path is refused → the patient's own audit trail (read through the patient API)
    shows the grant, the accesses, the revocation and the refusals.

The patient is the Synthea fixture (imported exactly as ``scripts/import_synthea.py`` does),
so FHIR resources exist to export; the clinician is the seeded demo doctor at CMC Vellore
(``seed_demo_staff``), the identity the guide tells the presenter to sign in as. Narrower
properties (rate limits, hidden records, suspension, export edge cases) are pinned in
``test_m3_gate.py`` and ``test_fhir_export_http.py``; this file pins the sequence.
"""

import base64
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from app.core.queue import InMemoryJobQueue
from app.modules.auth.domain import Role
from app.modules.auth.fake import FakeAuthProvider
from app.modules.auth.models import User
from app.modules.patients.repository import PatientRepository
from app.modules.records.fake import FakeObjectStorage
from app.modules.records.fhir_import import RosterEntry, SyntheaImporter
from app.modules.records.seed import seed_demo_staff, seed_reference_data
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.pdf_fixtures import text_pdf
from tests.support import run_with_session

RECORDS = "/api/v1/records"
EXPORT = "/api/v1/records/export/fhir"
REQUESTS = "/api/v1/access-requests"
GRANTS = "/api/v1/consent-grants"
GRANTED_RECORDS = "/api/v1/granted-records"
AUDIT = "/api/v1/audit-logs"

FIXTURE = Path(__file__).parent / "fixtures" / "fhir" / "canonical.json"
ENTRY = RosterEntry(
    filename="canonical.json",
    synthea_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
    health_id="PHI-IND-2026-J0TA0DK",
    email="fixture999@synthea.pulseos.test",
    expected_name="Fixture999 Testcase999",
)
HEALTH_ID = ENTRY.health_id
DEMO_DOCTOR_UID = "synthetic:doctor:hid-0002"  # Dr. Thomas George (Demo), CMC Vellore

# A line that exists only inside the uploaded file: if it ever appears in an export, the
# uploaded bytes leaked into the Bundle.
FILE_ONLY_MARKER = "DEMO-UPLOAD-ONLY Ferritin 8 ng/mL"
LAB_PDF = text_pdf(["Synthetic lab report (demo)", FILE_ONLY_MARKER])
MRI_PDF = text_pdf(["Synthetic MRI report (demo)", "No acute abnormality"])


@dataclass
class Demo:
    patient: dict[str, str]
    doctor: dict[str, str]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def demo(
    client: TestClient,
    fake_auth: FakeAuthProvider,
    sqlite_db: None,
    db_engine: AsyncEngine,
    fake_storage: FakeObjectStorage,
    fake_queue: InMemoryJobQueue,
) -> Demo:
    async def arrange(session: AsyncSession) -> dict[str, Any]:
        await seed_reference_data(session)
        await seed_demo_staff(session)
        await SyntheaImporter(session, storage=fake_storage).import_bundle(
            ENTRY, FIXTURE.read_bytes()
        )
        patient = await PatientRepository(session).get_by_health_id(HEALTH_ID)
        assert patient is not None
        patient_user = await session.get(User, patient.user_id)
        doctor_user = (
            await session.execute(select(User).where(User.firebase_uid == DEMO_DOCTOR_UID))
        ).scalar_one()
        assert patient_user is not None
        return {"patient": patient_user, "doctor": doctor_user}

    users = run_with_session(db_engine, arrange)
    fake_auth.register_user(
        "patient",
        user_id=users["patient"].id,
        firebase_uid=users["patient"].firebase_uid,
        role=Role.PATIENT,
    )
    fake_auth.register_user(
        "doctor",
        user_id=users["doctor"].id,
        firebase_uid=DEMO_DOCTOR_UID,
        role=Role.DOCTOR,
    )
    return Demo(patient=_bearer("patient"), doctor=_bearer("doctor"))


def _upload_to_locker(client: TestClient, demo: Demo, code: str, name: str, data: bytes) -> str:
    response: httpx.Response = client.post(
        RECORDS,
        data={"categoryCode": code, "dateOfService": "2026-09-01"},
        files={"file": (name, data, "application/pdf")},
        headers=demo.patient,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["origin"] == "PATIENT_LOCKER"
    assert body["processingStatus"] == "UPLOADED"  # indexing is the worker's job (workflow D)
    return str(body["id"])


def _export_resource_types(response: httpx.Response) -> Counter[str]:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/fhir+json")
    bundle = response.json()
    assert bundle["resourceType"] == "Bundle"
    return Counter(entry["resource"]["resourceType"] for entry in bundle["entry"])


def _assert_no_uploaded_bytes(response: httpx.Response) -> None:
    """Uploaded binaries are never embedded: not as text, not base64, not as attachments."""
    text = response.text
    assert FILE_ONLY_MARKER not in text
    for data in (LAB_PDF, MRI_PDF):
        assert base64.b64encode(data).decode()[:64] not in text
    assert "%PDF" not in text
    resource_types = {entry["resource"]["resourceType"] for entry in response.json()["entry"]}
    assert resource_types.isdisjoint({"Binary", "DocumentReference", "Media"})


def _patient_trail(client: TestClient, demo: Demo) -> list[str]:
    response = client.get(AUDIT, params={"limit": 100}, headers=demo.patient)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["nextCursor"] is None
    return [item["action"] for item in body["items"]]


def test_workflow_c_patient_controlled_sharing_end_to_end(
    client: TestClient, demo: Demo, fake_queue: InMemoryJobQueue
) -> None:
    # 1. The patient uploads two synthetic PDFs to their own locker.
    lab_pdf = _upload_to_locker(client, demo, "LAB_REPORT", "lab-demo.pdf", LAB_PDF)
    mri_pdf = _upload_to_locker(client, demo, "MRI", "mri-demo.pdf", MRI_PDF)
    assert [task for task, _ in fake_queue.jobs] == ["record_uploaded", "record_uploaded"]

    # Before any consent, the clinician sees that categories exist — and nothing else.
    existence = client.get(
        f"{RECORDS}/existence", params={"patientHealthId": HEALTH_ID}, headers=demo.doctor
    )
    assert existence.status_code == 200, existence.text
    assert {"LAB_REPORT", "MRI", "CONDITION"} <= {i["code"] for i in existence.json()["items"]}
    assert client.get(f"{RECORDS}/{lab_pdf}", headers=demo.doctor).status_code == 404
    refused_export = client.get(EXPORT, params={"patientHealthId": HEALTH_ID}, headers=demo.doctor)
    assert refused_export.status_code == 403

    # 2. Consent request → per-category patient decision: approve two, reject one.
    asked = client.post(
        REQUESTS,
        json={
            "patientHealthId": HEALTH_ID,
            "categoryCodes": ["LAB_REPORT", "CONDITION", "MRI"],
            "purpose": "Cardiology referral (demo)",
        },
        headers=demo.doctor,
    )
    assert asked.status_code == 201, asked.text
    request_id = asked.json()["id"]
    inbox = client.get(f"{REQUESTS}/inbox", headers=demo.patient).json()["items"]
    assert [item["id"] for item in inbox] == [request_id]

    approved = client.post(
        f"{REQUESTS}/{request_id}/approve",
        json={"categoryCodes": ["LAB_REPORT", "CONDITION"]},
        headers=demo.patient,
    )
    assert approved.status_code == 200, approved.text
    grant_ids = [grant["id"] for grant in approved.json()["grants"]]
    assert len(grant_ids) == 2
    rejected = client.post(
        f"{REQUESTS}/{request_id}/reject", json={"categoryCodes": ["MRI"]}, headers=demo.patient
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["requestStatus"] == "DECIDED"

    # 3. The clinician reads through the real backend — authorized categories only.
    listed = client.get(
        GRANTED_RECORDS, params={"patientHealthId": HEALTH_ID}, headers=demo.doctor
    ).json()
    assert sorted(c["code"] for c in listed["grantedCategories"]) == ["CONDITION", "LAB_REPORT"]
    assert {item["categoryCode"] for item in listed["items"]} == {"CONDITION", "LAB_REPORT"}
    assert lab_pdf in {item["id"] for item in listed["items"]}
    assert mri_pdf not in {item["id"] for item in listed["items"]}

    opened = client.get(f"{RECORDS}/{lab_pdf}", headers=demo.doctor)
    assert opened.status_code == 200, opened.text
    assert opened.json()["originalFilename"] == "lab-demo.pdf"
    assert client.post(f"{RECORDS}/{lab_pdf}/download-url", headers=demo.doctor).status_code == 200
    assert client.get(f"{RECORDS}/{mri_pdf}", headers=demo.doctor).status_code == 404

    # 7 (while granted). The clinician's FHIR export is scoped to the two granted
    # categories — the Synthea fixture holds one Condition and one LAB_REPORT
    # DiagnosticReport — and the uploaded PDF bytes are not in it.
    doctor_export = client.get(EXPORT, params={"patientHealthId": HEALTH_ID}, headers=demo.doctor)
    types = _export_resource_types(doctor_export)
    assert types["Patient"] == 1
    assert types["Condition"] == 1
    assert types["DiagnosticReport"] == 1  # LAB_REPORT granted; the CBC report is not
    assert {"Immunization", "AllergyIntolerance", "MedicationRequest", "Procedure"}.isdisjoint(
        types
    )
    _assert_no_uploaded_bytes(doctor_export)

    # The patient's own export covers every imported resource, and still no uploaded bytes.
    own_export = client.get(EXPORT, headers=demo.patient)
    assert sum(_export_resource_types(own_export).values()) == 8  # Patient + 7 resources
    _assert_no_uploaded_bytes(own_export)

    # 4. The patient revokes both grants.
    for grant_id in grant_ids:
        revoked = client.post(f"{GRANTS}/{grant_id}/revoke", headers=demo.patient)
        assert revoked.status_code == 200, revoked.text

    # 5. Every clinician path is now refused.
    assert client.get(f"{RECORDS}/{lab_pdf}", headers=demo.doctor).status_code == 404
    assert client.post(f"{RECORDS}/{lab_pdf}/download-url", headers=demo.doctor).status_code == 404
    after = client.get(
        GRANTED_RECORDS, params={"patientHealthId": HEALTH_ID}, headers=demo.doctor
    ).json()
    assert after["items"] == [] and after["grantedCategories"] == []
    assert (
        client.get(EXPORT, params={"patientHealthId": HEALTH_ID}, headers=demo.doctor).status_code
        == 403
    )

    # 6. The patient's own trail, read through the patient API, records every step.
    trail = Counter(_patient_trail(client, demo))
    assert trail["RECORD_UPLOADED"] == 2
    assert trail["ACCESS_REQUESTED"] == 1
    assert trail["CONSENT_APPROVED"] == 2  # one per approved category
    assert trail["CONSENT_REJECTED"] == 1
    assert trail["RECORDS_LISTED"] == 1  # the granted listing while consent was live
    assert trail["RECORD_VIEWED"] == 1
    assert trail["RECORD_DOWNLOADED"] == 1
    assert trail["RECORD_EXPORTED"] == 2  # the clinician's scoped export and the patient's own
    assert trail["CONSENT_REVOKED"] == 2  # one per category grant
    # Refusals: the pre-consent read and export; the rejected MRI read; after revoking,
    # the read, the download, the listing and the export.
    assert trail["ACCESS_DENIED"] == 7


def test_workflow_c_audit_entries_name_the_clinician_for_the_patient(
    client: TestClient, demo: Demo
) -> None:
    """What the patient's audit page renders: who acted, in what role, from which hospital."""
    lab_pdf = _upload_to_locker(client, demo, "LAB_REPORT", "lab-demo.pdf", LAB_PDF)
    request_id = client.post(
        REQUESTS,
        json={"patientHealthId": HEALTH_ID, "categoryCodes": ["LAB_REPORT"], "purpose": "demo"},
        headers=demo.doctor,
    ).json()["id"]
    client.post(
        f"{REQUESTS}/{request_id}/approve",
        json={"categoryCodes": ["LAB_REPORT"]},
        headers=demo.patient,
    )
    assert client.get(f"{RECORDS}/{lab_pdf}", headers=demo.doctor).status_code == 200

    items = client.get(AUDIT, headers=demo.patient).json()["items"]
    viewed = next(item for item in items if item["action"] == "RECORD_VIEWED")
    assert viewed["actorRole"] == "DOCTOR"
    assert viewed["targetRecordId"] == lab_pdf
    assert "Thomas George" in str(viewed["actor"])
    assert "CMC Vellore" in str(viewed["actor"])
