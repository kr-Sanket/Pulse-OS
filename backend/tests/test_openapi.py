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


def test_m4_existence_projection_is_present_and_declares_its_failures() -> None:
    spec = _spec()
    operation = spec["paths"]["/api/v1/records/existence"]["get"]
    assert set(operation["responses"]) >= {"200", "422"}
    (parameter,) = operation["parameters"]
    assert parameter["name"] == "patientHealthId"
    assert parameter["in"] == "query" and parameter["required"] is True


def test_existence_response_exposes_presence_only() -> None:
    """The contract guard for the endpoint's whole purpose: a code and a display name per
    category, and nothing that identifies a document or counts one."""
    schemas = _spec()["components"]["schemas"]

    assert set(schemas["RecordExistenceResponse"]["properties"]) == {"items"}
    # Its item type is the category vocabulary shape — two fields, no more.
    assert set(schemas["RecordCategoryResponse"]["properties"]) == {"code", "displayName"}
    leaked = {
        "id",
        "originalFilename",
        "uploadedByHospital",
        "sizeBytes",
        "description",
        "dateOfService",
        "contentType",
        "s3Key",
        "recordCount",
    }
    assert not leaked & set(schemas["RecordCategoryResponse"]["properties"])


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


def test_m4_granted_record_listing_is_present_and_declares_its_query() -> None:
    spec = _spec()
    operation = spec["paths"]["/api/v1/granted-records"]["get"]
    assert set(operation["responses"]) >= {"200", "422"}
    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}
    assert set(parameters) == {"patientHealthId", "cursor", "limit"}
    assert parameters["patientHealthId"]["in"] == "query"
    assert parameters["patientHealthId"]["required"] is True


def test_granted_record_schema_is_a_chooser_not_a_document() -> None:
    """ADR-020's disclosure allow-list, pinned. Widening it must be a deliberate edit to
    GrantedRecordResponse — never a side effect of adding a field for patients."""
    schemas = _spec()["components"]["schemas"]

    assert set(schemas["GrantedRecordResponse"]["properties"]) == {
        "id",
        "categoryCode",
        "categoryDisplayName",
        "origin",
        "dateOfService",
        "uploadedByHospital",
        "createdAt",
    }
    withheld = {
        "originalFilename",
        "description",
        "sizeBytes",
        "contentType",
        "processingStatus",
        "s3Key",
        "patientId",
        "uploadedByDoctorId",
        "isHidden",
    }
    assert not withheld & set(schemas["GrantedRecordResponse"]["properties"])


def test_granted_record_listing_reports_the_scope_beside_the_page() -> None:
    schemas = _spec()["components"]["schemas"]

    assert set(schemas["GrantedRecordListResponse"]["properties"]) == {
        "grantedCategories",
        "items",
        "nextCursor",
    }


def test_patient_lookup_is_present_and_declares_its_failures() -> None:
    spec = _spec()
    operation = spec["paths"]["/api/v1/patients/lookup"]["get"]
    assert set(operation["responses"]) >= {"200", "422"}
    (parameter,) = operation["parameters"]
    assert parameter["name"] == "healthId"
    assert parameter["in"] == "query" and parameter["required"] is True


def test_patient_lookup_response_discloses_identity_confirmation_only() -> None:
    """The contract guard for the endpoint's whole purpose: a Health ID and a name, and
    nothing that would turn identity confirmation into a patient-data read."""
    schemas = _spec()["components"]["schemas"]

    assert set(schemas["PatientLookupResponse"]["properties"]) == {"healthId", "fullName"}
    leaked = {"dateOfBirth", "gender", "createdAt", "id", "userId", "phone", "email"}
    assert leaked.isdisjoint(schemas["PatientLookupResponse"]["properties"])


def test_records_existence_contract_is_unchanged_by_the_lookup() -> None:
    """The clinician discovery endpoint has its own disclosure contract and is deliberately
    not widened or repurposed by the hospital lookup: still DOCTOR-only, still presence."""
    spec = _spec()
    operation = spec["paths"]["/api/v1/records/existence"]["get"]
    (parameter,) = operation["parameters"]

    assert parameter["name"] == "patientHealthId"
    assert set(spec["components"]["schemas"]["RecordExistenceResponse"]["properties"]) == {"items"}
