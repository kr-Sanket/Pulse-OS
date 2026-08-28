"""OpenAPI contract guards: the spec the web api-client is generated from (ADR-003).

If these fail, the generated client and the API have drifted — run `make api-client`
and review the openapi.json diff.
"""

from typing import Any

from app.main import create_app


def _spec() -> dict[str, Any]:
    return create_app().openapi()


def test_walking_skeleton_paths_are_present() -> None:
    paths = _spec()["paths"]
    assert "get" in paths["/api/v1/auth/me"]
    assert "post" in paths["/api/v1/patients/register"]
    assert "get" in paths["/api/v1/patients/me"]


def test_m2_paths_are_present() -> None:
    paths = _spec()["paths"]
    assert "post" in paths["/api/v1/hospitals/register"]
    assert "get" in paths["/api/v1/hospitals/me"]
    assert "post" in paths["/api/v1/hospitals/{hid}/verify"]
    assert "get" in paths["/api/v1/hospitals/me/doctors"]
    assert "post" in paths["/api/v1/hospitals/me/doctors/{doctor_id}/activate"]
    assert "post" in paths["/api/v1/hospitals/me/doctors/{doctor_id}/deactivate"]
    assert "post" in paths["/api/v1/doctors/register"]
    assert "get" in paths["/api/v1/doctors/me"]
    assert "post" in paths["/api/v1/records"]
    assert "get" in paths["/api/v1/records"]
    assert "get" in paths["/api/v1/records/{record_id}"]
    assert "post" in paths["/api/v1/records/{record_id}/download-url"]
    assert "get" in paths["/api/v1/record-categories"]


def test_m2_registrations_declare_created_and_idempotent_responses() -> None:
    paths = _spec()["paths"]
    for path in ["/api/v1/hospitals/register", "/api/v1/doctors/register"]:
        responses = paths[path]["post"]["responses"]
        assert "201" in responses and "200" in responses


def test_record_metadata_schema_is_camel_case_on_the_wire() -> None:
    schema = _spec()["components"]["schemas"]["RecordMetadataResponse"]
    assert set(schema["properties"]) == {
        "id",
        "categoryCode",
        "categoryDisplayName",
        "origin",
        "dateOfService",
        "description",
        "originalFilename",
        "contentType",
        "sizeBytes",
        "processingStatus",
        "uploadedByHospital",
        "createdAt",
    }


def test_record_upload_is_multipart_with_camel_case_fields() -> None:
    spec = _spec()
    body = spec["paths"]["/api/v1/records"]["post"]["requestBody"]["content"]
    (media_type,) = body
    assert media_type == "multipart/form-data"
    schema = body[media_type]["schema"]
    if "$ref" in schema:  # FastAPI hoists generated form bodies into components
        schema = spec["components"]["schemas"][schema["$ref"].rsplit("/", 1)[1]]
    fields = set(schema["properties"])
    assert fields == {"file", "categoryCode", "dateOfService", "description", "patientHealthId"}


def test_paginated_listings_expose_items_and_next_cursor() -> None:
    schemas = _spec()["components"]["schemas"]
    for name in ["RecordListResponse", "DoctorListResponse"]:
        assert set(schemas[name]["properties"]) == {"items", "nextCursor"}


def test_register_declares_created_and_idempotent_responses() -> None:
    responses = _spec()["paths"]["/api/v1/patients/register"]["post"]["responses"]
    assert "201" in responses and "200" in responses


def test_profile_schema_is_camel_case_on_the_wire() -> None:
    schema = _spec()["components"]["schemas"]["PatientProfileResponse"]
    assert set(schema["properties"]) == {
        "healthId",
        "fullName",
        "dateOfBirth",
        "gender",
        "createdAt",
    }


def test_registration_schema_requires_full_name_only() -> None:
    schema = _spec()["components"]["schemas"]["PatientRegistrationRequest"]
    assert schema["required"] == ["fullName"]
    assert schema.get("additionalProperties") is False  # unknown fields rejected on writes
