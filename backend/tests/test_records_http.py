"""HTTP tests for /api/v1/records and /api/v1/record-categories — the M2 gate surface.

Gate criteria under test (ROADMAP M2): a hospital admin can upload a record for a Health
ID; the file lands in (fake) object storage; metadata is queryable; RBAC is enforced —
a patient cannot call hospital surfaces, a doctor/system-admin has no record access at all.
"""

from dataclasses import dataclass
from uuid import UUID

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
from app.modules.records.models import Doctor, DoctorStatus, HospitalAdmin
from app.modules.records.repository import HospitalRepository
from app.modules.records.seed import seed_reference_data
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.support import run_with_session

RECORDS = "/api/v1/records"
EXISTENCE = f"{RECORDS}/existence"
GRANTED = "/api/v1/granted-records"
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
    patient (owner of HEALTH_ID), one ACTIVE and one DISABLED doctor of HID-0001, and one
    system admin."""

    admin_a: dict[str, str]
    admin_b: dict[str, str]
    patient: dict[str, str]
    doctor: dict[str, str]
    suspended_doctor: dict[str, str]
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
    async def arrange(session: AsyncSession) -> tuple[UUID, UUID, UUID, UUID, UUID, UUID]:
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

        # Real identity rows: any actor that reaches an audited path is a foreign key on
        # audit_logs.actor_user_id, so a fabricated id would fail the write.
        doctor_user = User(firebase_uid="fb-doc", role=Role.DOCTOR)
        suspended_user = User(firebase_uid="fb-doc-off", role=Role.DOCTOR)
        system_admin_user = User(firebase_uid="fb-sys", role=Role.SYSTEM_ADMIN)
        session.add_all([doctor_user, suspended_user, system_admin_user])
        await session.flush()

        # Clinician profiles: /records/existence needs one, and ADR-015 needs it ACTIVE.
        hospital_a = await hospitals.get_by_hid("HID-0001")
        assert hospital_a is not None
        session.add_all(
            [
                Doctor(
                    user_id=doctor_user.id,
                    hospital_id=hospital_a.id,
                    full_name="Dr Verma",
                    registration_number="REG-A",
                    status=DoctorStatus.ACTIVE,
                ),
                Doctor(
                    user_id=suspended_user.id,
                    hospital_id=hospital_a.id,
                    full_name="Dr Suspended",
                    registration_number="REG-B",
                    status=DoctorStatus.DISABLED,
                ),
            ]
        )
        await session.flush()

        patient_query = select(User).where(User.firebase_uid == "synthetic:patient:aarav")
        patient_user = (await session.execute(patient_query)).scalar_one()
        return (
            admin_ids[0],
            admin_ids[1],
            patient_user.id,
            doctor_user.id,
            suspended_user.id,
            system_admin_user.id,
        )

    (
        admin_a_id,
        admin_b_id,
        patient_user_id,
        doctor_user_id,
        suspended_doctor_id,
        system_admin_user_id,
    ) = run_with_session(db_engine, arrange)

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
    fake_auth.register_user(
        "doctor", user_id=doctor_user_id, firebase_uid="fb-doc", role=Role.DOCTOR
    )
    fake_auth.register_user(
        "doctor-off", user_id=suspended_doctor_id, firebase_uid="fb-doc-off", role=Role.DOCTOR
    )
    fake_auth.register_user(
        "sysadmin", user_id=system_admin_user_id, firebase_uid="fb-sys", role=Role.SYSTEM_ADMIN
    )
    return Actors(
        admin_a=_bearer("admin-a"),
        admin_b=_bearer("admin-b"),
        patient=_bearer("patient"),
        doctor=_bearer("doctor"),
        suspended_doctor=_bearer("doctor-off"),
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


def test_rbac_system_admin_has_no_record_access_and_a_doctor_has_none_without_consent(
    client: TestClient, actors: Actors
) -> None:
    """M3 access model: a clinician may reach the read path but is refused without a grant,
    and the refusal is a 404 so it cannot be distinguished from a missing record. A system
    admin never reaches it at all — no admin break-glass (docs/SECURITY.md)."""
    record_id = _upload(client, actors.admin_a).json()["id"]

    # Neither role may list or upload: both need a relationship records can evaluate.
    for headers in (actors.doctor, actors.system_admin):
        assert client.get(RECORDS, headers=headers).status_code == 403
        assert _upload(client, headers).status_code == 403

    # SYSTEM_ADMIN is stopped at the role gate.
    assert client.get(f"{RECORDS}/{record_id}", headers=actors.system_admin).status_code == 403
    assert (
        client.post(f"{RECORDS}/{record_id}/download-url", headers=actors.system_admin).status_code
        == 403
    )

    # A clinician passes the gate and is refused by consent, as "not found".
    assert client.get(f"{RECORDS}/{record_id}", headers=actors.doctor).status_code == 404
    assert (
        client.post(f"{RECORDS}/{record_id}/download-url", headers=actors.doctor).status_code == 404
    )


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
    assert len(items) == 13
    assert {"code": "CBC", "displayName": "Complete Blood Count"} in items
    # The Synthea import added three clinical codes; the portals read this list rather
    # than hard-coding it, so publishing them needed no frontend change.
    assert {"code": "CONDITION", "displayName": "Diagnosed Condition"} in items
    assert [i["code"] for i in items] == sorted(i["code"] for i in items)


# -- existence projection (M4.1) ---------------------------------------------------------


def test_existence_returns_only_codes_and_display_names(client: TestClient, actors: Actors) -> None:
    _upload(client, actors.admin_a, categoryCode="CBC")
    _upload(client, actors.admin_a, categoryCode="CBC")
    _upload(client, actors.admin_a, categoryCode="XRAY")

    response = client.get(EXISTENCE, params={"patientHealthId": HEALTH_ID}, headers=actors.doctor)

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"items"}
    assert body["items"] == [
        {"code": "CBC", "displayName": "Complete Blood Count"},
        {"code": "XRAY", "displayName": "X-Ray"},
    ]


def test_existence_never_carries_record_metadata(client: TestClient, actors: Actors) -> None:
    """The whole point of the endpoint: presence, and nothing that identifies a document."""
    _upload(client, actors.admin_a, categoryCode="CBC")

    body = client.get(
        EXISTENCE, params={"patientHealthId": HEALTH_ID}, headers=actors.doctor
    ).json()

    leaked = {
        "id",
        "originalFilename",
        "uploadedByHospital",
        "sizeBytes",
        "description",
        "dateOfService",
        "contentType",
        "s3Key",
        "processingStatus",
        "recordCount",
        "count",
    }
    for item in body["items"]:
        assert set(item) == {"code", "displayName"}
        assert not leaked & set(item)


def test_existence_is_empty_for_a_patient_with_no_records(
    client: TestClient, actors: Actors
) -> None:
    response = client.get(EXISTENCE, params={"patientHealthId": HEALTH_ID}, headers=actors.doctor)

    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_existence_is_doctor_only(client: TestClient, actors: Actors) -> None:
    forbidden = [
        client.get(EXISTENCE, params={"patientHealthId": HEALTH_ID}, headers=actors.patient),
        client.get(EXISTENCE, params={"patientHealthId": HEALTH_ID}, headers=actors.admin_a),
        client.get(EXISTENCE, params={"patientHealthId": HEALTH_ID}, headers=actors.system_admin),
    ]

    assert [response.status_code for response in forbidden] == [403] * 3


def test_existence_requires_authentication(client: TestClient) -> None:
    response = client.get(EXISTENCE, params={"patientHealthId": HEALTH_ID})

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_a_suspended_clinician_is_refused(client: TestClient, actors: Actors) -> None:
    _upload(client, actors.admin_a, categoryCode="CBC")

    response = client.get(
        EXISTENCE, params={"patientHealthId": HEALTH_ID}, headers=actors.suspended_doctor
    )

    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")


def test_existence_rejects_an_unknown_or_missing_health_id(
    client: TestClient, actors: Actors
) -> None:
    unknown = client.get(
        EXISTENCE, params={"patientHealthId": "PHI-IND-2026-0000000"}, headers=actors.doctor
    )
    missing = client.get(EXISTENCE, headers=actors.doctor)
    blank = client.get(EXISTENCE, params={"patientHealthId": ""}, headers=actors.doctor)

    assert [unknown.status_code, missing.status_code, blank.status_code] == [422, 422, 422]


def test_existence_does_not_collide_with_the_record_id_route(
    client: TestClient, actors: Actors
) -> None:
    """`/records/existence` is declared before `/records/{record_id}`; without that order
    FastAPI would try to parse "existence" as a UUID and answer 422."""
    response = client.get(EXISTENCE, params={"patientHealthId": HEALTH_ID}, headers=actors.doctor)

    assert response.status_code == 200


# -- granted-record listing (M4.3, ADR-020) ----------------------------------------------


def _granted(client: TestClient, headers: dict[str, str], **params: str) -> httpx.Response:
    query = {"patientHealthId": HEALTH_ID, **params}
    response: httpx.Response = client.get(GRANTED, params=query, headers=headers)
    return response


def test_granted_records_is_doctor_only(client: TestClient, actors: Actors) -> None:
    forbidden = [
        _granted(client, actors.patient),
        _granted(client, actors.admin_a),
        _granted(client, actors.system_admin),
    ]

    assert [response.status_code for response in forbidden] == [403] * 3


def test_granted_records_requires_authentication(client: TestClient) -> None:
    response = client.get(GRANTED, params={"patientHealthId": HEALTH_ID})

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_a_suspended_clinician_cannot_list_granted_records(
    client: TestClient, actors: Actors
) -> None:
    """ADR-015 — refused outright, not handed an empty page: the answer to a suspended
    clinician is about their standing, not about this patient."""
    response = _granted(client, actors.suspended_doctor)

    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")


def test_granted_records_rejects_an_unknown_or_missing_health_id(
    client: TestClient, actors: Actors
) -> None:
    unknown = _granted(client, actors.doctor, patientHealthId="PHI-IND-2026-0000000")
    missing = client.get(GRANTED, headers=actors.doctor)
    blank = _granted(client, actors.doctor, patientHealthId="")

    assert [unknown.status_code, missing.status_code, blank.status_code] == [422, 422, 422]


def test_granted_records_rejects_a_forged_cursor_and_an_oversized_limit(
    client: TestClient, actors: Actors
) -> None:
    forged = _granted(client, actors.doctor, cursor="not-a-cursor")
    too_many = _granted(client, actors.doctor, limit="101")

    assert forged.status_code == 422
    assert forged.json()["detail"] == "Invalid pagination cursor."
    assert too_many.status_code == 422


def test_a_clinician_with_no_grant_gets_an_empty_page_rather_than_a_refusal(
    client: TestClient, actors: Actors
) -> None:
    """They already know this patient exists — they searched the Health ID — so there is no
    existence left to protect, and an empty list is the honest answer to "what may I read"."""
    _upload(client, actors.admin_a, categoryCode="CBC")

    response = _granted(client, actors.doctor)

    assert response.status_code == 200, response.text
    assert response.json() == {"grantedCategories": [], "items": [], "nextCursor": None}


# -- listing controls: sort, search, cursor validity -------------------------------------


def _titles(response: httpx.Response) -> list[str]:
    return [item["originalFilename"] for item in response.json()["items"]]


def _seed_dated_records(client: TestClient, actors: Actors) -> None:
    """Three records on three clinical dates, uploaded in an order that matches none of
    them — so every assertion below fails if the listing reverts to insertion order."""
    for day, name in (("2026-03-02", "middle"), ("2026-03-03", "newest"), ("2026-03-01", "oldest")):
        response = client.post(
            RECORDS,
            data={**UPLOAD_FORM, "dateOfService": day, "description": name},
            files={"file": (f"{name}.pdf", b"%PDF-1.7 x", "application/pdf")},
            headers=actors.patient,
        )
        assert response.status_code == 201, response.text


def test_records_are_listed_newest_clinical_date_first_by_default(
    client: TestClient, actors: Actors
) -> None:
    _seed_dated_records(client, actors)
    response = client.get(RECORDS, headers=actors.patient)
    assert response.status_code == 200
    assert _titles(response) == ["newest.pdf", "middle.pdf", "oldest.pdf"]


def test_the_sort_parameter_reverses_the_listing(client: TestClient, actors: Actors) -> None:
    _seed_dated_records(client, actors)
    newest = client.get(RECORDS, params={"sort": "newest"}, headers=actors.patient)
    oldest = client.get(RECORDS, params={"sort": "oldest"}, headers=actors.patient)
    assert _titles(newest) == ["newest.pdf", "middle.pdf", "oldest.pdf"]
    assert _titles(oldest) == ["oldest.pdf", "middle.pdf", "newest.pdf"]


def test_an_unknown_sort_value_is_refused(client: TestClient, actors: Actors) -> None:
    assert (
        client.get(RECORDS, params={"sort": "sideways"}, headers=actors.patient).status_code == 422
    )


def test_the_search_parameter_filters_server_side(client: TestClient, actors: Actors) -> None:
    _seed_dated_records(client, actors)
    assert _titles(client.get(RECORDS, params={"search": "newest"}, headers=actors.patient)) == [
        "newest.pdf"
    ]
    # The description is searched too, not only the filename.
    assert _titles(client.get(RECORDS, params={"search": "middle"}, headers=actors.patient)) == [
        "middle.pdf"
    ]
    empty = client.get(RECORDS, params={"search": "absent"}, headers=actors.patient)
    assert empty.json()["items"] == []


def test_a_cursor_issued_for_one_sort_is_refused_under_the_other(
    client: TestClient, actors: Actors
) -> None:
    """Honouring it would serve a page from the wrong end of the sequence with no error —
    the silent failure this validation exists to make loud."""
    _seed_dated_records(client, actors)
    first = client.get(RECORDS, params={"sort": "newest", "limit": 1}, headers=actors.patient)
    cursor = first.json()["nextCursor"]
    assert cursor is not None

    same = client.get(
        RECORDS, params={"sort": "newest", "cursor": cursor, "limit": 1}, headers=actors.patient
    )
    assert same.status_code == 200
    assert _titles(same) == ["middle.pdf"]

    crossed = client.get(
        RECORDS, params={"sort": "oldest", "cursor": cursor, "limit": 1}, headers=actors.patient
    )
    assert crossed.status_code == 422
    assert "sort order" in crossed.json()["detail"]


def test_a_corrupt_cursor_is_still_a_validation_error(client: TestClient, actors: Actors) -> None:
    response = client.get(RECORDS, params={"cursor": "not-a-cursor"}, headers=actors.patient)
    assert response.status_code == 422


def test_paging_with_a_cursor_covers_the_listing_exactly_once(
    client: TestClient, actors: Actors
) -> None:
    _seed_dated_records(client, actors)
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(5):  # bounded, so a broken cursor cannot loop forever
        params: dict[str, object] = {"sort": "oldest", "limit": 1}
        if cursor is not None:
            params["cursor"] = cursor
        page = client.get(RECORDS, params=params, headers=actors.patient)
        assert page.status_code == 200
        seen.extend(_titles(page))
        cursor = page.json()["nextCursor"]
        if cursor is None:
            break
    assert seen == ["oldest.pdf", "middle.pdf", "newest.pdf"]


# -- granted-records privacy regression --------------------------------------------------


def test_the_granted_listing_offers_no_search_parameter() -> None:
    """``GrantedRecordResponse`` withholds ``originalFilename`` and ``description`` on
    purpose. A search over exactly those two withheld columns would let a clinician recover
    a diagnosis-bearing description from result counts, so the parameter must not exist."""
    from app.main import create_app

    spec = create_app().openapi()
    operation = spec["paths"]["/api/v1/granted-records"]["get"]
    names = {parameter["name"] for parameter in operation["parameters"]}
    assert "search" not in names
    assert "sort" not in names
    assert names == {"patientHealthId", "cursor", "limit"}


def test_the_granted_listing_still_withholds_filename_and_description() -> None:
    """A field-level pin: widening this model is what the search oracle would need."""
    from app.modules.records.schemas import GrantedRecordResponse

    fields = set(GrantedRecordResponse.model_fields)
    assert {"original_filename", "description", "size_bytes", "content_type"}.isdisjoint(fields)
