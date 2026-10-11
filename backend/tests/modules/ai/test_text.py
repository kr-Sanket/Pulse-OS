"""Tests for AI text normalization and pre-LLM query sanitization."""

from app.modules.ai.text import (
    HEALTH_ID_PLACEHOLDER,
    PHONE_PLACEHOLDER,
    normalize_fhir_resource,
    sanitize_clinical_query,
)


def test_sanitize_health_id_direct() -> None:
    query = "Show records for PHI-IND-2026-ABC123XYZ"
    sanitized = sanitize_clinical_query(query)

    assert HEALTH_ID_PLACEHOLDER in sanitized
    assert "PHI-IND-2026-ABC123XYZ" not in sanitized
    assert sanitized == f"Show records for {HEALTH_ID_PLACEHOLDER}"


def test_sanitize_health_id_valid_pulseos_format() -> None:
    query = "Patient PHI-IND-2026-7K3M99X diagnostic history"
    sanitized = sanitize_clinical_query(query)

    assert sanitized == f"Patient {HEALTH_ID_PLACEHOLDER} diagnostic history"
    assert "PHI-IND-2026-7K3M99X" not in sanitized


def test_sanitize_health_id_case_insensitive() -> None:
    query = "Status of phi-ind-2025-0123456"
    sanitized = sanitize_clinical_query(query)

    assert sanitized == f"Status of {HEALTH_ID_PLACEHOLDER}"
    assert "phi-ind-2025-0123456" not in sanitized


def test_sanitize_indian_phone_formats() -> None:
    cases = [
        ("+919876543210", PHONE_PLACEHOLDER),
        ("919876543210", PHONE_PLACEHOLDER),
        ("9876543210", PHONE_PLACEHOLDER),
        ("+91 9876543210", PHONE_PLACEHOLDER),
        ("+91-9876543210", PHONE_PLACEHOLDER),
        ("+91 98765 43210", PHONE_PLACEHOLDER),
        ("91 9876543210", PHONE_PLACEHOLDER),
        (
            "Contact Dr. Asha at +919876543210 regarding labs",
            f"Contact Dr. Asha at {PHONE_PLACEHOLDER} regarding labs",
        ),
        ("Call 9876543210 immediately", f"Call {PHONE_PLACEHOLDER} immediately"),
    ]

    for raw, expected in cases:
        assert sanitize_clinical_query(raw) == expected


def test_sanitize_multiple_identifiers() -> None:
    query = "Check records for PHI-IND-2026-ABC123XYZ or call +919876543210 or 9876543210"
    sanitized = sanitize_clinical_query(query)

    assert HEALTH_ID_PLACEHOLDER in sanitized
    assert "PHI-IND-2026-ABC123XYZ" not in sanitized
    assert "+919876543210" not in sanitized
    assert "9876543210" not in sanitized
    assert sanitized == (
        f"Check records for {HEALTH_ID_PLACEHOLDER} or call "
        f"{PHONE_PLACEHOLDER} or {PHONE_PLACEHOLDER}"
    )


def test_clinical_content_preserved() -> None:
    queries = [
        "What medications were prescribed for hypertension?",
        "Fasting blood glucose 110 mg/dL and BP 120/80 mmHg",
        "WBC count 4500/uL, creatinine 0.9 mg/dL",
        "Prescription filled in 2026 with Metformin 500mg daily",
    ]

    for q in queries:
        assert sanitize_clinical_query(q) == q


def test_empty_query() -> None:
    assert sanitize_clinical_query("") == ""


def test_normalize_fhir_condition() -> None:
    resource = {
        "resourceType": "Condition",
        "id": "cond-1",
        "clinicalStatus": {"text": "Active"},
        "verificationStatus": {"text": "Confirmed"},
        "code": {
            "text": "Essential hypertension",
            "coding": [
                {
                    "system": "http://snomed.info/sct",
                    "code": "59621000",
                    "display": "Hypertension",
                }
            ],
        },
    }
    normalized = normalize_fhir_resource(resource)

    assert "Resource Type: Condition" in normalized
    assert "Resource ID: cond-1" in normalized
    assert "Clinical Status: Active" in normalized
    assert "Code: Essential hypertension" in normalized
    assert "http://snomed.info/sct | 59621000 | Hypertension" in normalized


def test_normalize_fhir_medication_request() -> None:
    resource = {
        "resourceType": "MedicationRequest",
        "id": "med-1",
        "status": "active",
        "intent": "order",
        "medicationCodeableConcept": {"text": "Amlodipine 5mg"},
        "reasonCode": {"text": "High blood pressure"},
    }
    normalized = normalize_fhir_resource(resource)

    assert "Resource Type: MedicationRequest" in normalized
    assert "Status: active" in normalized
    assert "Intent: order" in normalized
    assert "Medication: Amlodipine 5mg" in normalized
    assert "Reason: High blood pressure" in normalized


def test_normalize_fhir_diagnostic_report_with_embedded_observations() -> None:
    resource = {
        "resourceType": "DiagnosticReport",
        "id": "report-001",
        "status": "final",
        "effectiveDateTime": "2026-03-15T09:30:00Z",
        "issued": "2026-03-15T10:00:00Z",
        "code": {
            "text": "Basic Metabolic Panel",
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": "24323-8",
                    "display": "Basic Metabolic Panel",
                }
            ],
        },
        "result": [
            {
                "resourceType": "Observation",
                "id": "obs-glucose",
                "code": {
                    "coding": [
                        {
                            "system": "http://loinc.org",
                            "code": "2339-0",
                            "display": "Glucose",
                        }
                    ],
                    "text": "Glucose",
                },
                "valueQuantity": {
                    "value": 69.53018,
                    "unit": "mg/dL",
                },
            },
            {
                "resourceType": "Observation",
                "id": "obs-creatinine",
                "code": {
                    "coding": [
                        {
                            "system": "http://loinc.org",
                            "code": "2160-0",
                            "display": "Creatinine",
                        }
                    ],
                    "text": "Creatinine",
                },
                "valueQuantity": {
                    "value": 1.0,
                    "unit": "mg/dL",
                },
            },
            {
                "resourceType": "Observation",
                "id": "obs-qualitative",
                "code": {"text": "Urine Appearance"},
                "valueString": "Clear",
            },
        ],
    }

    normalized = normalize_fhir_resource(resource)

    assert "Resource Type: DiagnosticReport" in normalized
    assert "Resource ID: report-001" in normalized
    assert "Status: final" in normalized
    assert "Effective Date: 2026-03-15T09:30:00Z" in normalized
    assert "Issued Date: 2026-03-15T10:00:00Z" in normalized
    assert "Code: Basic Metabolic Panel" in normalized
    assert "Result: Glucose 69.5 mg/dL" in normalized
    assert "Result: Creatinine 1 mg/dL" in normalized
    assert "Result: Urine Appearance Clear" in normalized


def test_normalize_fhir_diagnostic_report_unresolved_reference_fallback() -> None:
    resource = {
        "resourceType": "DiagnosticReport",
        "id": "report-002",
        "status": "final",
        "code": {"text": "Lipid Panel"},
        "result": [
            {"reference": "urn:uuid:885af0bd-e538-4355-9a11-de43ab422e0a"},
            {"reference": "Observation/123", "display": "Cholesterol"},
        ],
    }

    normalized = normalize_fhir_resource(resource)

    assert "Resource Type: DiagnosticReport" in normalized
    assert "Result Reference 1: urn:uuid:885af0bd-e538-4355-9a11-de43ab422e0a" in normalized
    assert "Result Reference 2: Observation/123" in normalized


def test_normalize_fhir_diagnostic_report_deterministic_ordering() -> None:
    resource = {
        "resourceType": "DiagnosticReport",
        "id": "report-order",
        "result": [
            {"code": {"text": "Analyte A"}, "valueQuantity": {"value": 10, "unit": "u/L"}},
            {"code": {"text": "Analyte B"}, "valueQuantity": {"value": 20, "unit": "u/L"}},
            {"code": {"text": "Analyte C"}, "valueQuantity": {"value": 30, "unit": "u/L"}},
        ],
    }

    norm1 = normalize_fhir_resource(resource)
    norm2 = normalize_fhir_resource(resource)

    assert norm1 == norm2
    lines = norm1.split("\n")
    a_idx = lines.index("Result: Analyte A 10 u/L")
    b_idx = lines.index("Result: Analyte B 20 u/L")
    c_idx = lines.index("Result: Analyte C 30 u/L")
    assert a_idx < b_idx < c_idx


def test_normalize_fhir_standalone_observation() -> None:
    resource = {
        "resourceType": "Observation",
        "id": "obs-standalone",
        "status": "final",
        "effectiveDateTime": "2026-02-10T08:00:00Z",
        "code": {
            "text": "Body Weight",
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": "29463-7",
                    "display": "Body Weight",
                }
            ],
        },
        "valueQuantity": {"value": 72.5, "unit": "kg"},
    }

    normalized = normalize_fhir_resource(resource)

    assert "Resource Type: Observation" in normalized
    assert "Effective Date: 2026-02-10T08:00:00Z" in normalized
    assert "Code: Body Weight" in normalized
    assert "Result: Body Weight 72.5 kg" in normalized
