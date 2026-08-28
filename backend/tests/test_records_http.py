"""HTTP tests for /api/v1/records and /api/v1/record-categories — the M2 gate surface.

Gate criteria under test (ROADMAP M2): a hospital admin can upload a record for a Health
ID; the file lands in (fake) object storage; metadata is queryable; RBAC is enforced —
a patient cannot call hospital surfaces, a doctor/system-admin has no record access at all.
"""

from dataclasses import dataclass
from uuid import UUID, uuid4

import httpx
import pytest
from app.core.config import get_settings
from app.core.queue import InMemoryJobQueue, QueueUnavailableError
from app.modules.auth.domain import Role
from app.modules.auth.fake import FakeAuthProvider
from app.modules.auth.models import User
from app.modules.patients.seed import seed_synthetic_patients
from app.modules.records.errors import StorageUnavailableError
from app.modules.records.fake import FakeObjectStorage
from app.modules.records.models import HospitalAdmin
from app.modules.records.repository import HospitalRepository
from app.modules.records.seed import seed_reference_data
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.support import run_with_session

RECORDS = "/api/v1/records"
CATEGORIES = "/api/v1/record-categories"

#: A pinned, valid synthetic Health ID (app/modules/patients/seed.py).
HEALTH_ID = "PHI-IND-2026-1QE8DVR"

PDF_FILE = ("cbc report.pdf", b"%PDF-1.7 fake-cbc", "application/pdf")
UPLOAD_FORM = {"categoryCode": "CBC", "dateOfService": "2026-03-01", "description": "Routine CBC"}


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@dataclass
class Actors:
    """Bearer headers for one admin of HID-0001, one admin of HID-0002, one seeded
    patient (owner of HEALTH_ID), one doctor, and one system admin."""

    admin_a: dict[str, str]
    admin_b: dict[str, str]
    patient: dict[str, str]
    doctor: dict[str, str]
    system_admin: dict[str, str]


@pytest.fixture
def actors(
    client: TestClient,
    fake_auth: FakeAuthProvider,
    sqlite_db: None,
    db_engine: AsyncEngine,
    fake_storage: FakeObjectStorage,
    fake_queue: InMemoryJobQueue,
) -> Actors:
    async def arrange(session: AsyncSession) -> tuple[UUID, UUID, UUID]:
        await seed_reference_data(session)  # HID-0001..3 VERIFIED + 10 categories
        await seed_synthetic_patients(session)  # includes the owner of HEALTH_ID

        hospitals = HospitalRepository(session)
        admin_ids: list[UUID] = []
        for index, hid in enumerate(["HID-0001", "HID-0002"]):
            hospital = await hospitals.get_by_hid(hid)
            assert hospital is not None
            user = User(firebase_uid=f"fb-admin-{index}", role=Role.HOSPITAL_ADMIN)
            session.add(user)
            await session.flush()
            session.add(
                HospitalAdmin(user_id=user.id, hospital_id=hospital.id, full_name=f"Admin {index}")
            )
            admin_ids.append(user.id)

        patient_query = select(User).where(User.firebase_uid == "synthetic:patient:aarav")
        patient_user = (await session.execute(patient_query)).scalar_one()
        return admin_ids[0], admin_ids[1], patient_user.id

    admin_a_id, admin_b_id, patient_user_id = run_with_session(db_engine, arrange)

    fake_auth.register_user(
        "admin-a", user_id=admin_a_id, firebase_uid="fb-admin-0", role=Role.HOSPITAL_ADMIN
    )
    fake_auth.register_user(
        "admin-b", user_id=admin_b_id, firebase_uid="fb-admin-1", role=Role.HOSPITAL_ADMIN
    )
    fake_auth.register_user(
        "patient",
        user_id=patient_user_id,
        firebase_uid="synthetic:patient:aarav",
        role=Role.PATIENT,
    )
    fake_auth.register_user("doctor", user_id=uuid4(), firebase_uid="fb-doc", role=Role.DOCTOR)
    fake_auth.register_user(
        "sysadmin", user_id=uuid4(), firebase_uid="fb-sys", role=Role.SYSTEM_ADMIN
    )
    return Actors(
        admin_a=_bearer("admin-a"),
        admin_b=_bearer("admin-b"),
        patient=_bearer("patient"),
        doctor=_bearer("doctor"),
        system_admin=_bearer("sysadmin"),
    )


def _upload(
    client: TestClient,
    headers: dict[str, str],
    *,
    health_id: str | None = HEALTH_ID,
    **overrides: str,
) -> httpx.Response:
    form = {**UPLOAD_FORM, **overrides}
    if health_id is not None:
        form["patientHealthId"] = health_id
    response: httpx.Response = client.post(
        RECORDS, data=form, files={"file": PDF_FILE}, headers=headers
    )
    return response


def test_m2_gate_hospital_upload_lands_in_storage_and_is_queryable(
    client: TestClient,
    actors: Actors,
    fake_storage: FakeObjectStorage,
    fake_queue: InMemoryJobQueue,
) -> None:
    response = _upload(client, actors.admin_a)
    assert response.status_code == 201, response.text
    record = response.json()
    assert record["categoryCode"] == "CBC"
    assert record["origin"] == "HOSPITAL_UPLOAD"
    assert record["processingStatus"] == "UPLOADED"
    assert record["uploadedByHospital"] == {"hid": "HID-0001", "name": "TMH Jamshedpur"}
    assert record["originalFilename"] == "cbc report.pdf"
    assert record["sizeBytes"] == len(PDF_FILE[1])

    # The file is in object storage under a UUID-only key.
    (key,) = fake_storage.objects
    prefix, patient_uuid, record_uuid = key.split("/")
    assert prefix == "records"
    UUID(patient_uuid), UUID(record_uuid)  # UUID-only key — no names, no filenames
    assert fake_storage.objects[key].data == PDF_FILE[1]
    assert record["id"] in key
    # The worker job was announced.
    assert fake_queue.jobs == [("record_uploaded", {"record_id": record["id"]})]

    # Metadata is queryable by the uploader...
    listing = client.get(RECORDS, headers=actors.admin_a)
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()["items"]] == [record["id"]]
    single = client.get(f"{RECORDS}/{record['id']}", headers=actors.admin_a)
    assert single.status_code == 200 and single.json() == record

    # ...and by the owning patient.
    patient_view = client.get(RECORDS, headers=actors.patient)
    assert [item["id"] for item in patient_view.json()["items"]] == [record["id"]]


def test_download_url_flow_and_relationship_enforcement(
    client: TestClient, actors: Actors, fake_storage: FakeObjectStorage
) -> None:
    record_id = _upload(client, actors.admin_a).json()["id"]

    for headers in (actors.admin_a, actors.patient):
        link = client.post(f"{RECORDS}/{record_id}/download-url", headers=headers)
        assert link.status_code == 200
        body = link.json()
        assert body["expiresInSeconds"] == get_settings().s3_presign_ttl_seconds
        assert record_id in body["url"]

    # Another hospital's admin: the record is indistinguishable from nonexistent.
    assert client.get(f"{RECORDS}/{record_id}", headers=actors.admin_b).status_code == 404
    assert (
        client.post(f"{RECORDS}/{record_id}/download-url", headers=actors.admin_b).status_code
        == 404
    )
    assert client.get(RECORDS, headers=actors.admin_b).json()["items"] == []


def test_rbac_patient_cannot_use_hospital_surfaces_and_vice_versa(
    client: TestClient, actors: Actors
) -> None:
    # Patient supplying a target Health ID is rejected: locker uploads are self-only.
    own_goal = _upload(client, actors.patient, health_id=HEALTH_ID)
    assert own_goal.status_code == 422
    # Hospital admin must name a patient.
    missing_target = _upload(client, actors.admin_a, health_id=None)
    assert missing_target.status_code == 422
    # M2 gate criterion: the patient cannot call hospital endpoints.
    assert client.get("/api/v1/hospitals/me", headers=actors.patient).status_code == 403
    assert client.get("/api/v1/hospitals/me/doctors", headers=actors.patient).status_code == 403


def test_rbac_doctor_and_system_admin_have_no_record_access_at_m2(
    client: TestClient, actors: Actors
) -> None:
    record_id = _upload(client, actors.admin_a).json()["id"]
    for headers in (actors.doctor, actors.system_admin):
        assert client.get(RECORDS, headers=headers).status_code == 403
        assert client.get(f"{RECORDS}/{record_id}", headers=headers).status_code == 403
        assert (
            client.post(f"{RECORDS}/{record_id}/download-url", headers=headers).status_code == 403
        )
        assert _upload(client, headers).status_code == 403


def test_patient_locker_upload(client: TestClient, actors: Actors) -> None:
    response = _upload(
        client, actors.patient, health_id=None, categoryCode="PRESCRIPTION", description=""
    )
    assert response.status_code == 201
    body = response.json()
    assert body["origin"] == "PATIENT_LOCKER"
    assert body["uploadedByHospital"] is None
    # Locker records are invisible to every hospital.
    assert client.get(RECORDS, headers=actors.admin_a).json()["items"] == []


def test_upload_validation_over_http(client: TestClient, actors: Actors) -> None:
    unknown_category = _upload(client, actors.admin_a, categoryCode="NOT_A_CODE")
    assert unknown_category.status_code == 422

    unknown_patient = _upload(client, actors.admin_a, health_id="PHI-IND-2026-ZZZZZZZ")
    assert unknown_patient.status_code == 422

    future = _upload(client, actors.admin_a, dateOfService="2999-01-01")
    assert future.status_code == 422

    wrong_type = client.post(
        RECORDS,
        data={**UPLOAD_FORM, "patientHealthId": HEALTH_ID},
        files={"file": ("x.zip", b"PK", "application/zip")},
        headers=actors.admin_a,
    )
    assert wrong_type.status_code == 415

    empty = client.post(
        RECORDS,
        data={**UPLOAD_FORM, "patientHealthId": HEALTH_ID},
        files={"file": ("x.pdf", b"", "application/pdf")},
        headers=actors.admin_a,
    )
    assert empty.status_code == 422

    assert client.post(RECORDS).status_code == 401  # unauthenticated


def test_oversize_upload_is_413(
    client: TestClient, actors: Actors, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PULSEOS_RECORDS_MAX_UPLOAD_BYTES", "8")
    get_settings.cache_clear()
    try:
        response = client.post(
            RECORDS,
            data={**UPLOAD_FORM, "patientHealthId": HEALTH_ID},
            files={"file": ("big.pdf", b"123456789", "application/pdf")},
            headers=actors.admin_a,
        )
        assert response.status_code == 413
    finally:
        get_settings.cache_clear()


def test_storage_failure_is_503_and_nothing_persists(
    client: TestClient, actors: Actors, fake_storage: FakeObjectStorage
) -> None:
    fake_storage.storage_error = StorageUnavailableError()
    failed = _upload(client, actors.admin_a)
    assert failed.status_code == 503

    fake_storage.storage_error = None
    retried = _upload(client, actors.admin_a)
    assert retried.status_code == 201
    # Exactly one record exists — the failed attempt rolled back its row.
    assert len(client.get(RECORDS, headers=actors.admin_a).json()["items"]) == 1


def test_queue_outage_never_fails_an_upload(
    client: TestClient, actors: Actors, fake_queue: InMemoryJobQueue
) -> None:
    fake_queue.enqueue_error = QueueUnavailableError()
    response = _upload(client, actors.admin_a)
    assert response.status_code == 201  # queue down, upload still succeeds (ADR-014)


def test_listing_filters_and_paginates_over_http(client: TestClient, actors: Actors) -> None:
    for code in ["CBC", "MRI", "XRAY"]:
        assert _upload(client, actors.admin_a, categoryCode=code).status_code == 201

    only_mri = client.get(RECORDS, params={"category": "MRI"}, headers=actors.admin_a)
    assert [item["categoryCode"] for item in only_mri.json()["items"]] == ["MRI"]

    unknown = client.get(RECORDS, params={"category": "NOPE"}, headers=actors.admin_a)
    assert unknown.status_code == 422

    first = client.get(RECORDS, params={"limit": 2}, headers=actors.admin_a)
    assert len(first.json()["items"]) == 2
    cursor = first.json()["nextCursor"]
    assert cursor is not None
    second = client.get(RECORDS, params={"limit": 2, "cursor": cursor}, headers=actors.admin_a)
    assert len(second.json()["items"]) == 1
    assert second.json()["nextCursor"] is None
    all_ids = {i["id"] for i in first.json()["items"]} | {i["id"] for i in second.json()["items"]}
    assert len(all_ids) == 3

    garbage = client.get(RECORDS, params={"cursor": "garbage"}, headers=actors.admin_a)
    assert garbage.status_code == 422
    too_big = client.get(RECORDS, params={"limit": 101}, headers=actors.admin_a)
    assert too_big.status_code == 422


def test_record_categories_listing(client: TestClient, actors: Actors) -> None:
    assert client.get(CATEGORIES).status_code == 401
    response = client.get(CATEGORIES, headers=actors.patient)
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 10
    assert {"code": "CBC", "displayName": "Complete Blood Count"} in items
    assert [i["code"] for i in items] == sorted(i["code"] for i in items)
