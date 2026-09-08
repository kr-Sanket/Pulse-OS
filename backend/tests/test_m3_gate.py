"""The M3 gate flow, end to end through the mounted application (.claude/ROADMAP.md).

    doctor requests → patient approves per category → doctor reads only approved
    categories → patient sees the audit entry. Revocation cuts access immediately.
    Attempted unauthorized reads are denied AND logged.

Everything here goes over HTTP against the real ``create_app()`` router set, with only the
external providers faked (auth, object storage, queue) — so it exercises the records ↔
consent wiring, not a hand-assembled service graph.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
import pytest
from app.core.queue import InMemoryJobQueue
from app.core.ratelimit import InMemoryRateLimiter
from app.modules.auth.domain import Role
from app.modules.auth.fake import FakeAuthProvider
from app.modules.auth.models import User
from app.modules.consent.repository import AuditLogRepository
from app.modules.patients.health_id import generate_health_id
from app.modules.patients.seed import seed_synthetic_patients
from app.modules.records.fake import FakeObjectStorage
from app.modules.records.models import Doctor, DoctorStatus, HospitalAdmin
from app.modules.records.repository import HospitalRepository
from app.modules.records.seed import seed_reference_data
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.support import run_with_session

API = "/api/v1"
RECORDS = "/api/v1/records"
REQUESTS = "/api/v1/access-requests"
GRANTS = "/api/v1/consent-grants"
GRANTED_RECORDS = "/api/v1/granted-records"
HEALTH_ID = "PHI-IND-2026-1QE8DVR"
PDF = ("cbc.pdf", b"%PDF-1.7 fake", "application/pdf")


@dataclass
class Cast:
    """One admin at TMH (HID-0001) who uploads, and one clinician at CMC (HID-0002) who
    asks for access — the cross-hospital flow the gate describes."""

    admin_tmh: dict[str, str]
    doctor_cmc: dict[str, str]
    patient: dict[str, str]
    patient_id: UUID
    doctor_user_id: UUID


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def cast(
    client: TestClient,
    fake_auth: FakeAuthProvider,
    sqlite_db: None,
    db_engine: AsyncEngine,
    fake_storage: FakeObjectStorage,
    fake_queue: InMemoryJobQueue,
) -> Cast:
    async def arrange(session: AsyncSession) -> dict[str, Any]:
        await seed_reference_data(session)
        await seed_synthetic_patients(session)
        hospitals = HospitalRepository(session)
        tmh = await hospitals.get_by_hid("HID-0001")
        cmc = await hospitals.get_by_hid("HID-0002")
        assert tmh is not None and cmc is not None

        admin_user = User(firebase_uid="fb-admin-tmh", role=Role.HOSPITAL_ADMIN)
        doctor_user = User(firebase_uid="fb-doctor-cmc", role=Role.DOCTOR)
        session.add_all([admin_user, doctor_user])
        await session.flush()
        session.add_all(
            [
                HospitalAdmin(user_id=admin_user.id, hospital_id=tmh.id, full_name="Admin"),
                Doctor(
                    user_id=doctor_user.id,
                    hospital_id=cmc.id,
                    full_name="Dr Thomas",
                    registration_number="R-CMC",
                    status=DoctorStatus.ACTIVE,
                ),
            ]
        )
        patient_user = (
            await session.execute(
                select(User).where(User.firebase_uid == "synthetic:patient:aarav")
            )
        ).scalar_one()
        from app.modules.patients.repository import PatientRepository

        patient = await PatientRepository(session).get_by_health_id(HEALTH_ID)
        assert patient is not None
        return {
            "admin_user_id": admin_user.id,
            "doctor_user_id": doctor_user.id,
            "patient_user_id": patient_user.id,
            "patient_id": patient.id,
        }

    ids = run_with_session(db_engine, arrange)
    fake_auth.register_user(
        "admin",
        user_id=ids["admin_user_id"],
        firebase_uid="fb-admin-tmh",
        role=Role.HOSPITAL_ADMIN,
    )
    fake_auth.register_user(
        "doctor", user_id=ids["doctor_user_id"], firebase_uid="fb-doctor-cmc", role=Role.DOCTOR
    )
    fake_auth.register_user(
        "patient",
        user_id=ids["patient_user_id"],
        firebase_uid="synthetic:patient:aarav",
        role=Role.PATIENT,
    )
    return Cast(
        admin_tmh=_bearer("admin"),
        doctor_cmc=_bearer("doctor"),
        patient=_bearer("patient"),
        patient_id=ids["patient_id"],
        doctor_user_id=ids["doctor_user_id"],
    )


def _upload(client: TestClient, cast: Cast, code: str) -> str:
    response: httpx.Response = client.post(
        RECORDS,
        data={
            "categoryCode": code,
            "dateOfService": "2026-03-01",
            "patientHealthId": HEALTH_ID,
        },
        files={"file": PDF},
        headers=cast.admin_tmh,
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _audit(db_engine: AsyncEngine, patient_id: UUID) -> list[str]:
    async def read(session: AsyncSession) -> list[str]:
        rows = await AuditLogRepository(session).list_page_by_patient(
            patient_id, after=None, limit=99
        )
        return [row.action.value for row in rows]

    return run_with_session(db_engine, read)


def test_m3_gate_request_approve_read_revoke_across_two_hospitals(
    client: TestClient, cast: Cast, db_engine: AsyncEngine
) -> None:
    cbc_record = _upload(client, cast, "CBC")
    mri_record = _upload(client, cast, "MRI")

    # 1. A clinician at another hospital cannot read either record, and is told nothing.
    assert client.get(f"{RECORDS}/{cbc_record}", headers=cast.doctor_cmc).status_code == 404
    assert "ACCESS_DENIED" in _audit(db_engine, cast.patient_id)

    # 2. The clinician asks for both categories.
    asked = client.post(
        REQUESTS,
        json={"patientHealthId": HEALTH_ID, "categoryCodes": ["CBC", "MRI"], "purpose": "referral"},
        headers=cast.doctor_cmc,
    )
    assert asked.status_code == 201, asked.text
    request_id = asked.json()["id"]

    # 3. It lands in the patient's inbox with both categories.
    inbox = client.get(f"{REQUESTS}/inbox", headers=cast.patient)
    assert [item["id"] for item in inbox.json()["items"]] == [request_id]
    assert sorted(inbox.json()["items"][0]["categoryCodes"]) == ["CBC", "MRI"]

    # 4. The patient approves CBC and rejects MRI.
    approved = client.post(
        f"{REQUESTS}/{request_id}/approve", json={"categoryCodes": ["CBC"]}, headers=cast.patient
    )
    assert approved.status_code == 200
    grant_id = approved.json()["grants"][0]["id"]
    assert (
        client.post(
            f"{REQUESTS}/{request_id}/reject",
            json={"categoryCodes": ["MRI"]},
            headers=cast.patient,
        ).json()["requestStatus"]
        == "DECIDED"
    )

    # 5. The clinician now reads the approved category — and only that one.
    assert client.get(f"{RECORDS}/{cbc_record}", headers=cast.doctor_cmc).status_code == 200
    assert client.get(f"{RECORDS}/{mri_record}", headers=cast.doctor_cmc).status_code == 404

    # 6. Downloading the granted record works and is recorded as a download, not a view.
    download = client.post(f"{RECORDS}/{cbc_record}/download-url", headers=cast.doctor_cmc)
    assert download.status_code == 200
    assert cbc_record in download.json()["url"]

    # 7. Revocation cuts access for the very next read.
    assert client.post(f"{GRANTS}/{grant_id}/revoke", headers=cast.patient).status_code == 200
    assert client.get(f"{RECORDS}/{cbc_record}", headers=cast.doctor_cmc).status_code == 404

    # 8. The patient's trail records every step, allowed and refused alike.
    from collections import Counter

    trail = Counter(_audit(db_engine, cast.patient_id))
    assert trail["RECORD_UPLOADED"] == 2  # the two hospital uploads that set the journey up
    assert trail["ACCESS_REQUESTED"] == 1
    assert trail["CONSENT_APPROVED"] == 1
    assert trail["CONSENT_REJECTED"] == 1
    assert trail["CONSENT_REVOKED"] == 1
    assert trail["RECORD_VIEWED"] == 1  # the one allowed metadata read
    assert trail["RECORD_DOWNLOADED"] == 1  # the file access, distinguished from the view
    assert trail["ACCESS_DENIED"] == 3  # before the grant, the rejected MRI, after revoking


def test_m2_relationships_survive_the_consent_integration(
    client: TestClient, cast: Cast, db_engine: AsyncEngine
) -> None:
    """ADR-013 layer 2 is untouched: a hospital still reads its own upload with no grant,
    and a patient still reads their own records."""
    record_id = _upload(client, cast, "CBC")

    assert client.get(f"{RECORDS}/{record_id}", headers=cast.admin_tmh).status_code == 200
    assert client.get(f"{RECORDS}/{record_id}", headers=cast.patient).status_code == 200
    assert client.get(RECORDS, headers=cast.admin_tmh).json()["items"][0]["id"] == record_id
    assert client.get(RECORDS, headers=cast.patient).json()["items"][0]["id"] == record_id

    # Both reads are audited. The hospital's own-upload read is decided by layer 2 and
    # never reaches the consent choke point, but it still reaches the trail (ADR-022,
    # closing finding M3-E) — so the patient sees every read of their record, whoever made
    # it and whatever authorised it. The upload that created the record is on there too.
    trail = _audit(db_engine, cast.patient_id)
    assert trail.count("RECORD_VIEWED") == 2
    assert trail.count("RECORD_UPLOADED") == 1
    # Listing is still not audited for either caller: the owner/hospital listing ruling
    # (M3-B) is that rule 3 covers non-owner reads, and a hospital-scoped listing event
    # cannot be attributed without ADR-022's deferred hospital column.
    assert trail.count("RECORDS_LISTED") == 0


def test_a_suspended_clinician_loses_a_grant_it_already_holds(
    client: TestClient, cast: Cast, db_engine: AsyncEngine
) -> None:
    record_id = _upload(client, cast, "CBC")
    request_id = client.post(
        REQUESTS,
        json={"patientHealthId": HEALTH_ID, "categoryCodes": ["CBC"], "purpose": "p"},
        headers=cast.doctor_cmc,
    ).json()["id"]
    client.post(
        f"{REQUESTS}/{request_id}/approve", json={"categoryCodes": ["CBC"]}, headers=cast.patient
    )
    assert client.get(f"{RECORDS}/{record_id}", headers=cast.doctor_cmc).status_code == 200

    async def suspend(session: AsyncSession) -> None:
        doctor = (
            await session.execute(select(Doctor).where(Doctor.user_id == cast.doctor_user_id))
        ).scalar_one()
        doctor.status = DoctorStatus.DISABLED

    run_with_session(db_engine, suspend)
    assert client.get(f"{RECORDS}/{record_id}", headers=cast.doctor_cmc).status_code == 404


def _grant_cbc(client: TestClient, cast: Cast) -> str:
    """Give the CMC clinician an active grant for CBC and return the grant id."""
    request_id = client.post(
        REQUESTS,
        json={"patientHealthId": HEALTH_ID, "categoryCodes": ["CBC"], "purpose": "p"},
        headers=cast.doctor_cmc,
    ).json()["id"]
    approved = client.post(
        f"{REQUESTS}/{request_id}/approve",
        json={"categoryCodes": ["CBC"]},
        headers=cast.patient,
    )
    assert approved.status_code == 200, approved.text
    return str(approved.json()["grants"][0]["id"])


def _hide(client: TestClient, cast: Cast, record_id: str, *, hidden: bool = True) -> None:
    """Hide (or unhide) a record the way a patient actually does it.

    This used to write ``is_hidden`` straight to the row, because no endpoint existed. Now
    that one does, the enforcement tests below exercise the whole path — the patient's own
    request included — rather than a state only a test could produce.
    """
    response: httpx.Response = client.patch(
        f"{RECORDS}/{record_id}/visibility", json={"isHidden": hidden}, headers=cast.patient
    )
    assert response.status_code == 200, response.text
    assert response.json()["isHidden"] is hidden


def test_a_denied_download_is_refused_and_durably_audited(
    client: TestClient, cast: Cast, db_engine: AsyncEngine
) -> None:
    """.claude/ROADMAP.md M3 gate: attempted unauthorized reads are denied AND logged.

    File access is the read that matters most. The refusal is signalled to the client as a
    404, and the ACCESS_DENIED row must survive the request that produced it.
    """
    record_id = _upload(client, cast, "CBC")
    before = _audit(db_engine, cast.patient_id).count("ACCESS_DENIED")

    refused = client.post(f"{RECORDS}/{record_id}/download-url", headers=cast.doctor_cmc)
    assert refused.status_code == 404
    assert refused.headers["content-type"].startswith("application/problem+json")
    assert refused.json()["detail"] == "Record not found."

    after = _audit(db_engine, cast.patient_id)
    assert after.count("ACCESS_DENIED") == before + 1


def test_a_hidden_record_is_unreadable_by_a_clinician_holding_a_valid_grant(
    client: TestClient, cast: Cast, db_engine: AsyncEngine
) -> None:
    """docs/DOMAIN_MODEL.md §1: ``is_hidden`` is patient-controlled visibility. Hiding
    removes a record from what consent can share, so an active grant is not enough."""
    record_id = _upload(client, cast, "CBC")
    _grant_cbc(client, cast)
    assert client.get(f"{RECORDS}/{record_id}", headers=cast.doctor_cmc).status_code == 200

    _hide(client, cast, record_id)
    assert client.get(f"{RECORDS}/{record_id}", headers=cast.doctor_cmc).status_code == 404
    assert (
        client.post(f"{RECORDS}/{record_id}/download-url", headers=cast.doctor_cmc).status_code
        == 404
    )


def test_a_hidden_record_stays_visible_to_the_patient_who_hid_it(
    client: TestClient, cast: Cast, db_engine: AsyncEngine
) -> None:
    """The owner must keep seeing a hidden record — otherwise hiding would be a one-way
    door and the patient could never unhide it."""
    record_id = _upload(client, cast, "CBC")
    _hide(client, cast, record_id)

    assert client.get(f"{RECORDS}/{record_id}", headers=cast.patient).status_code == 200
    assert (
        client.post(f"{RECORDS}/{record_id}/download-url", headers=cast.patient).status_code == 200
    )
    assert [item["id"] for item in client.get(RECORDS, headers=cast.patient).json()["items"]] == [
        record_id
    ]


def test_a_hidden_record_stays_visible_to_the_hospital_that_uploaded_it(
    client: TestClient, cast: Cast, db_engine: AsyncEngine
) -> None:
    """The implemented rule, stated as a test: hiding changes what *consent* can share and
    nothing else. ADR-013 layer 2 is untouched, so the uploading hospital still reads its
    own record — and per docs/DOMAIN_MODEL.md §1 hiding applies to locker records, which
    have no uploading hospital, so this combination should not arise in practice."""
    record_id = _upload(client, cast, "CBC")
    _hide(client, cast, record_id)

    assert client.get(f"{RECORDS}/{record_id}", headers=cast.admin_tmh).status_code == 200
    assert [item["id"] for item in client.get(RECORDS, headers=cast.admin_tmh).json()["items"]] == [
        record_id
    ]


# -- the discovery step the flow was missing (M4.3, ADR-020) -----------------------------


def _granted_records(client: TestClient, cast: Cast, **params: str) -> dict[str, Any]:
    response: httpx.Response = client.get(
        GRANTED_RECORDS,
        params={"patientHealthId": HEALTH_ID, **params},
        headers=cast.doctor_cmc,
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_a_clinician_can_reach_a_record_id_only_through_consent(
    client: TestClient, cast: Cast, db_engine: AsyncEngine
) -> None:
    """The end-to-end capability ADR-020 adds, and the whole point of it: before the
    approval the clinician cannot name a single record; after it they can name exactly the
    ones the patient approved, and nothing else."""
    cbc_record = _upload(client, cast, "CBC")
    mri_record = _upload(client, cast, "MRI")

    before = _granted_records(client, cast)
    assert before == {"grantedCategories": [], "items": [], "nextCursor": None}

    _grant_cbc(client, cast)

    after = _granted_records(client, cast)
    assert [item["id"] for item in after["items"]] == [cbc_record]
    assert [category["code"] for category in after["grantedCategories"]] == ["CBC"]
    assert mri_record not in {item["id"] for item in after["items"]}

    # The id is not merely displayed — it opens the record, and its file.
    assert client.get(f"{RECORDS}/{cbc_record}", headers=cast.doctor_cmc).status_code == 200
    assert (
        client.post(f"{RECORDS}/{cbc_record}/download-url", headers=cast.doctor_cmc).status_code
        == 200
    )


def test_a_listed_record_id_is_worthless_once_the_grant_is_revoked(
    client: TestClient, cast: Cast, db_engine: AsyncEngine
) -> None:
    """The property that makes it safe to hand out ids at all: the listing is a filter, not
    a permission. Every read still crosses ``enforce``, so a saved id dies with its grant."""
    record_id = _upload(client, cast, "CBC")
    grant_id = _grant_cbc(client, cast)
    assert [item["id"] for item in _granted_records(client, cast)["items"]] == [record_id]

    assert client.post(f"{GRANTS}/{grant_id}/revoke", headers=cast.patient).status_code == 200

    assert client.get(f"{RECORDS}/{record_id}", headers=cast.doctor_cmc).status_code == 404
    assert (
        client.post(f"{RECORDS}/{record_id}/download-url", headers=cast.doctor_cmc).status_code
        == 404
    )
    assert _granted_records(client, cast) == {
        "grantedCategories": [],
        "items": [],
        "nextCursor": None,
    }


def test_the_listing_discloses_a_chooser_not_a_document(
    client: TestClient, cast: Cast, db_engine: AsyncEngine
) -> None:
    """docs/SECURITY.md: a filename is unsafe to put in a storage key, so it is unsafe to
    broadcast across a page. The listing says enough to pick a record; ``GET /records/{id}``
    discloses the document, one audited read at a time."""
    record_id = _upload(client, cast, "CBC")
    _grant_cbc(client, cast)

    (item,) = _granted_records(client, cast)["items"]

    assert set(item) == {
        "id",
        "categoryCode",
        "categoryDisplayName",
        "origin",
        "dateOfService",
        "uploadedByHospital",
        "createdAt",
    }
    assert item["uploadedByHospital"] == {"hid": "HID-0001", "name": "TMH Jamshedpur"}
    assert item["origin"] == "HOSPITAL_UPLOAD"

    # Every withheld field is still reachable on the single authorized read.
    detail = client.get(f"{RECORDS}/{record_id}", headers=cast.doctor_cmc).json()
    assert detail["originalFilename"] == "cbc.pdf"
    assert detail["sizeBytes"] == len(PDF[1])


def test_a_hidden_record_never_appears_in_a_granted_listing(
    client: TestClient, cast: Cast, db_engine: AsyncEngine
) -> None:
    record_id = _upload(client, cast, "CBC")
    _grant_cbc(client, cast)
    _hide(client, cast, record_id)

    listed = _granted_records(client, cast)

    assert listed["items"] == []
    # The approval stands; one withdrawn document does not undo it.
    assert [category["code"] for category in listed["grantedCategories"]] == ["CBC"]


def test_the_patient_sees_that_a_clinician_asked_what_they_could_read(
    client: TestClient, cast: Cast, db_engine: AsyncEngine
) -> None:
    """SYSTEM_ARCHITECTURE rule 3 covers metadata-beyond-existence, so a listing is an
    access event. One row per request — never one per record, whatever the page holds."""
    for _ in range(3):
        _upload(client, cast, "CBC")

    _granted_records(client, cast)  # refused: no grant yet
    assert _audit(db_engine, cast.patient_id).count("ACCESS_DENIED") == 1

    _grant_cbc(client, cast)
    assert len(_granted_records(client, cast)["items"]) == 3

    trail = _audit(db_engine, cast.patient_id)
    assert trail.count("RECORDS_LISTED") == 1
    assert trail.count("RECORD_VIEWED") == 0  # listing three records is not reading them


def test_the_listing_pages_without_multiplying_audit_rows(
    client: TestClient, cast: Cast, db_engine: AsyncEngine
) -> None:
    for _ in range(3):
        _upload(client, cast, "CBC")
    _grant_cbc(client, cast)

    first = _granted_records(client, cast, limit="2")
    assert len(first["items"]) == 2 and first["nextCursor"] is not None
    second = _granted_records(client, cast, limit="2", cursor=first["nextCursor"])
    assert len(second["items"]) == 1 and second["nextCursor"] is None

    seen = {item["id"] for item in [*first["items"], *second["items"]]}
    assert len(seen) == 3  # no overlap, no loss
    # Two requests, two rows — the count tracks requests, never rows returned.
    assert _audit(db_engine, cast.patient_id).count("RECORDS_LISTED") == 2


# -- ADR-023: the hospital's view of its own activity ----------------------------------------

HOSPITAL_AUDIT = "/api/v1/hospitals/me/audit-logs"


def test_a_hospital_sees_its_own_activity_and_only_that(
    client: TestClient, cast: Cast, db_engine: AsyncEngine
) -> None:
    """Scope comes from the caller's admin profile, never from a parameter."""
    record_id = _upload(client, cast, "CBC")
    assert client.get(f"{RECORDS}/{record_id}", headers=cast.admin_tmh).status_code == 200

    response = client.get(HOSPITAL_AUDIT, headers=cast.admin_tmh)

    assert response.status_code == 200, response.text
    actions = [item["action"] for item in response.json()["items"]]
    # The upload and the read it just made, newest first. The patient's own events are
    # absent: they carry no hospital.
    assert actions == ["RECORD_VIEWED", "RECORD_UPLOADED"]


def test_the_hospital_audit_response_carries_no_patient_and_no_digest(
    client: TestClient, cast: Cast
) -> None:
    """The allow-list, pinned. A hospital reading its own activity is not handed a patient
    index, and tamper evidence is published to the subject of the trail, not to a hospital."""
    _upload(client, cast, "CBC")

    item = client.get(HOSPITAL_AUDIT, headers=cast.admin_tmh).json()["items"][0]

    assert set(item) == {
        "id",
        "action",
        "actorUserId",
        "actorRole",
        "actor",
        "targetRecordId",
        "occurredAt",
    }
    leaked = {
        "patientId",
        "eventHash",
        "hashVersion",
        "requestContext",
        "createdAt",
        "actorHospitalId",
        "targetCategoryCode",
    }
    assert leaked.isdisjoint(item)


def test_another_hospitals_activity_is_invisible(client: TestClient, cast: Cast) -> None:
    """No cross-hospital leakage: CMC's clinician generates events, TMH's admin sees none
    of them, and there is no parameter that could ask for them."""
    record_id = _upload(client, cast, "CBC")
    # A CMC doctor is refused the record — an ACCESS_DENIED attributed to CMC.
    assert client.get(f"{RECORDS}/{record_id}", headers=cast.doctor_cmc).status_code == 404

    items = client.get(HOSPITAL_AUDIT, headers=cast.admin_tmh).json()["items"]

    assert [item["action"] for item in items] == ["RECORD_UPLOADED"]


def test_the_hospital_audit_endpoint_is_hospital_admin_only(client: TestClient, cast: Cast) -> None:
    _upload(client, cast, "CBC")

    assert client.get(HOSPITAL_AUDIT).status_code == 401
    assert client.get(HOSPITAL_AUDIT, headers=cast.patient).status_code == 403
    assert client.get(HOSPITAL_AUDIT, headers=cast.doctor_cmc).status_code == 403


def test_the_hospital_audit_page_is_cursor_paginated(client: TestClient, cast: Cast) -> None:
    for code in ("CBC", "MRI", "XRAY"):
        _upload(client, cast, code)

    first = client.get(HOSPITAL_AUDIT, params={"limit": 2}, headers=cast.admin_tmh).json()
    assert first["nextCursor"] is not None
    second = client.get(
        HOSPITAL_AUDIT,
        params={"limit": 2, "cursor": first["nextCursor"]},
        headers=cast.admin_tmh,
    ).json()

    assert len(first["items"]) == 2
    assert len(second["items"]) == 1
    first_ids = {item["id"] for item in first["items"]}
    assert first_ids.isdisjoint({item["id"] for item in second["items"]})


def test_the_patient_trail_is_unaffected_by_the_hospital_view(
    client: TestClient, cast: Cast, db_engine: AsyncEngine
) -> None:
    """The patient's listing still shows everything about them, hospital-attributed or not."""
    record_id = _upload(client, cast, "CBC")
    assert client.get(f"{RECORDS}/{record_id}", headers=cast.patient).status_code == 200

    patient_actions = [
        item["action"]
        for item in client.get("/api/v1/audit-logs", headers=cast.patient).json()["items"]
    ]

    # The patient sees their own read *and* the hospital's upload; the hospital sees only
    # the upload. Same rows, two truthful scopes.
    assert patient_actions == ["RECORD_VIEWED", "RECORD_UPLOADED"]


# -- rate limiting on the remaining protected surfaces (ADR-024, M3-D) -----------------------

EXISTENCE = f"{RECORDS}/existence"


def test_records_existence_is_rate_limited_at_thirty_per_minute(
    client: TestClient, cast: Cast, rate_limiter: InMemoryRateLimiter
) -> None:
    assert rate_limiter.limit_for("record_existence").limit == 30
    params = {"patientHealthId": HEALTH_ID}
    for _ in range(30):
        assert client.get(EXISTENCE, params=params, headers=cast.doctor_cmc).status_code == 200

    refused = client.get(EXISTENCE, params=params, headers=cast.doctor_cmc)

    assert refused.status_code == 429
    assert int(refused.headers["Retry-After"]) >= 1


def test_granted_records_is_rate_limited_at_thirty_per_minute(
    client: TestClient, cast: Cast, rate_limiter: InMemoryRateLimiter
) -> None:
    assert rate_limiter.limit_for("granted_records").limit == 30
    params = {"patientHealthId": HEALTH_ID}
    for _ in range(30):
        assert (
            client.get(GRANTED_RECORDS, params=params, headers=cast.doctor_cmc).status_code == 200
        )

    refused = client.get(GRANTED_RECORDS, params=params, headers=cast.doctor_cmc)

    assert refused.status_code == 429


def test_access_request_creation_is_rate_limited_at_ten_per_minute(
    client: TestClient, cast: Cast, rate_limiter: InMemoryRateLimiter
) -> None:
    assert rate_limiter.limit_for("access_request_create").limit == 10
    body = {"patientHealthId": HEALTH_ID, "categoryCodes": ["CBC"], "purpose": "care"}
    for _ in range(10):
        assert client.post(REQUESTS, json=body, headers=cast.doctor_cmc).status_code == 201

    refused = client.post(REQUESTS, json=body, headers=cast.doctor_cmc)

    assert refused.status_code == 429


def test_the_four_buckets_are_independent_of_one_another(
    client: TestClient, cast: Cast, rate_limiter: InMemoryRateLimiter
) -> None:
    """Spending one endpoint's quota must not close another's."""
    params = {"patientHealthId": HEALTH_ID}
    for _ in range(31):
        client.get(EXISTENCE, params=params, headers=cast.doctor_cmc)
    assert client.get(EXISTENCE, params=params, headers=cast.doctor_cmc).status_code == 429

    assert client.get(GRANTED_RECORDS, params=params, headers=cast.doctor_cmc).status_code == 200


def test_unprotected_routes_are_untouched_by_the_limiter(
    client: TestClient, cast: Cast, rate_limiter: InMemoryRateLimiter
) -> None:
    """Only the four declared surfaces are limited; nothing else acquired a quota."""
    for _ in range(40):
        assert client.get(f"{API}/record-categories", headers=cast.doctor_cmc).status_code == 200
    for _ in range(40):
        assert client.get(RECORDS, headers=cast.admin_tmh).status_code == 200


def test_a_throttled_discovery_reveals_nothing_about_the_health_id(
    client: TestClient, cast: Cast, rate_limiter: InMemoryRateLimiter
) -> None:
    """Once throttled, a Health ID that resolves and one that does not answer identically."""
    unissued = generate_health_id()
    for _ in range(30):
        client.get(EXISTENCE, params={"patientHealthId": HEALTH_ID}, headers=cast.doctor_cmc)

    real = client.get(EXISTENCE, params={"patientHealthId": HEALTH_ID}, headers=cast.doctor_cmc)
    fake = client.get(EXISTENCE, params={"patientHealthId": unissued}, headers=cast.doctor_cmc)

    assert real.status_code == fake.status_code == 429
    assert real.json()["title"] == fake.json()["title"]
    assert real.json()["detail"] == fake.json()["detail"]
    assert HEALTH_ID not in real.text and unissued not in fake.text
    assert "record_existence" not in real.text


# -- patient-controlled visibility, end to end (D1: any record the patient owns) ---------
#
# The records these exercise are HOSPITAL_UPLOAD, uploaded by TMH — the case the approved
# scope turns on. Hiding is the patient withdrawing a document from what consent can share;
# it is not a revocation, and these tests are how the two stay distinguishable.


def test_hiding_and_unhiding_a_record_closes_and_reopens_every_grantee_path(
    client: TestClient, cast: Cast
) -> None:
    """The whole round trip on one record: readable under a grant, gone while hidden, back
    when unhidden — metadata and file alike, with the grant never touched."""
    record_id = _upload(client, cast, "CBC")
    _grant_cbc(client, cast)

    assert client.get(f"{RECORDS}/{record_id}", headers=cast.doctor_cmc).status_code == 200
    assert (
        client.post(f"{RECORDS}/{record_id}/download-url", headers=cast.doctor_cmc).status_code
        == 200
    )

    _hide(client, cast, record_id)

    assert client.get(f"{RECORDS}/{record_id}", headers=cast.doctor_cmc).status_code == 404
    assert (
        client.post(f"{RECORDS}/{record_id}/download-url", headers=cast.doctor_cmc).status_code
        == 404
    )

    _hide(client, cast, record_id, hidden=False)

    assert client.get(f"{RECORDS}/{record_id}", headers=cast.doctor_cmc).status_code == 200
    assert (
        client.post(f"{RECORDS}/{record_id}/download-url", headers=cast.doctor_cmc).status_code
        == 200
    )


def test_hiding_a_record_leaves_the_grant_exactly_as_it_was(client: TestClient, cast: Cast) -> None:
    """Hiding is not revoking. The distinction is the whole reason both exist: a revoked
    grant is a decision about a clinician, a hidden record is a decision about a document.
    """
    record_id = _upload(client, cast, "CBC")
    grant_id = _grant_cbc(client, cast)
    before = client.get(GRANTS, headers=cast.patient).json()

    _hide(client, cast, record_id)

    after = client.get(GRANTS, headers=cast.patient).json()
    assert after == before
    (grant,) = [item for item in after["items"] if item["id"] == grant_id]
    assert grant["status"] == "ACTIVE"
    assert grant["revokedAt"] is None


def test_hiding_the_last_record_in_a_category_withdraws_it_from_discovery(
    client: TestClient, cast: Cast
) -> None:
    """``/records/existence`` answers presence, and a hidden record is not present to a
    clinician. The MRI is the control: the category the patient did not touch is unmoved."""
    cbc = _upload(client, cast, "CBC")
    _upload(client, cast, "MRI")

    def discovered() -> list[str]:
        response = client.get(
            EXISTENCE, params={"patientHealthId": HEALTH_ID}, headers=cast.doctor_cmc
        )
        assert response.status_code == 200, response.text
        return sorted(item["code"] for item in response.json()["items"])

    assert discovered() == ["CBC", "MRI"]

    _hide(client, cast, cbc)
    assert discovered() == ["MRI"]

    _hide(client, cast, cbc, hidden=False)
    assert discovered() == ["CBC", "MRI"]


def test_hiding_one_record_leaves_the_rest_of_its_category_discoverable(
    client: TestClient, cast: Cast
) -> None:
    """Existence is per category, not per document: one hidden CBC among two says nothing."""
    first = _upload(client, cast, "CBC")
    _upload(client, cast, "CBC")

    _hide(client, cast, first)

    response = client.get(EXISTENCE, params={"patientHealthId": HEALTH_ID}, headers=cast.doctor_cmc)
    assert [item["code"] for item in response.json()["items"]] == ["CBC"]


def test_unhiding_returns_a_record_to_the_granted_listing(client: TestClient, cast: Cast) -> None:
    """The other half of ``test_a_hidden_record_never_appears_in_a_granted_listing``: the
    disappearance is reversible, and the scope beside the page never moved."""
    record_id = _upload(client, cast, "CBC")
    _grant_cbc(client, cast)
    _hide(client, cast, record_id)
    assert _granted_records(client, cast)["items"] == []

    _hide(client, cast, record_id, hidden=False)

    listed = _granted_records(client, cast)
    assert [item["id"] for item in listed["items"]] == [record_id]
    assert [category["code"] for category in listed["grantedCategories"]] == ["CBC"]


def test_the_uploading_hospital_still_reads_a_record_the_patient_hid(
    client: TestClient, cast: Cast
) -> None:
    """ADR-013 layer 2 is untouched by hiding, and under D1 (any owned record) this is now
    a reachable combination rather than a hypothetical: a hospital upload, hidden by its
    patient, is still readable by the hospital that filed it. The patient-facing wording
    says so rather than implying a guarantee the authorization model does not give."""
    record_id = _upload(client, cast, "CBC")

    _hide(client, cast, record_id)

    assert client.get(f"{RECORDS}/{record_id}", headers=cast.admin_tmh).status_code == 200
    listed = client.get(RECORDS, headers=cast.admin_tmh).json()["items"]
    assert [item["id"] for item in listed] == [record_id]
    assert listed[0]["isHidden"] is True


def test_a_clinician_cannot_change_a_patients_visibility_setting(
    client: TestClient, cast: Cast
) -> None:
    """The inverse of the whole feature: a grant lets a clinician read a record, never
    un-hide one. Refused by the role gate, before any record is looked up."""
    record_id = _upload(client, cast, "CBC")
    _grant_cbc(client, cast)
    _hide(client, cast, record_id)

    for headers in (cast.doctor_cmc, cast.admin_tmh):
        refused = client.patch(
            f"{RECORDS}/{record_id}/visibility", json={"isHidden": False}, headers=headers
        )
        assert refused.status_code == 403

    assert client.get(f"{RECORDS}/{record_id}", headers=cast.doctor_cmc).status_code == 404
