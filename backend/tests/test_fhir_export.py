"""Pure unit tests for FHIR R4 export serializer and subject validator.

No database, no object storage, no HTTP stack.
"""

import json
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from app.modules.patients.models import Gender, Patient
from app.modules.records.errors import (
    ConflictingPatientReferenceError,
    FHIRSerializationError,
    MalformedResourcePayloadError,
)
from app.modules.records.fhir_export import (
    PULSEOS_HEALTH_ID_SYSTEM,
    RESOURCE_PATIENT_REFERENCE_FIELDS,
    build_patient_resource,
    canonical_patient_reference,
    create_fhir_bundle,
    serialize_bundle_to_json,
    validate_and_attach_patient,
)
from app.modules.records.models import MedicalRecord, RecordOrigin


def _dummy_patient(
    *,
    patient_id: UUID | None = None,
    health_id: str = "PHI-IND-2026-TEST999",
    full_name: str = "Aarav Sharma",
    date_of_birth: date | None = date(1985, 5, 20),
    gender: Gender | None = Gender.MALE,
) -> Patient:
    patient = Patient(
        user_id=uuid4(),
        health_id=health_id,
        full_name=full_name,
        date_of_birth=date_of_birth,
        gender=gender,
    )
    patient.id = patient_id or uuid4()
    return patient


def _dummy_record(
    patient_id: UUID,
    *,
    record_id: UUID | None = None,
    category_id: UUID | None = None,
    content_type: str = "application/fhir+json",
) -> MedicalRecord:
    rec = MedicalRecord(
        patient_id=patient_id,
        category_id=category_id or uuid4(),
        origin=RecordOrigin.PATIENT_LOCKER,
        date_of_service=date(2023, 1, 15),
        original_filename="Condition — 2023-01-15.json",
        content_type=content_type,
        size_bytes=100,
        s3_key=f"records/{patient_id}/{record_id or uuid4()}",
    )
    rec.id = record_id or uuid4()
    return rec


# -- Patient Resource Serialization ----------------------------------------------------


def test_build_patient_resource_maps_demographics() -> None:
    patient = _dummy_patient()
    resource = build_patient_resource(patient)

    assert resource["resourceType"] == "Patient"
    assert resource["id"] == str(patient.id)
    assert resource["birthDate"] == "1985-05-20"
    assert resource["gender"] == "male"
    assert resource["identifier"] == [
        {"system": PULSEOS_HEALTH_ID_SYSTEM, "value": patient.health_id}
    ]
    assert resource["name"] == [
        {"use": "official", "text": "Aarav Sharma", "given": ["Aarav"], "family": "Sharma"}
    ]


def test_build_patient_resource_handles_nullable_demographics() -> None:
    patient = _dummy_patient(date_of_birth=None, gender=None, full_name="SingleName")
    resource = build_patient_resource(patient)

    assert "birthDate" not in resource
    assert "gender" not in resource
    assert resource["name"] == [{"use": "official", "text": "SingleName"}]


def test_canonical_patient_reference() -> None:
    patient = _dummy_patient()
    ref = canonical_patient_reference(patient)
    assert ref == {"reference": f"urn:uuid:{patient.id}", "display": "Aarav Sharma"}


# -- Resource-Specific Patient References ---------------------------------------------


@pytest.mark.parametrize(
    ("resource_type", "expected_field"),
    [
        ("Condition", "subject"),
        ("Procedure", "subject"),
        ("MedicationRequest", "subject"),
        ("DiagnosticReport", "subject"),
        ("Immunization", "patient"),
        ("AllergyIntolerance", "patient"),
    ],
)
def test_resource_specific_patient_reference_field(resource_type: str, expected_field: str) -> None:
    assert RESOURCE_PATIENT_REFERENCE_FIELDS[resource_type] == expected_field

    patient = _dummy_patient()
    payload = {"resourceType": resource_type, "id": "res-1", "status": "active"}
    attached = validate_and_attach_patient(payload, patient)

    assert expected_field in attached
    assert attached[expected_field] == {
        "reference": f"urn:uuid:{patient.id}",
        "display": patient.full_name,
    }

    # Verify that the alternate reference field is not present
    alternate_field = "patient" if expected_field == "subject" else "subject"
    assert alternate_field not in attached


def test_immunization_and_allergy_must_use_patient_not_subject() -> None:
    patient = _dummy_patient()

    imm_payload = {"resourceType": "Immunization", "id": "imm-1", "status": "completed"}
    attached_imm = validate_and_attach_patient(imm_payload, patient)
    assert "patient" in attached_imm
    assert "subject" not in attached_imm

    alg_payload = {"resourceType": "AllergyIntolerance", "id": "alg-1", "clinicalStatus": {}}
    attached_alg = validate_and_attach_patient(alg_payload, patient)
    assert "patient" in attached_alg
    assert "subject" not in attached_alg


# -- Conflicting Patient References ---------------------------------------------------


def test_existing_conflicting_subject_reference_is_rejected() -> None:
    patient = _dummy_patient()
    conflicting_uuid = str(uuid4())
    payload = {
        "resourceType": "Condition",
        "id": "c1",
        "subject": {"reference": f"Patient/{conflicting_uuid}"},
    }

    with pytest.raises(ConflictingPatientReferenceError, match="conflicting patient"):
        validate_and_attach_patient(payload, patient)


def test_existing_conflicting_patient_field_on_condition_is_rejected() -> None:
    patient = _dummy_patient()
    conflicting_uuid = str(uuid4())
    payload = {
        "resourceType": "Condition",
        "id": "c1",
        "patient": {"reference": f"urn:uuid:{conflicting_uuid}"},
    }

    with pytest.raises(ConflictingPatientReferenceError, match="conflicting patient"):
        validate_and_attach_patient(payload, patient)


def test_existing_matching_subject_reference_is_accepted_and_canonicalized() -> None:
    patient = _dummy_patient()
    payload = {
        "resourceType": "Condition",
        "id": "c1",
        "subject": {"reference": f"urn:uuid:{patient.id}", "display": "Old Name"},
    }

    attached = validate_and_attach_patient(payload, patient)
    assert attached["subject"] == {
        "reference": f"urn:uuid:{patient.id}",
        "display": patient.full_name,
    }


def test_nested_observation_in_diagnostic_report_conflicting_subject_rejected() -> None:
    patient = _dummy_patient()
    conflicting_uuid = str(uuid4())
    payload = {
        "resourceType": "DiagnosticReport",
        "id": "dr-1",
        "result": [
            {
                "resourceType": "Observation",
                "id": "obs-1",
                "subject": {"reference": f"Patient/{conflicting_uuid}"},
            }
        ],
    }

    with pytest.raises(ConflictingPatientReferenceError, match="conflicting patient"):
        validate_and_attach_patient(payload, patient)


def test_nested_observation_in_diagnostic_report_has_patient_attached() -> None:
    patient = _dummy_patient()
    payload = {
        "resourceType": "DiagnosticReport",
        "id": "dr-1",
        "result": [
            {
                "resourceType": "Observation",
                "id": "obs-1",
                "code": {"text": "Glucose"},
            }
        ],
    }

    attached = validate_and_attach_patient(payload, patient)
    assert attached["subject"] == canonical_patient_reference(patient)
    assert "contained" in attached
    assert len(attached["contained"]) == 1
    obs = attached["contained"][0]
    assert obs["resourceType"] == "Observation"
    assert obs["id"] == "obs-1"
    assert obs["subject"] == canonical_patient_reference(patient)
    assert attached["result"] == [{"reference": "#obs-1", "display": "Glucose"}]


# -- Validation of Stored Payloads ----------------------------------------------------


def test_malformed_json_bytes_raises_error() -> None:
    patient = _dummy_patient()
    with pytest.raises(MalformedResourcePayloadError, match="not valid JSON"):
        validate_and_attach_patient(b"{invalid json", patient)


def test_json_array_raises_error() -> None:
    patient = _dummy_patient()
    with pytest.raises(MalformedResourcePayloadError, match="not a JSON object"):
        validate_and_attach_patient(b"[]", patient)


def test_missing_resource_type_raises_error() -> None:
    patient = _dummy_patient()
    with pytest.raises(MalformedResourcePayloadError, match="no resourceType"):
        validate_and_attach_patient(b'{"id": "test"}', patient)


def test_unsupported_resource_type_raises_error() -> None:
    patient = _dummy_patient()
    with pytest.raises(FHIRSerializationError, match="Unsupported FHIR resource type"):
        validate_and_attach_patient(b'{"resourceType": "CarePlan", "id": "cp1"}', patient)


def test_expected_resource_type_mismatch_raises_error() -> None:
    patient = _dummy_patient()
    with pytest.raises(FHIRSerializationError, match="Resource type mismatch"):
        validate_and_attach_patient(
            b'{"resourceType": "Condition", "id": "c1"}',
            patient,
            expected_resource_type="Procedure",
        )


# -- Bundle Construction --------------------------------------------------------------


def test_empty_export_bundle_contains_patient_and_no_records() -> None:
    patient = _dummy_patient()
    bundle = create_fhir_bundle(patient, [])

    assert bundle["resourceType"] == "Bundle"
    assert bundle["type"] == "collection"
    assert UUID(bundle["id"])
    assert len(bundle["entry"]) == 1
    assert bundle["entry"][0]["fullUrl"] == f"urn:uuid:{patient.id}"
    assert bundle["entry"][0]["resource"]["resourceType"] == "Patient"
    assert bundle["entry"][0]["resource"]["id"] == str(patient.id)


def test_bundle_with_records_includes_canonical_entries() -> None:
    patient = _dummy_patient()
    rec1 = _dummy_record(patient.id)
    rec2 = _dummy_record(patient.id)

    payload1 = json.dumps({"resourceType": "Condition", "id": "c1"}).encode()
    payload2 = json.dumps({"resourceType": "Immunization", "id": "imm1"}).encode()

    bundle = create_fhir_bundle(patient, [(rec1, payload1), (rec2, payload2)])

    assert len(bundle["entry"]) == 3
    # Entry 0: Patient
    assert bundle["entry"][0]["fullUrl"] == f"urn:uuid:{patient.id}"
    assert bundle["entry"][0]["resource"]["resourceType"] == "Patient"

    # Entry 1: Condition with subject
    assert bundle["entry"][1]["fullUrl"] == f"urn:uuid:{rec1.id}"
    res1 = bundle["entry"][1]["resource"]
    assert res1["resourceType"] == "Condition"
    assert res1["subject"] == canonical_patient_reference(patient)

    # Entry 2: Immunization with patient
    assert bundle["entry"][2]["fullUrl"] == f"urn:uuid:{rec2.id}"
    res2 = bundle["entry"][2]["resource"]
    assert res2["resourceType"] == "Immunization"
    assert res2["patient"] == canonical_patient_reference(patient)
    assert "subject" not in res2


def test_bundle_rejects_record_with_mismatched_patient_id() -> None:
    patient = _dummy_patient()
    other_patient_id = uuid4()
    bad_rec = _dummy_record(other_patient_id)
    payload = json.dumps({"resourceType": "Condition", "id": "c1"}).encode()

    with pytest.raises(ConflictingPatientReferenceError, match="belongs to patient"):
        create_fhir_bundle(patient, [(bad_rec, payload)])


def test_serialize_bundle_to_json_deterministic() -> None:
    patient = _dummy_patient()
    bundle = create_fhir_bundle(
        patient,
        [],
        bundle_id=UUID("00000000-0000-0000-0000-000000000001"),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
    )
    first = serialize_bundle_to_json(bundle)
    second = serialize_bundle_to_json(bundle)
    assert first == second
    assert b'"resourceType":"Bundle"' in first
    assert b'"type":"collection"' in first


# -- DiagnosticReport Contained Observation Tests (FIX 1) ------------------------------


def test_diagnostic_report_result_points_to_contained_observations_with_valid_references() -> None:
    patient = _dummy_patient()
    payload = {
        "resourceType": "DiagnosticReport",
        "id": "dr-panel-1",
        "status": "final",
        "code": {"text": "Basic Metabolic Panel"},
        "result": [
            {
                "resourceType": "Observation",
                "id": "obs-glucose",
                "status": "final",
                "code": {"text": "Glucose", "coding": [{"display": "Glucose [Mass/volume]"}]},
                "valueQuantity": {"value": 95, "unit": "mg/dL"},
            },
            {
                "resourceType": "Observation",
                "id": "obs-potassium",
                "status": "final",
                "code": {"text": "Potassium"},
                "valueQuantity": {"value": 4.2, "unit": "mmol/L"},
            },
        ],
    }

    attached = validate_and_attach_patient(payload, patient)

    assert attached["subject"] == canonical_patient_reference(patient)
    assert "contained" in attached
    assert len(attached["contained"]) == 2

    # Verify contained observation 1
    obs1 = attached["contained"][0]
    assert obs1["resourceType"] == "Observation"
    assert obs1["id"] == "obs-glucose"
    assert obs1["subject"] == canonical_patient_reference(patient)

    # Verify contained observation 2
    obs2 = attached["contained"][1]
    assert obs2["resourceType"] == "Observation"
    assert obs2["id"] == "obs-potassium"
    assert obs2["subject"] == canonical_patient_reference(patient)

    # Verify result references point to the contained IDs using local fragment references
    results = attached["result"]
    assert len(results) == 2
    assert results[0] == {"reference": "#obs-glucose", "display": "Glucose"}
    assert results[1] == {"reference": "#obs-potassium", "display": "Potassium"}


def test_diagnostic_report_preserves_existing_valid_reference_in_result() -> None:
    patient = _dummy_patient()
    payload = {
        "resourceType": "DiagnosticReport",
        "id": "dr-ref-1",
        "contained": [
            {
                "resourceType": "Observation",
                "id": "obs-pre-1",
                "code": {"text": "Pre-existing lab"},
            }
        ],
        "result": [
            {"reference": "#obs-pre-1", "display": "Pre-existing lab"},
            {
                "resourceType": "Observation",
                "id": "obs-local-1",
                "code": {"text": "Local analyte"},
            },
        ],
    }

    attached = validate_and_attach_patient(payload, patient)

    assert len(attached["contained"]) == 2
    assert attached["contained"][0]["id"] == "obs-pre-1"
    assert attached["contained"][1]["id"] == "obs-local-1"

    # Both existing valid fragment reference and new fragment reference are present in result
    assert attached["result"] == [
        {"reference": "#obs-pre-1", "display": "Pre-existing lab"},
        {"reference": "#obs-local-1", "display": "Local analyte"},
    ]


# -- DiagnosticReport Reference Resolution Policy Tests -------------------------------


def test_fragment_reference_target_exists_preserved() -> None:
    patient = _dummy_patient()
    payload = {
        "resourceType": "DiagnosticReport",
        "id": "dr-frag-ok",
        "contained": [
            {
                "resourceType": "Observation",
                "id": "obs-valid-1",
                "status": "final",
                "code": {"text": "Serum Sodium"},
            }
        ],
        "result": [
            {"reference": "#obs-valid-1", "display": "Serum Sodium"},
        ],
    }

    attached = validate_and_attach_patient(payload, patient)

    assert len(attached["contained"]) == 1
    assert attached["contained"][0]["id"] == "obs-valid-1"
    assert attached["result"] == [{"reference": "#obs-valid-1", "display": "Serum Sodium"}]


def test_fragment_reference_target_missing_rejected() -> None:
    patient = _dummy_patient()
    payload = {
        "resourceType": "DiagnosticReport",
        "id": "dr-frag-missing",
        "contained": [
            {
                "resourceType": "Observation",
                "id": "obs-valid-1",
                "code": {"text": "Sodium"},
            }
        ],
        "result": [
            {"reference": "#missing-obs-id", "display": "Missing Obs"},
        ],
    }

    with pytest.raises(MalformedResourcePayloadError, match="dangling fragment reference"):
        validate_and_attach_patient(payload, patient)


def test_relative_observation_reference_absent_from_bundle_rejected() -> None:
    patient = _dummy_patient()
    payload = {
        "resourceType": "DiagnosticReport",
        "id": "dr-rel-missing",
        "result": [
            {"reference": "Observation/external-obs-1", "display": "Lab Outside"},
        ],
    }

    # Case 1: Standalone validation without bundle context
    with pytest.raises(MalformedResourcePayloadError, match="unresolvable reference"):
        validate_and_attach_patient(payload, patient)

    # Case 2: In bundle where target Observation is not among the entries
    rec = _dummy_record(patient.id)
    payload_bytes = json.dumps(payload).encode()
    with pytest.raises(MalformedResourcePayloadError, match="unresolvable reference"):
        create_fhir_bundle(patient, [(rec, payload_bytes)])


def test_reference_resolves_to_actual_bundle_entry() -> None:
    patient = _dummy_patient()
    obs_record = _dummy_record(patient.id)
    obs_payload = json.dumps(
        {
            "resourceType": "Observation",
            "id": "obs-entry-1",
            "status": "final",
            "code": {"text": "Hemoglobin"},
        }
    ).encode()

    dr_record = _dummy_record(patient.id)
    # The DiagnosticReport references the Observation record by relative reference
    dr_payload = json.dumps(
        {
            "resourceType": "DiagnosticReport",
            "id": "dr-1",
            "result": [
                {"reference": "Observation/obs-entry-1", "display": "Hemoglobin"},
            ],
        }
    ).encode()

    bundle = create_fhir_bundle(patient, [(obs_record, obs_payload), (dr_record, dr_payload)])

    # Entry 0 is Patient, Entry 1 is Observation, Entry 2 is DiagnosticReport
    assert len(bundle["entry"]) == 3
    obs_entry = bundle["entry"][1]
    dr_entry = bundle["entry"][2]

    assert obs_entry["fullUrl"] == f"urn:uuid:{obs_record.id}"
    assert obs_entry["resource"]["resourceType"] == "Observation"

    # DiagnosticReport reference resolves to the Observation entry's fullUrl
    assert dr_entry["resource"]["result"] == [
        {"reference": f"urn:uuid:{obs_record.id}", "display": "Hemoglobin"}
    ]

    # Also verify direct fullUrl reference in payload resolves
    dr_record2 = _dummy_record(patient.id)
    dr_payload2 = json.dumps(
        {
            "resourceType": "DiagnosticReport",
            "id": "dr-2",
            "result": [
                {"reference": f"urn:uuid:{obs_record.id}", "display": "Hemoglobin Direct"},
            ],
        }
    ).encode()

    bundle2 = create_fhir_bundle(patient, [(obs_record, obs_payload), (dr_record2, dr_payload2)])
    assert bundle2["entry"][2]["resource"]["result"] == [
        {"reference": f"urn:uuid:{obs_record.id}", "display": "Hemoglobin Direct"}
    ]


def test_preservation_of_valid_contained_observations_and_existing_valid_references() -> None:
    patient = _dummy_patient()
    payload = {
        "resourceType": "DiagnosticReport",
        "id": "dr-mix-1",
        "contained": [
            {
                "resourceType": "Observation",
                "id": "obs-pre-1",
                "status": "final",
                "code": {"text": "Pre-existing analyte"},
            }
        ],
        "result": [
            {"reference": "#obs-pre-1", "display": "Pre-existing analyte"},
            {
                "resourceType": "Observation",
                "id": "obs-embedded-2",
                "status": "final",
                "code": {"text": "Embedded analyte"},
            },
        ],
    }

    attached = validate_and_attach_patient(payload, patient)

    # Both observations are preserved in contained, with patient reference attached
    assert len(attached["contained"]) == 2
    assert attached["contained"][0]["id"] == "obs-pre-1"
    assert attached["contained"][0]["subject"] == canonical_patient_reference(patient)
    assert attached["contained"][1]["id"] == "obs-embedded-2"
    assert attached["contained"][1]["subject"] == canonical_patient_reference(patient)

    # Result array references both without clinical data loss
    assert attached["result"] == [
        {"reference": "#obs-pre-1", "display": "Pre-existing analyte"},
        {"reference": "#obs-embedded-2", "display": "Embedded analyte"},
    ]


def test_no_dangling_references_in_resulting_diagnostic_report_or_bundle() -> None:
    patient = _dummy_patient()
    obs_rec = _dummy_record(patient.id)
    obs_payload = json.dumps(
        {
            "resourceType": "Observation",
            "id": "obs-bundle-ext",
            "status": "final",
            "code": {"text": "Ext Lab"},
        }
    ).encode()

    dr_rec = _dummy_record(patient.id)
    dr_payload = json.dumps(
        {
            "resourceType": "DiagnosticReport",
            "id": "dr-clean-1",
            "contained": [
                {
                    "resourceType": "Observation",
                    "id": "obs-internal-1",
                    "status": "final",
                    "code": {"text": "Internal Lab"},
                }
            ],
            "result": [
                {"reference": "#obs-internal-1", "display": "Internal Lab"},
                {"reference": "Observation/obs-bundle-ext", "display": "Ext Lab"},
                {
                    "resourceType": "Observation",
                    "id": "obs-embedded-1",
                    "code": {"text": "Embedded Lab"},
                },
            ],
        }
    ).encode()

    cond_rec = _dummy_record(patient.id)
    cond_payload = json.dumps({"resourceType": "Condition", "id": "c1"}).encode()

    bundle = create_fhir_bundle(
        patient,
        [(obs_rec, obs_payload), (dr_rec, dr_payload), (cond_rec, cond_payload)],
    )

    # Collect all valid fullUrls in the bundle
    bundle_full_urls = {entry["fullUrl"] for entry in bundle["entry"]}
    assert f"urn:uuid:{patient.id}" in bundle_full_urls
    assert f"urn:uuid:{obs_rec.id}" in bundle_full_urls
    assert f"urn:uuid:{dr_rec.id}" in bundle_full_urls
    assert f"urn:uuid:{cond_rec.id}" in bundle_full_urls

    # Check each resource entry for reference integrity
    for entry in bundle["entry"]:
        res = entry["resource"]
        rtype = res["resourceType"]

        # 1. Patient reference must resolve to the Patient entry fullUrl
        if rtype != "Patient":
            p_field = RESOURCE_PATIENT_REFERENCE_FIELDS[rtype]
            p_ref = res[p_field]["reference"]
            assert p_ref in bundle_full_urls
            assert p_ref == f"urn:uuid:{patient.id}"

        # 2. Contained resources must have valid IDs
        contained_ids = {c["id"] for c in res.get("contained", []) if "id" in c}

        # 3. For DiagnosticReport, all result references must resolve
        if rtype == "DiagnosticReport":
            for ref_entry in res.get("result", []):
                ref_str = ref_entry["reference"]
                if ref_str.startswith("#"):
                    # Fragment reference must resolve to contained resource
                    target_frag = ref_str[1:]
                    assert target_frag in contained_ids, f"Dangling fragment: {ref_str}"
                else:
                    # Non-fragment reference must resolve to a Bundle entry fullUrl
                    assert ref_str in bundle_full_urls, f"Dangling bundle reference: {ref_str}"


def test_diagnostic_report_malformed_result_item_rejected() -> None:
    patient = _dummy_patient()

    # 1. Non-Observation resource type in result
    payload1 = {
        "resourceType": "DiagnosticReport",
        "id": "dr-bad-1",
        "result": [{"resourceType": "Condition", "id": "cond-1"}],
    }
    with pytest.raises(MalformedResourcePayloadError, match="invalid result entry"):
        validate_and_attach_patient(payload1, patient)

    # 2. Primitive / non-dict item in result
    payload2 = {
        "resourceType": "DiagnosticReport",
        "id": "dr-bad-2",
        "result": ["Observation/123"],
    }
    with pytest.raises(MalformedResourcePayloadError, match="invalid result entry"):
        validate_and_attach_patient(payload2, patient)

    # 3. Empty dictionary in result
    payload3 = {
        "resourceType": "DiagnosticReport",
        "id": "dr-bad-3",
        "result": [{}],
    }
    with pytest.raises(MalformedResourcePayloadError, match="invalid result entry"):
        validate_and_attach_patient(payload3, patient)


def test_diagnostic_report_generates_unique_local_ids_when_missing_or_duplicate() -> None:
    patient = _dummy_patient()
    payload = {
        "resourceType": "DiagnosticReport",
        "id": "dr-dup-1",
        "result": [
            {"resourceType": "Observation", "id": "same-id", "code": {"text": "A"}},
            {"resourceType": "Observation", "id": "same-id", "code": {"text": "B"}},
            {"resourceType": "Observation", "code": {"text": "C"}},
        ],
    }

    attached = validate_and_attach_patient(payload, patient)

    contained_ids = [c["id"] for c in attached["contained"]]
    # All 3 IDs must be unique
    assert len(contained_ids) == len(set(contained_ids)) == 3
    # Result references must match the assigned IDs exactly
    result_refs = [r["reference"] for r in attached["result"]]
    assert result_refs == [f"#{cid}" for cid in contained_ids]


def test_diagnostic_report_existing_contained_resources_preserved() -> None:
    patient = _dummy_patient()
    payload = {
        "resourceType": "DiagnosticReport",
        "id": "dr-cont-1",
        "contained": [
            {"resourceType": "Practitioner", "id": "pr-1", "name": [{"text": "Dr Smith"}]}
        ],
        "result": [{"resourceType": "Observation", "id": "obs-1", "code": {"text": "Calcium"}}],
    }

    attached = validate_and_attach_patient(payload, patient)

    assert len(attached["contained"]) == 2
    assert attached["contained"][0]["resourceType"] == "Practitioner"
    assert attached["contained"][0]["id"] == "pr-1"
    assert attached["contained"][1]["resourceType"] == "Observation"
    assert attached["contained"][1]["id"] == "obs-1"
    assert attached["result"] == [{"reference": "#obs-1", "display": "Calcium"}]


# -- Consistent Bundle Reference Resolution (FIX 2) ------------------------------------


def test_bundle_patient_reference_resolves_to_patient_entry_fullurl_for_all_six_types() -> None:
    patient = _dummy_patient()
    records = [
        (_dummy_record(patient.id), json.dumps({"resourceType": "Condition", "id": "c1"}).encode()),
        (_dummy_record(patient.id), json.dumps({"resourceType": "Procedure", "id": "p1"}).encode()),
        (
            _dummy_record(patient.id),
            json.dumps({"resourceType": "MedicationRequest", "id": "m1"}).encode(),
        ),
        (
            _dummy_record(patient.id),
            json.dumps({"resourceType": "DiagnosticReport", "id": "d1"}).encode(),
        ),
        (
            _dummy_record(patient.id),
            json.dumps({"resourceType": "Immunization", "id": "i1"}).encode(),
        ),
        (
            _dummy_record(patient.id),
            json.dumps({"resourceType": "AllergyIntolerance", "id": "a1"}).encode(),
        ),
    ]

    bundle = create_fhir_bundle(patient, records)

    patient_entry = bundle["entry"][0]
    assert patient_entry["resource"]["resourceType"] == "Patient"
    patient_full_url = patient_entry["fullUrl"]
    assert patient_full_url == f"urn:uuid:{patient.id}"

    # For every clinical resource, the reference must resolve to the Patient fullUrl
    for entry in bundle["entry"][1:]:
        res = entry["resource"]
        rtype = res["resourceType"]
        target_field = RESOURCE_PATIENT_REFERENCE_FIELDS[rtype]
        ref_obj = res[target_field]
        assert ref_obj["reference"] == patient_full_url
        assert ref_obj["display"] == patient.full_name


# -- Reference Identifier Validation (FIX 3) -------------------------------------------


def test_reference_with_matching_identifier_system_and_value_accepted() -> None:
    patient = _dummy_patient()
    payload = {
        "resourceType": "Condition",
        "id": "c1",
        "subject": {
            "reference": f"urn:uuid:{patient.id}",
            "identifier": {
                "system": PULSEOS_HEALTH_ID_SYSTEM,
                "value": patient.health_id,
            },
        },
    }

    attached = validate_and_attach_patient(payload, patient)
    assert attached["subject"] == canonical_patient_reference(patient)


def test_reference_with_conflicting_identifier_value_rejected() -> None:
    patient = _dummy_patient()
    payload = {
        "resourceType": "Condition",
        "id": "c1",
        "subject": {
            "reference": f"urn:uuid:{patient.id}",
            "identifier": {
                "system": PULSEOS_HEALTH_ID_SYSTEM,
                "value": "PHI-IND-2026-CONFLICTING99",
            },
        },
    }

    with pytest.raises(
        ConflictingPatientReferenceError, match="conflicting patient identifier value"
    ):
        validate_and_attach_patient(payload, patient)


def test_reference_with_conflicting_identifier_system_rejected() -> None:
    patient = _dummy_patient()
    payload = {
        "resourceType": "Condition",
        "id": "c1",
        "subject": {
            "reference": f"urn:uuid:{patient.id}",
            "identifier": {
                "system": "https://external.hospital.org/identifiers/patient",
                "value": patient.health_id,
            },
        },
    }

    with pytest.raises(
        ConflictingPatientReferenceError, match="unknown or conflicting identifier system"
    ):
        validate_and_attach_patient(payload, patient)


def test_identifier_only_reference_accepted_and_validated() -> None:
    patient = _dummy_patient()
    payload = {
        "resourceType": "Condition",
        "id": "c1",
        "subject": {
            "identifier": {
                "system": PULSEOS_HEALTH_ID_SYSTEM,
                "value": patient.health_id,
            },
        },
    }

    attached = validate_and_attach_patient(payload, patient)
    assert attached["subject"] == canonical_patient_reference(patient)


def test_identifier_only_conflicting_value_rejected() -> None:
    patient = _dummy_patient()
    payload = {
        "resourceType": "Condition",
        "id": "c1",
        "subject": {
            "identifier": {
                "system": PULSEOS_HEALTH_ID_SYSTEM,
                "value": "PHI-IND-2026-WRONG",
            },
        },
    }

    with pytest.raises(
        ConflictingPatientReferenceError, match="conflicting patient identifier value"
    ):
        validate_and_attach_patient(payload, patient)


def test_reference_only_matching_accepted() -> None:
    patient = _dummy_patient()
    payload = {
        "resourceType": "Condition",
        "id": "c1",
        "subject": {
            "reference": f"urn:uuid:{patient.id}",
        },
    }

    attached = validate_and_attach_patient(payload, patient)
    assert attached["subject"] == canonical_patient_reference(patient)


def test_both_reference_and_identifier_inconsistent_rejected() -> None:
    patient = _dummy_patient()
    conflicting_uuid = str(uuid4())

    # Case A: matching reference, but conflicting identifier value
    payload_a = {
        "resourceType": "Condition",
        "id": "c1",
        "subject": {
            "reference": f"urn:uuid:{patient.id}",
            "identifier": {
                "system": PULSEOS_HEALTH_ID_SYSTEM,
                "value": "PHI-IND-2026-WRONG",
            },
        },
    }
    with pytest.raises(
        ConflictingPatientReferenceError, match="conflicting patient identifier value"
    ):
        validate_and_attach_patient(payload_a, patient)

    # Case B: matching identifier, but conflicting reference
    payload_b = {
        "resourceType": "Condition",
        "id": "c2",
        "subject": {
            "reference": f"urn:uuid:{conflicting_uuid}",
            "identifier": {
                "system": PULSEOS_HEALTH_ID_SYSTEM,
                "value": patient.health_id,
            },
        },
    }
    with pytest.raises(ConflictingPatientReferenceError, match="conflicting patient"):
        validate_and_attach_patient(payload_b, patient)


def test_missing_or_empty_identifier_field_accepted() -> None:
    patient = _dummy_patient()

    # Empty dict identifier
    payload1 = {
        "resourceType": "Condition",
        "id": "c1",
        "subject": {
            "reference": f"urn:uuid:{patient.id}",
            "identifier": {},
        },
    }
    attached1 = validate_and_attach_patient(payload1, patient)
    assert attached1["subject"] == canonical_patient_reference(patient)

    # Missing identifier
    payload2 = {
        "resourceType": "Condition",
        "id": "c2",
        "subject": {
            "reference": f"urn:uuid:{patient.id}",
        },
    }
    attached2 = validate_and_attach_patient(payload2, patient)
    assert attached2["subject"] == canonical_patient_reference(patient)


def test_ambiguous_identifier_system_without_value_rejected() -> None:
    patient = _dummy_patient()
    payload = {
        "resourceType": "Condition",
        "id": "c1",
        "subject": {
            "identifier": {
                "system": PULSEOS_HEALTH_ID_SYSTEM,
            },
        },
    }

    with pytest.raises(ConflictingPatientReferenceError, match="ambiguous patient identifier"):
        validate_and_attach_patient(payload, patient)
