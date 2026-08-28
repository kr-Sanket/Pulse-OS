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
