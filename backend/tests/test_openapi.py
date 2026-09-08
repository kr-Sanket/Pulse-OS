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


def test_hospital_audit_endpoint_is_present_and_paginated() -> None:
    operation = _spec()["paths"]["/api/v1/hospitals/me/audit-logs"]["get"]
    parameters = {parameter["name"] for parameter in operation["parameters"]}

    assert set(operation["responses"]) >= {"200", "422"}
    # Cursor pagination, and **no hospital parameter**: the scope is the caller's own
    # hospital, derived server-side, so no query string can reach another one (ADR-023).
    assert parameters == {"cursor", "limit"}


def test_hospital_audit_response_discloses_activity_not_patients() -> None:
    """The allow-list guard: a hospital's operational log must not become a patient index,
    and tamper evidence belongs to the subject of the trail."""
    properties = _spec()["components"]["schemas"]["HospitalAuditEventResponse"]["properties"]

    assert set(properties) == {
        "id",
        "action",
        "actorUserId",
        "actorRole",
        "actor",
        "targetRecordId",
        "occurredAt",
    }
    leaked = {"patientId", "eventHash", "hashVersion", "requestContext", "actorHospitalId"}
    assert leaked.isdisjoint(properties)


def test_the_patient_audit_contract_is_unchanged_by_the_hospital_view() -> None:
    """Two scopes over one table; the patient's response shape must not drift because a
    hospital gained its own.

    ``actorHospital`` was added deliberately by ADR-025 — the historical attribution the
    patient's trail groups on. It is the patient projection only: the assertion below that
    the hospital's own response did *not* acquire it is the half that still guards ADR-023's
    separation.
    """
    schemas = _spec()["components"]["schemas"]

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
    # The hospital reads its own activity; every row already has its hospital, and
    # publishing one per row would be noise at best (ADR-023 §5).
    assert "actorHospital" not in schemas["HospitalAuditEventResponse"]["properties"]


def test_the_audit_hospital_is_the_public_organisation_pair() -> None:
    """``hid`` and ``name`` — the same shape a patient already sees against every record,
    and nothing that would turn an organisation into a profile."""
    properties = _spec()["components"]["schemas"]["AuditHospitalResponse"]["properties"]
    assert set(properties) == {"hid", "name"}


def test_the_staff_projection_still_carries_the_current_affiliation() -> None:
    """ADR-025 splits two questions rather than replacing one. ``StaffDisplayResponse`` is
    still where "where does this person work now" is answered, for the consent inbox and
    the grants list; the audit trail simply stops using it for attribution."""
    properties = _spec()["components"]["schemas"]["StaffDisplayResponse"]["properties"]
    assert set(properties) == {"fullName", "specialty", "hospitalName"}


def test_the_four_rate_limited_endpoints_declare_429() -> None:
    """The spec must say which surfaces are throttled (ADR-024): a client that cannot see
    429 in the contract has no reason to handle it."""
    paths = _spec()["paths"]
    protected = (
        ("/api/v1/patients/lookup", "get"),
        ("/api/v1/records/existence", "get"),
        ("/api/v1/granted-records", "get"),
        ("/api/v1/access-requests", "post"),
    )

    for path, method in protected:
        assert "429" in paths[path][method]["responses"], f"{method.upper()} {path}"


def test_unprotected_endpoints_do_not_claim_a_429_they_cannot_return() -> None:
    paths = _spec()["paths"]

    assert "429" not in paths["/api/v1/record-categories"]["get"]["responses"]
    assert "429" not in paths["/api/v1/audit-logs"]["get"]["responses"]
    assert "429" not in paths["/api/v1/records"]["get"]["responses"]


def test_rate_limiting_added_no_request_parameter() -> None:
    """The limiter keys on the authenticated identity, so nothing about it is client-supplied
    — no bucket, no quota, nothing a caller could tamper with."""
    operation = _spec()["paths"]["/api/v1/patients/lookup"]["get"]

    assert {parameter["name"] for parameter in operation["parameters"]} == {"healthId"}


def test_record_listing_declares_its_sort_and_search_query() -> None:
    """The parameters the patient portal's controls are generated from."""
    operation = _spec()["paths"]["/api/v1/records"]["get"]
    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}
    assert set(parameters) == {"category", "search", "sort", "cursor", "limit"}
    assert all(parameters[name]["in"] == "query" for name in parameters)
    assert all(parameters[name].get("required", False) is False for name in parameters)


def test_the_sort_parameter_is_a_closed_vocabulary_defaulting_to_newest() -> None:
    """An enum rather than a free string, so the client is generated with the two values
    and an unknown one is a 422 from FastAPI rather than a silent fallback."""
    spec = _spec()
    operation = spec["paths"]["/api/v1/records"]["get"]
    sort = next(p for p in operation["parameters"] if p["name"] == "sort")
    schema = sort["schema"]
    reference = schema.get("$ref") or next(
        (option["$ref"] for option in schema.get("allOf", []) if "$ref" in option), None
    )
    if reference is not None:
        enum_name = reference.rsplit("/", 1)[-1]
        assert spec["components"]["schemas"][enum_name]["enum"] == ["newest", "oldest"]
    else:
        assert schema["enum"] == ["newest", "oldest"]
    assert schema.get("default", sort.get("schema", {}).get("default")) == "newest"


def test_the_record_listing_search_is_length_bounded() -> None:
    """An unbounded LIKE term is a cheap way to make the database work hard."""
    operation = _spec()["paths"]["/api/v1/records"]["get"]
    search = next(p for p in operation["parameters"] if p["name"] == "search")
    schema = search["schema"]
    constraints = (
        schema
        if "maxLength" in schema
        else next(option for option in schema.get("anyOf", []) if option.get("type") == "string")
    )
    assert constraints["maxLength"] == 100
    assert constraints["minLength"] == 1
