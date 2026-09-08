"""HTTP tests for the consent endpoints: role gates, status codes, RFC 7807 bodies, and
the OpenAPI contract.

The consent routers are not mounted in ``app.main`` yet (that lands with the records
integration), so these tests build a throwaway app with the same middleware and exception
handlers the real one installs. When the routers are mounted, this fixture collapses into
the shared ``client``/``sqlite_db`` fixtures in conftest.py and the contract pins below
move to test_openapi.py.
"""

import datetime as dt
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from app.core.db import Base, create_session_factory, get_db_session
from app.core.errors import register_exception_handlers
from app.core.middleware import RequestContextMiddleware
from app.core.ratelimit import UnlimitedRateLimiter, get_rate_limiter
from app.modules.auth.dependencies import get_auth_provider
from app.modules.auth.domain import Role
from app.modules.auth.fake import FakeAuthProvider
from app.modules.auth.models import User
from app.modules.consent.dependencies import (
    get_category_vocabulary_source,
    get_clinician_directory,
    to_http_error,
)
from app.modules.consent.errors import (
    AccessDeniedError,
    ClinicianNotActiveError,
    ClinicianProfileNotFoundError,
    ConsentError,
    DuplicateDecisionError,
    DuplicateGrantError,
    DuplicateRequestCategoryError,
    EmptyCategorySelectionError,
    GrantNotFoundError,
    PatientProfileNotFoundError,
    RequestNotDecidableError,
    RequestNotFoundError,
    UnknownPatientError,
    UnrequestedCategoryError,
)
from app.modules.consent.router import (
    access_requests_router,
    audit_logs_router,
    consent_grants_router,
)
from app.modules.patients.models import Patient
from app.modules.records.models import (
    Doctor,
    DoctorStatus,
    Hospital,
    HospitalVerificationStatus,
    RecordCategory,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.support import (
    FakeCategoryVocabularySource,
    FakeClinicianDirectory,
    create_sqlite_test_engine,
    run_with_session,
)

API = "/api/v1"
REQUESTS = f"{API}/access-requests"
GRANTS = f"{API}/consent-grants"
AUDIT = f"{API}/audit-logs"
HEALTH_ID = "PHI-IND-2026-1QE8DVR"
#: The second patient the fixture seeds — used to prove two subjects are told apart.
OTHER_HEALTH_ID = "PHI-IND-2026-5WD2FD4"
PROBLEM_JSON = "application/problem+json"


@dataclass
class World:
    client: TestClient
    clinicians: FakeClinicianDirectory
    doctor: dict[str, str]
    patient: dict[str, str]
    other_patient: dict[str, str]
    doctor_user_id: UUID


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _consent_app() -> FastAPI:
    application = FastAPI()
    application.add_middleware(RequestContextMiddleware)
    register_exception_handlers(application)
    application.include_router(access_requests_router, prefix=API)
    application.include_router(consent_grants_router, prefix=API)
    application.include_router(audit_logs_router, prefix=API)
    return application


@pytest.fixture
def consent_app() -> FastAPI:
    return _consent_app()


@pytest.fixture
def world(consent_app: FastAPI) -> Iterator[World]:
    engine: AsyncEngine = create_sqlite_test_engine()

    import asyncio

    async def _schema() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(_schema())

    async def arrange(session: AsyncSession) -> dict[str, Any]:
        doctor_user = User(firebase_uid="fb-doctor", role=Role.DOCTOR)
        patient_user = User(firebase_uid="fb-patient", role=Role.PATIENT)
        other_user = User(firebase_uid="fb-other", role=Role.PATIENT)
        session.add_all([doctor_user, patient_user, other_user])
        hospital = Hospital(
            hid="HID-0001", name="TMH", verification_status=HospitalVerificationStatus.VERIFIED
        )
        session.add(hospital)
        await session.flush()
        doctor = Doctor(
            user_id=doctor_user.id,
            hospital_id=hospital.id,
            full_name="Dr Verma",
            registration_number="R1",
            status=DoctorStatus.ACTIVE,
        )
        session.add_all(
            [
                doctor,
                Patient(user_id=patient_user.id, health_id=HEALTH_ID, full_name="Aarav"),
                Patient(user_id=other_user.id, health_id="PHI-IND-2026-5WD2FD4", full_name="Meera"),
                RecordCategory(code="CBC", display_name="CBC"),
                RecordCategory(code="MRI", display_name="MRI"),
                RecordCategory(code="XRAY", display_name="XRAY"),
            ]
        )
        await session.flush()
        return {
            "doctor_user_id": doctor_user.id,
            "patient_user_id": patient_user.id,
            "other_user_id": other_user.id,
            "doctor_id": doctor.id,
            "hospital_id": hospital.id,
            "categories": {
                code: (await session.execute(_select_category(code))).scalar_one().id
                for code in ("CBC", "MRI", "XRAY")
            },
        }

    ids = run_with_session(engine, arrange)

    factory = create_session_factory(engine)

    async def override_session() -> Any:
        async with factory() as session, session.begin():
            yield session

    fake_auth = FakeAuthProvider()
    fake_auth.register_user(
        "doctor", user_id=ids["doctor_user_id"], firebase_uid="fb-doctor", role=Role.DOCTOR
    )
    fake_auth.register_user(
        "patient", user_id=ids["patient_user_id"], firebase_uid="fb-patient", role=Role.PATIENT
    )
    fake_auth.register_user(
        "other", user_id=ids["other_user_id"], firebase_uid="fb-other", role=Role.PATIENT
    )
    # Valid claims, no profile row — the 404-class condition each listing must handle.
    fake_auth.register_user(
        "ghost-patient", user_id=uuid4(), firebase_uid="fb-ghost-p", role=Role.PATIENT
    )
    fake_auth.register_user(
        "ghost-doctor", user_id=uuid4(), firebase_uid="fb-ghost-d", role=Role.DOCTOR
    )
    clinicians = FakeClinicianDirectory()
    clinicians.register(
        ids["doctor_user_id"], doctor_id=ids["doctor_id"], hospital_id=ids["hospital_id"]
    )
    vocabulary = FakeCategoryVocabularySource(ids["categories"])

    # This suite builds its own app, so conftest's autouse override does not reach it
    # and app.state carries no limiter (TODO §4: fold these pins into test_openapi).
    consent_app.dependency_overrides[get_rate_limiter] = lambda: UnlimitedRateLimiter()
    consent_app.dependency_overrides[get_db_session] = override_session
    consent_app.dependency_overrides[get_auth_provider] = lambda: fake_auth
    consent_app.dependency_overrides[get_clinician_directory] = lambda: clinicians
    consent_app.dependency_overrides[get_category_vocabulary_source] = lambda: vocabulary

    with TestClient(consent_app) as client:
        yield World(
            client=client,
            clinicians=clinicians,
            doctor=_bearer("doctor"),
            patient=_bearer("patient"),
            other_patient=_bearer("other"),
            doctor_user_id=ids["doctor_user_id"],
        )


def _select_category(code: str) -> Any:
    from sqlalchemy import select

    return select(RecordCategory).where(RecordCategory.code == code)


def _create(world: World, *codes: str, **overrides: Any) -> httpx.Response:
    body: dict[str, Any] = {
        "patientHealthId": HEALTH_ID,
        "categoryCodes": list(codes),
        "purpose": "follow-up",
        **overrides,
    }
    response: httpx.Response = world.client.post(REQUESTS, json=body, headers=world.doctor)
    return response


# -- happy path ------------------------------------------------------------------------


def test_create_request_returns_201_with_camel_case_and_normalized_codes(world: World) -> None:
    response = _create(world, "cbc", " mri ")
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == {
        "id",
        "status",
        "purpose",
        "categoryCodes",
        "requesterDoctorId",
        "requesterHospitalId",
        "expiresAt",
        "createdAt",
    }
    assert body["status"] == "PENDING"
    assert sorted(body["categoryCodes"]) == ["CBC", "MRI"]
    assert response.headers["X-Request-Id"]


def test_inbox_and_sent_listings(world: World) -> None:
    request_id = _create(world, "CBC", "MRI").json()["id"]

    inbox = world.client.get(f"{REQUESTS}/inbox", headers=world.patient)
    assert inbox.status_code == 200
    assert [item["id"] for item in inbox.json()["items"]] == [request_id]
    assert inbox.json()["nextCursor"] is None

    sent = world.client.get(f"{REQUESTS}/sent", headers=world.doctor)
    assert [item["id"] for item in sent.json()["items"]] == [request_id]

    # Another patient never sees it.
    assert world.client.get(f"{REQUESTS}/inbox", headers=world.other_patient).json()["items"] == []


def test_the_sent_listing_names_the_patient_but_the_inbox_does_not(world: World) -> None:
    """The whole point of the field: a doctor's own listing is unreadable without knowing
    who each request is about. The patient's inbox is unchanged — every row is theirs."""
    _create(world, "CBC")

    sent = world.client.get(f"{REQUESTS}/sent", headers=world.doctor)
    inbox = world.client.get(f"{REQUESTS}/inbox", headers=world.patient)

    assert sent.status_code == 200, sent.text
    assert sent.json()["items"][0]["patientHealthId"] == HEALTH_ID
    assert inbox.status_code == 200
    assert "patientHealthId" not in inbox.json()["items"][0]


def test_the_sent_listing_exposes_nothing_else_off_the_patient_row(world: World) -> None:
    _create(world, "CBC")

    item = world.client.get(f"{REQUESTS}/sent", headers=world.doctor).json()["items"][0]

    assert set(item) == {
        "id",
        "status",
        "purpose",
        "categoryCodes",
        "requester",
        "requesterDoctorId",
        "requesterHospitalId",
        "requesterHospitalName",
        "expiresAt",
        "createdAt",
        "patientHealthId",
    }
    # No name, no date of birth, no internal patient id.
    assert not {"patientName", "fullName", "dateOfBirth", "patientId"} & set(item)


def test_the_sent_listing_distinguishes_two_patients(world: World) -> None:
    """The duplicate-detection use case: two requests, two subjects, told apart."""
    _create(world, "CBC")
    _create(world, "MRI", patientHealthId=OTHER_HEALTH_ID)

    items = world.client.get(f"{REQUESTS}/sent", headers=world.doctor).json()["items"]

    assert {item["patientHealthId"] for item in items} == {HEALTH_ID, OTHER_HEALTH_ID}


def test_creating_a_request_still_answers_without_a_subject(world: World) -> None:
    """The write path is untouched: the requester just supplied the Health ID."""
    created = _create(world, "CBC")

    assert created.status_code == 201
    assert "patientHealthId" not in created.json()


def test_approve_then_reject_closes_the_request(world: World) -> None:
    request_id = _create(world, "CBC", "MRI").json()["id"]

    approved = world.client.post(
        f"{REQUESTS}/{request_id}/approve", json={"categoryCodes": ["CBC"]}, headers=world.patient
    )
    assert approved.status_code == 200
    body = approved.json()
    assert body["requestStatus"] == "PENDING"
    assert [d["categoryCode"] for d in body["decisions"]] == ["CBC"]
    assert body["decisions"][0]["status"] == "APPROVED"
    assert len(body["grants"]) == 1
    assert body["grants"][0]["revokedAt"] is None

    rejected = world.client.post(
        f"{REQUESTS}/{request_id}/reject", json={"categoryCodes": ["MRI"]}, headers=world.patient
    )
    assert rejected.status_code == 200
    assert rejected.json()["requestStatus"] == "DECIDED"
    assert rejected.json()["grants"] == []


def _instant(value: str) -> dt.datetime:
    """Parse a wire timestamp as UTC.

    Normalisation is needed because the two revoke responses below do not agree on the
    offset suffix: the first serialises the aware value the service just assigned, the
    second serialises the same column read back, which SQLite returns naive for a
    ``DateTime(timezone=True)`` column. Postgres returns aware in both cases. The test
    asserts the property that matters — the same instant — rather than encoding a
    backend-specific string; the serialisation gap itself is reported separately.
    """
    parsed = dt.datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def test_revoke_is_idempotent(world: World) -> None:
    request_id = _create(world, "CBC").json()["id"]
    grant = world.client.post(
        f"{REQUESTS}/{request_id}/approve", json={"categoryCodes": ["CBC"]}, headers=world.patient
    ).json()["grants"][0]

    first = world.client.post(f"{GRANTS}/{grant['id']}/revoke", headers=world.patient)
    assert first.status_code == 200
    assert first.json()["revokedAt"] is not None
    second = world.client.post(f"{GRANTS}/{grant['id']}/revoke", headers=world.patient)
    assert second.status_code == 200
    # Revoking twice records one revocation: the same instant, not a fresh one.
    assert _instant(second.json()["revokedAt"]) == _instant(first.json()["revokedAt"])
    assert second.json()["id"] == first.json()["id"]


def _grant_one(world: World, code: str = "CBC") -> dict[str, Any]:
    """Raise a request and approve one category, returning the grant that produced."""
    request_id = _create(world, code).json()["id"]
    approved = world.client.post(
        f"{REQUESTS}/{request_id}/approve", json={"categoryCodes": [code]}, headers=world.patient
    )
    grant: dict[str, Any] = approved.json()["grants"][0]
    return grant


def test_grant_listing_returns_the_patients_grants_with_their_state(world: World) -> None:
    granted = _grant_one(world)

    listed = world.client.get(GRANTS, headers=world.patient)

    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["nextCursor"] is None
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert set(item) == {
        "id",
        "categoryCode",
        "granteeDoctorId",
        "grantedAt",
        "expiresAt",
        "revokedAt",
        "status",
        "grantee",
    }
    assert item["id"] == granted["id"]
    assert item["categoryCode"] == "CBC"
    assert item["revokedAt"] is None
    assert item["status"] == "ACTIVE"
    assert item["grantee"] == {
        "fullName": "Dr Verma",
        "specialty": None,
        "hospitalName": "TMH",
    }


def test_a_revoked_grant_stays_in_the_listing_and_says_so(world: World) -> None:
    """Withdrawn access is history the owner keeps seeing, not a row that disappears."""
    granted = _grant_one(world)
    revoked = world.client.post(f"{GRANTS}/{granted['id']}/revoke", headers=world.patient)
    assert revoked.status_code == 200, revoked.text

    item = world.client.get(GRANTS, headers=world.patient).json()["items"][0]

    assert item["id"] == granted["id"]
    assert item["status"] == "REVOKED"
    assert item["revokedAt"] is not None


def test_grant_listing_is_scoped_to_the_caller(world: World) -> None:
    _grant_one(world)

    assert world.client.get(GRANTS, headers=world.other_patient).json()["items"] == []


def test_grant_listing_cursor_pagination_over_http(world: World) -> None:
    created = {_grant_one(world)["id"] for _ in range(3)}

    first = world.client.get(GRANTS, params={"limit": 2}, headers=world.patient)
    assert len(first.json()["items"]) == 2
    cursor = first.json()["nextCursor"]
    assert cursor is not None
    second = world.client.get(GRANTS, params={"limit": 2, "cursor": cursor}, headers=world.patient)
    assert len(second.json()["items"]) == 1
    assert second.json()["nextCursor"] is None
    seen = {item["id"] for item in first.json()["items"] + second.json()["items"]}
    assert seen == created


def test_cursor_pagination_over_http(world: World) -> None:
    created = {_create(world, "CBC").json()["id"] for _ in range(3)}
    first = world.client.get(f"{REQUESTS}/inbox", params={"limit": 2}, headers=world.patient)
    assert len(first.json()["items"]) == 2
    cursor = first.json()["nextCursor"]
    assert cursor is not None
    second = world.client.get(
        f"{REQUESTS}/inbox", params={"limit": 2, "cursor": cursor}, headers=world.patient
    )
    assert len(second.json()["items"]) == 1
    assert second.json()["nextCursor"] is None
    seen = {item["id"] for item in first.json()["items"] + second.json()["items"]}
    assert seen == created


def test_the_inbox_names_the_clinician_and_the_hospital_that_asked(world: World) -> None:
    request_id = _create(world, "CBC").json()["id"]

    inbox = world.client.get(f"{REQUESTS}/inbox", headers=world.patient)

    assert inbox.status_code == 200, inbox.text
    item = inbox.json()["items"][0]
    assert item["id"] == request_id
    assert item["requester"] == {
        "fullName": "Dr Verma",
        "specialty": None,
        "hospitalName": "TMH",
    }
    assert item["requesterHospitalName"] == "TMH"
    # The ids the projection was built from are still there, unchanged.
    assert item["requesterDoctorId"] is not None
    assert item["requesterHospitalId"] is not None


def test_creating_a_request_is_unchanged_by_the_projection(world: World) -> None:
    """The write path answers the requester themselves, so it stays free of the lookup."""
    created = _create(world, "CBC")

    assert created.status_code == 201
    assert "requester" not in created.json()


def test_the_trail_returns_the_patients_events_with_stored_identifiers(world: World) -> None:
    request_id = _create(world, "CBC").json()["id"]
    world.client.post(
        f"{REQUESTS}/{request_id}/approve", json={"categoryCodes": ["CBC"]}, headers=world.patient
    )

    listed = world.client.get(AUDIT, headers=world.patient)

    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["nextCursor"] is None
    assert [item["action"] for item in body["items"]] == ["CONSENT_APPROVED", "ACCESS_REQUESTED"]

    approval, asked = body["items"]
    assert set(approval) == {
        "id",
        "action",
        "actorUserId",
        "actorRole",
        "actor",
        "actorHospital",
        "targetRecordId",
        "targetCategoryCode",
        "targetRequestId",
        "occurredAt",
        "eventHash",
    }
    # The decision targets a category, by code; the request targets the request itself.
    assert approval["actorRole"] == "PATIENT"
    assert approval["targetCategoryCode"] == "CBC"
    assert approval["targetRecordId"] is None
    assert asked["actorRole"] == "DOCTOR"
    assert asked["actorUserId"] == str(world.doctor_user_id)
    assert asked["targetRequestId"] == request_id
    assert len(asked["eventHash"]) == 64
    # ADR-025: the organisation comes from the event, and a patient's own action has none.
    assert approval["actorHospital"] is None
    assert asked["actorHospital"] == {"hid": "HID-0001", "name": "TMH"}
    # The clinician who asked is named; the patient's own decision is not — actorRole
    # already says it was them, and this module knows no name for a patient.
    assert asked["actor"] == {"fullName": "Dr Verma", "specialty": None, "hospitalName": "TMH"}
    assert approval["actor"] is None


def test_the_trail_is_scoped_to_the_caller(world: World) -> None:
    _create(world, "CBC")

    assert world.client.get(AUDIT, headers=world.other_patient).json()["items"] == []


def test_trail_cursor_pagination_over_http(world: World) -> None:
    for _ in range(3):
        _create(world, "CBC")

    first = world.client.get(AUDIT, params={"limit": 2}, headers=world.patient)
    assert len(first.json()["items"]) == 2
    cursor = first.json()["nextCursor"]
    assert cursor is not None
    second = world.client.get(AUDIT, params={"limit": 2, "cursor": cursor}, headers=world.patient)
    assert len(second.json()["items"]) == 1
    assert second.json()["nextCursor"] is None
    seen = {item["id"] for item in first.json()["items"] + second.json()["items"]}
    assert len(seen) == 3


def test_reading_the_trail_leaves_it_unchanged(world: World) -> None:
    _create(world, "CBC")
    before = world.client.get(AUDIT, headers=world.patient).json()["items"]

    after = world.client.get(AUDIT, headers=world.patient).json()["items"]

    assert [item["id"] for item in after] == [item["id"] for item in before]


# -- authn / authz ---------------------------------------------------------------------


def test_every_endpoint_requires_authentication(world: World) -> None:
    unauthenticated = [
        world.client.post(REQUESTS, json={}),
        world.client.get(f"{REQUESTS}/inbox"),
        world.client.get(f"{REQUESTS}/sent"),
        world.client.post(f"{REQUESTS}/{uuid4()}/approve", json={"categoryCodes": ["CBC"]}),
        world.client.post(f"{REQUESTS}/{uuid4()}/reject", json={"categoryCodes": ["CBC"]}),
        world.client.get(GRANTS),
        world.client.post(f"{GRANTS}/{uuid4()}/revoke"),
        world.client.get(AUDIT),
    ]
    assert [response.status_code for response in unauthenticated] == [401] * 8
    assert all(response.headers["WWW-Authenticate"] == "Bearer" for response in unauthenticated)


def test_role_gates_reject_the_wrong_role(world: World) -> None:
    request_id = _create(world, "CBC").json()["id"]
    patient_only = [
        world.client.get(f"{REQUESTS}/inbox", headers=world.doctor),
        world.client.post(
            f"{REQUESTS}/{request_id}/approve",
            json={"categoryCodes": ["CBC"]},
            headers=world.doctor,
        ),
        world.client.get(GRANTS, headers=world.doctor),
        world.client.post(f"{GRANTS}/{uuid4()}/revoke", headers=world.doctor),
        world.client.get(AUDIT, headers=world.doctor),
    ]
    assert [response.status_code for response in patient_only] == [403] * 5

    doctor_only = [
        world.client.get(f"{REQUESTS}/sent", headers=world.patient),
        world.client.post(REQUESTS, json={}, headers=world.patient),
    ]
    assert [response.status_code for response in doctor_only] == [403] * 2


def test_a_suspended_clinician_cannot_raise_a_request_but_can_read_its_own_list(
    world: World,
) -> None:
    world.clinicians.suspend(world.doctor_user_id)
    refused = _create(world, "CBC")
    assert refused.status_code == 403
    assert refused.json()["detail"] == "Your clinician profile is not active at its hospital."
    assert world.client.get(f"{REQUESTS}/sent", headers=world.doctor).status_code == 200


def test_another_patients_request_and_grant_answer_404_not_403(world: World) -> None:
    request_id = _create(world, "CBC").json()["id"]
    intruder = world.client.post(
        f"{REQUESTS}/{request_id}/approve",
        json={"categoryCodes": ["CBC"]},
        headers=world.other_patient,
    )
    assert intruder.status_code == 404
    assert world.client.post(f"{GRANTS}/{uuid4()}/revoke", headers=world.patient).status_code == 404


# -- error mapping ---------------------------------------------------------------------


def test_error_mapping_matrix(world: World) -> None:
    request_id = _create(world, "CBC").json()["id"]

    unknown_category = _create(world, "NOT_A_CODE")
    assert unknown_category.status_code == 422
    assert "NOT_A_CODE" in unknown_category.json()["detail"]

    unknown_patient = _create(world, "CBC", patientHealthId="PHI-IND-2026-ZZZZZZZ")
    assert unknown_patient.status_code == 422
    assert unknown_patient.json()["detail"] == "Unknown patient Health ID."

    not_requested = world.client.post(
        f"{REQUESTS}/{request_id}/approve",
        json={"categoryCodes": ["XRAY"]},
        headers=world.patient,
    )
    assert not_requested.status_code == 422

    assert (
        world.client.post(
            f"{REQUESTS}/{request_id}/approve",
            json={"categoryCodes": ["CBC"]},
            headers=world.patient,
        ).status_code
        == 200
    )
    already = world.client.post(
        f"{REQUESTS}/{request_id}/reject", json={"categoryCodes": ["CBC"]}, headers=world.patient
    )
    assert already.status_code == 409
    assert "DECIDED" in already.json()["detail"]

    assert (
        world.client.post(
            f"{REQUESTS}/{uuid4()}/approve", json={"categoryCodes": ["CBC"]}, headers=world.patient
        ).status_code
        == 404
    )


def test_request_validation_rejects_unknown_fields_blanks_and_bad_paging(world: World) -> None:
    assert _create(world, "CBC", surprise=1).status_code == 422  # extra="forbid"
    assert _create(world).status_code == 422  # empty categoryCodes
    assert _create(world, "CBC", purpose="   ").status_code == 422  # blank purpose
    assert _create(world, "  ").status_code == 422  # blank category code
    assert (
        world.client.get(
            f"{REQUESTS}/inbox", params={"cursor": "garbage"}, headers=world.patient
        ).status_code
        == 422
    )
    assert (
        world.client.get(
            f"{REQUESTS}/inbox", params={"limit": 101}, headers=world.patient
        ).status_code
        == 422
    )
    assert (
        world.client.get(GRANTS, params={"cursor": "garbage"}, headers=world.patient).status_code
        == 422
    )
    assert world.client.get(GRANTS, params={"limit": 0}, headers=world.patient).status_code == 422
    assert (
        world.client.get(AUDIT, params={"cursor": "garbage"}, headers=world.patient).status_code
        == 422
    )
    assert world.client.get(AUDIT, params={"limit": 101}, headers=world.patient).status_code == 422


def test_error_responses_are_rfc7807_problem_json(world: World) -> None:
    response = world.client.post(
        f"{REQUESTS}/{uuid4()}/approve", json={"categoryCodes": ["CBC"]}, headers=world.patient
    )
    assert response.status_code == 404
    assert response.headers["content-type"].startswith(PROBLEM_JSON)
    body = response.json()
    assert body["type"] == "about:blank"
    assert body["title"] == "Not Found"
    assert body["status"] == 404
    assert body["instance"].startswith(f"{REQUESTS}/")
    assert body["detail"] == "Access request not found."
    assert response.headers["X-Request-Id"]


def test_validation_errors_carry_a_field_list(world: World) -> None:
    response = _create(world, "CBC", purpose="")
    assert response.status_code == 422
    body = response.json()
    assert body["title"] == "Validation Error"
    assert any("purpose" in error["field"] for error in body["errors"])


# -- OpenAPI contract ------------------------------------------------------------------


def test_openapi_declares_every_consent_path_and_its_failures(consent_app: FastAPI) -> None:
    """Pinned here rather than in test_openapi.py because the routers are not mounted in
    the real app yet; move these when they are."""
    spec = consent_app.openapi()
    paths = spec["paths"]
    assert set(paths) == {
        f"{REQUESTS}",
        f"{REQUESTS}/inbox",
        f"{REQUESTS}/sent",
        f"{REQUESTS}/{{request_id}}/approve",
        f"{REQUESTS}/{{request_id}}/reject",
        GRANTS,
        f"{GRANTS}/{{grant_id}}/revoke",
        AUDIT,
    }
    assert set(paths[GRANTS]["get"]["responses"]) >= {"200", "401", "403", "404", "422"}
    assert set(paths[AUDIT]["get"]["responses"]) >= {"200", "401", "403", "404", "422"}
    assert set(paths[REQUESTS]["post"]["responses"]) >= {"201", "401", "403", "404", "422"}
    approve = paths[f"{REQUESTS}/{{request_id}}/approve"]["post"]["responses"]
    assert set(approve) >= {"200", "401", "403", "404", "409", "422"}
    assert list(approve["409"]["content"]) == [PROBLEM_JSON]


def test_openapi_schemas_are_camel_case_and_paginated(consent_app: FastAPI) -> None:
    schemas = consent_app.openapi()["components"]["schemas"]
    assert set(schemas["AccessRequestListResponse"]["properties"]) == {"items", "nextCursor"}
    assert set(schemas["SentAccessRequestListResponse"]["properties"]) == {"items", "nextCursor"}
    # The requester's own item is the inbox item plus the subject, and nothing else.
    assert set(schemas["SentAccessRequestResponse"]["properties"]) == {
        *schemas["AccessRequestListItemResponse"]["properties"],
        "patientHealthId",
    }
    assert "patientHealthId" not in schemas["AccessRequestListItemResponse"]["properties"]
    assert "patientHealthId" not in schemas["AccessRequestResponse"]["properties"]
    assert set(schemas["AccessRequestResponse"]["properties"]) == {
        "id",
        "status",
        "purpose",
        "categoryCodes",
        "requesterDoctorId",
        "requesterHospitalId",
        "expiresAt",
        "createdAt",
    }
    assert set(schemas["DecisionOutcomeResponse"]["properties"]) == {
        "requestId",
        "requestStatus",
        "decisions",
        "grants",
    }
    assert set(schemas["ConsentGrantListResponse"]["properties"]) == {"items", "nextCursor"}
    # The listing item is the single-grant shape plus the derived state, so the two can
    # never disagree about a grant's fields.
    assert set(schemas["ConsentGrantListItemResponse"]["properties"]) == {
        *schemas["ConsentGrantResponse"]["properties"],
        "status",
        "grantee",
    }
    assert "status" not in schemas["ConsentGrantResponse"]["properties"]
    assert "grantee" not in schemas["ConsentGrantResponse"]["properties"]
    # The listing item is the single-request shape plus who asked; the write path keeps its.
    assert set(schemas["AccessRequestListItemResponse"]["properties"]) == {
        *schemas["AccessRequestResponse"]["properties"],
        "requester",
        "requesterHospitalName",
    }
    assert "requester" not in schemas["AccessRequestResponse"]["properties"]
    # One display shape serves all three listings, and it carries no identifier.
    assert set(schemas["StaffDisplayResponse"]["properties"]) == {
        "fullName",
        "specialty",
        "hospitalName",
    }
    assert set(schemas["AuditEventListResponse"]["properties"]) == {"items", "nextCursor"}
    assert set(schemas["AuditEventResponse"]["properties"]) == {
        "id",
        "action",
        "actorUserId",
        "actorRole",
        "actor",
        "actorHospital",
        "targetRecordId",
        "targetCategoryCode",
        "targetRequestId",
        "occurredAt",
        "eventHash",
    }
    # Writes reject unknown fields (docs/API_GUIDELINES.md).
    assert schemas["AccessRequestCreateRequest"].get("additionalProperties") is False
    assert schemas["CategorySelectionRequest"].get("additionalProperties") is False


def test_openapi_never_exposes_internal_record_identifiers(consent_app: FastAPI) -> None:
    """Existence vs content: nothing on the consent surface carries record metadata."""
    schemas = consent_app.openapi()["components"]["schemas"]
    leaked = {
        "s3Key",
        "originalFilename",
        "sizeBytes",
        "dateOfService",
        "contentType",
        # Categories are addressed by code on this surface; the internal id stays internal.
        "targetCategoryId",
        "categoryId",
    }
    for schema in schemas.values():
        assert not leaked & set(schema.get("properties", {}))


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (PatientProfileNotFoundError(), 404),
        (ClinicianProfileNotFoundError(), 404),
        (ClinicianNotActiveError(), 403),
        (RequestNotFoundError(), 404),
        (GrantNotFoundError(), 404),
        (AccessDeniedError(), 404),
        (RequestNotDecidableError("EXPIRED"), 409),
        (DuplicateDecisionError(), 409),
        (DuplicateRequestCategoryError(), 409),
        (DuplicateGrantError(), 409),
        (UnrequestedCategoryError(), 422),
        (UnknownPatientError(), 422),
        (EmptyCategorySelectionError(), 422),
    ],
)
def test_every_consent_error_has_an_explicit_status(
    error: ConsentError, expected_status: int
) -> None:
    """No consent domain error may fall through to the generic 500 branch."""
    assert to_http_error(error).status_code == expected_status


def test_an_unmapped_error_is_a_logged_500(caplog: pytest.LogCaptureFixture) -> None:
    """HTTPException-shaped 500s never reach the unhandled-exception handler, so the
    translator is the only place the cause can be recorded (app/core/errors.py)."""

    class FutureConsentError(ConsentError):
        pass

    with caplog.at_level(logging.ERROR, logger="app.modules.consent.dependencies"):
        assert to_http_error(FutureConsentError()).status_code == 500
    assert any("unmapped consent domain error" in record.message for record in caplog.records)
    assert any(
        getattr(record, "error_type", None) == "FutureConsentError" for record in caplog.records
    )


def test_a_token_without_a_profile_row_gets_404_on_every_listing(world: World) -> None:
    """Exercises the listing error paths: valid claims, no profile."""
    assert (
        world.client.get(f"{REQUESTS}/inbox", headers=_bearer("ghost-patient")).status_code == 404
    )
    assert world.client.get(f"{REQUESTS}/sent", headers=_bearer("ghost-doctor")).status_code == 404
    assert world.client.get(GRANTS, headers=_bearer("ghost-patient")).status_code == 404
    assert world.client.get(AUDIT, headers=_bearer("ghost-patient")).status_code == 404
