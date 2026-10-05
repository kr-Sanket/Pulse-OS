"""Deterministic text normalization and sanitization for AI/RAG ingestion.

This module converts sanitized FHIR resource JSON into stable, readable text
that can later be chunked and embedded, and sanitizes clinical queries before
prompt construction for external LLM providers.

It deliberately has no database, storage, FastAPI, or model dependencies.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Final

HEALTH_ID_PLACEHOLDER: Final[str] = "[HEALTH_ID]"
PHONE_PLACEHOLDER: Final[str] = "[PHONE]"

_HEALTH_ID_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\bPHI-IND-\d{4}-[A-Za-z0-9*]+\b",
    re.IGNORECASE,
)

_PHONE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?<!\w)(?:\+91[\s\-]|\+91|91[\s\-]|91)(?:\d{10}|\d{5}[\s\-]\d{5})(?!\d)|(?<!\w)[6-9]\d{9}(?!\d)"
)


def sanitize_clinical_query(query: str) -> str:
    """Sanitize clinician query by replacing direct identifiers with neutral tokens.

    Direct identifiers like PulseOS Health IDs (e.g. PHI-IND-2026-XXXXXXC)
    and Indian phone numbers are replaced with [HEALTH_ID] and [PHONE]
    respectively before prompt formatting for LLM generation.
    """
    if not query:
        return query

    sanitized = _HEALTH_ID_PATTERN.sub(HEALTH_ID_PLACEHOLDER, query)
    sanitized = _PHONE_PATTERN.sub(PHONE_PLACEHOLDER, sanitized)
    return sanitized



def normalize_fhir_resource(resource: Mapping[str, Any]) -> str:
    """Convert a sanitized FHIR resource into deterministic readable text.

    The output is intentionally conservative. It preserves the resource type,
    resource id, common clinical fields, and structured JSON content without
    attempting clinical interpretation.
    """
    lines: list[str] = []

    resource_type = resource.get("resourceType")
    resource_id = resource.get("id")

    if resource_type:
        lines.append(f"Resource Type: {resource_type}")

    if resource_id:
        lines.append(f"Resource ID: {resource_id}")

    _append_scalar(lines, "Status", resource.get("status"))
    _append_scalar(lines, "Intent", resource.get("intent"))
    _append_scalar(lines, "Date", resource.get("date"))
    _append_scalar(lines, "Recorded Date", resource.get("recordedDate"))
    _append_scalar(lines, "Occurrence Date", resource.get("occurrenceDateTime"))

    _append_codeable_concept(lines, "Code", resource.get("code"))
    _append_codeable_concept(lines, "Category", resource.get("category"))

    if resource_type == "DiagnosticReport":
        _append_codeable_concept(lines, "Conclusion Code", resource.get("conclusionCode"))
        _append_scalar(lines, "Conclusion", resource.get("conclusion"))

        results = resource.get("result")
        if isinstance(results, list):
            for index, result in enumerate(results, start=1):
                if isinstance(result, Mapping):
                    lines.append(
                        f"Result Reference {index}: "
                        f"{result.get('reference', result.get('display', ''))}"
                    )

    if resource_type == "Condition":
        _append_codeable_concept(lines, "Clinical Status", resource.get("clinicalStatus"))
        _append_codeable_concept(lines, "Verification Status", resource.get("verificationStatus"))

    if resource_type == "MedicationRequest":
        _append_codeable_concept(lines, "Medication", resource.get("medicationCodeableConcept"))
        _append_codeable_concept(lines, "Reason", resource.get("reasonCode"))

    if resource_type == "Immunization":
        _append_codeable_concept(lines, "Vaccine", resource.get("vaccineCode"))
        _append_scalar(lines, "Occurrence", resource.get("occurrenceDateTime"))

    if resource_type == "AllergyIntolerance":
        _append_codeable_concept(lines, "Allergy", resource.get("code"))
        _append_codeable_concept(lines, "Clinical Status", resource.get("clinicalStatus"))
        _append_codeable_concept(lines, "Verification Status", resource.get("verificationStatus"))

    return "\n".join(line for line in lines if line.strip())


def _append_scalar(
    lines: list[str],
    label: str,
    value: Any,
) -> None:
    """Append a scalar value when it is present."""
    if value is None:
        return

    if isinstance(value, (str, int, float, bool)):
        lines.append(f"{label}: {value}")


def _append_codeable_concept(
    lines: list[str],
    label: str,
    value: Any,
) -> None:
    """Append useful text from a FHIR CodeableConcept-like object."""
    if not isinstance(value, Mapping):
        return

    text = value.get("text")
    if isinstance(text, str) and text.strip():
        lines.append(f"{label}: {text.strip()}")

    coding = value.get("coding")
    if not isinstance(coding, list):
        return

    for item in coding:
        if not isinstance(item, Mapping):
            continue

        system = item.get("system")
        code = item.get("code")
        display = item.get("display")

        parts: list[str] = []

        if isinstance(system, str) and system:
            parts.append(system)

        if isinstance(code, str) and code:
            parts.append(code)

        if isinstance(display, str) and display:
            parts.append(display)

        if parts:
            lines.append(f"{label} Coding: {' | '.join(parts)}")