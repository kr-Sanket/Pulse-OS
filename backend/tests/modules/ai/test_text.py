"""Tests for AI text normalization and pre-LLM query sanitization."""

from app.modules.ai.text import (
    HEALTH_ID_PLACEHOLDER,
    PHONE_PLACEHOLDER,
    normalize_fhir_resource,
    sanitize_clinical_query,
)


def test_sanitize_health_id_direct():
    query = "Show records for PHI-IND-2026-ABC123XYZ"
    sanitized = sanitize_clinical_query(query)

    assert HEALTH_ID_PLACEHOLDER in sanitized
    assert "PHI-IND-2026-ABC123XYZ" not in sanitized
    assert sanitized == f"Show records for {HEALTH_ID_PLACEHOLDER}"


def test_sanitize_health_id_valid_pulseos_format():
    query = "Patient PHI-IND-2026-7K3M99X diagnostic history"
    sanitized = sanitize_clinical_query(query)

    assert sanitized == f"Patient {HEALTH_ID_PLACEHOLDER} diagnostic history"
    assert "PHI-IND-2026-7K3M99X" not in sanitized


def test_sanitize_health_id_case_insensitive():
    query = "Status of phi-ind-2025-0123456"
    sanitized = sanitize_clinical_query(query)

    assert sanitized == f"Status of {HEALTH_ID_PLACEHOLDER}"
    assert "phi-ind-2025-0123456" not in sanitized


def test_sanitize_indian_phone_formats():
    cases = [
        ("+919876543210", PHONE_PLACEHOLDER),
        ("919876543210", PHONE_PLACEHOLDER),
        ("9876543210", PHONE_PLACEHOLDER),
        ("+91 9876543210", PHONE_PLACEHOLDER),
        ("+91-9876543210", PHONE_PLACEHOLDER),
        ("+91 98765 43210", PHONE_PLACEHOLDER),
        ("91 9876543210", PHONE_PLACEHOLDER),
        ("Contact Dr. Asha at +919876543210 regarding labs", f"Contact Dr. Asha at {PHONE_PLACEHOLDER} regarding labs"),
        ("Call 9876543210 immediately", f"Call {PHONE_PLACEHOLDER} immediately"),
    ]

    for raw, expected in cases:
        assert sanitize_clinical_query(raw) == expected


def test_sanitize_multiple_identifiers():
    query = "Check records for PHI-IND-2026-ABC123XYZ or call +919876543210 or 9876543210"
    sanitized = sanitize_clinical_query(query)

    assert HEALTH_ID_PLACEHOLDER in sanitized
    assert "PHI-IND-2026-ABC123XYZ" not in sanitized
    assert "+919876543210" not in sanitized
    assert "9876543210" not in sanitized
    assert sanitized == (
        f"Check records for {HEALTH_ID_PLACEHOLDER} or call {PHONE_PLACEHOLDER} or {PHONE_PLACEHOLDER}"
    )


def test_clinical_content_preserved():
    queries = [
        "What medications were prescribed for hypertension?",
        "Fasting blood glucose 110 mg/dL and BP 120/80 mmHg",
        "WBC count 4500/uL, creatinine 0.9 mg/dL",
        "Prescription filled in 2026 with Metformin 500mg daily",
    ]

    for q in queries:
        assert sanitize_clinical_query(q) == q


def test_empty_query():
    assert sanitize_clinical_query("") == ""


def test_normalize_fhir_condition():
    resource = {
        "resourceType": "Condition",
        "id": "cond-1",
        "clinicalStatus": {"text": "Active"},
        "verificationStatus": {"text": "Confirmed"},
        "code": {
            "text": "Essential hypertension",
            "coding": [{"system": "http://snomed.info/sct", "code": "59621000", "display": "Hypertension"}],
        },
    }
    normalized = normalize_fhir_resource(resource)

    assert "Resource Type: Condition" in normalized
    assert "Resource ID: cond-1" in normalized
    assert "Clinical Status: Active" in normalized
    assert "Code: Essential hypertension" in normalized
    assert "http://snomed.info/sct | 59621000 | Hypertension" in normalized


def test_normalize_fhir_medication_request():
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
