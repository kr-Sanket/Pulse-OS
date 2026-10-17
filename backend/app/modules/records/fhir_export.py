"""FHIR R4 export serializer and subject validator. Pure functions: no DB, no I/O.

Constructs a canonical FHIR R4 Bundle (type: collection) from validated PulseOS records
and patient demographics. Enforces resource-specific patient references, rejects
conflicting patient references or malformed payloads, and guarantees that every exported
resource is strictly bound to the target patient.
"""

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID, uuid4

from app.modules.patients.models import Patient
from app.modules.records.errors import (
    ConflictingPatientReferenceError,
    FHIRSerializationError,
    MalformedResourcePayloadError,
)
from app.modules.records.models import MedicalRecord

#: The FHIR R4 clinical resource types mapped or exported by PulseOS.
SUPPORTED_EXPORT_RESOURCE_TYPES: Final[frozenset[str]] = frozenset(
    {
        "Condition",
        "Procedure",
        "MedicationRequest",
        "DiagnosticReport",
        "Immunization",
        "AllergyIntolerance",
        "Observation",
    }
)

#: Resource-specific patient reference fields according to FHIR R4:
#: - Immunization and AllergyIntolerance use ``patient``
#: - Condition, Procedure, MedicationRequest, DiagnosticReport, and Observation use ``subject``
RESOURCE_PATIENT_REFERENCE_FIELDS: Final[Mapping[str, str]] = {
    "Condition": "subject",
    "Procedure": "subject",
    "MedicationRequest": "subject",
    "DiagnosticReport": "subject",
    "Immunization": "patient",
    "AllergyIntolerance": "patient",
    "Observation": "subject",
}

#: System URI for PulseOS Health IDs in exported FHIR Patient identifiers.
PULSEOS_HEALTH_ID_SYSTEM: Final[str] = "https://pulseos.local/fhir/identifier/health-id"


def build_patient_resource(patient: Patient) -> dict[str, Any]:
    """Construct a canonical FHIR R4 Patient resource from a PulseOS Patient model."""
    names = patient.full_name.strip().split()
    name_entry: dict[str, Any] = {"use": "official", "text": patient.full_name}
    if len(names) > 1:
        name_entry["given"] = names[:-1]
        name_entry["family"] = names[-1]
    elif names:
        name_entry["text"] = names[0]

    resource: dict[str, Any] = {
        "resourceType": "Patient",
        "id": str(patient.id),
        "identifier": [
            {
                "system": PULSEOS_HEALTH_ID_SYSTEM,
                "value": patient.health_id,
            }
        ],
        "name": [name_entry],
    }
    if patient.date_of_birth:
        resource["birthDate"] = patient.date_of_birth.isoformat()
    if patient.gender:
        resource["gender"] = patient.gender.value.lower()
    return resource


def canonical_patient_reference(patient: Patient) -> dict[str, str]:
    """Return the canonical Reference structure for the target patient."""
    return {
        "reference": f"urn:uuid:{patient.id}",
        "display": patient.full_name,
    }


def _extract_reference_id(ref: Any) -> str | None:
    """Extract the target ID from a reference string (e.g. Patient/{id} or urn:uuid:{id})."""
    if not isinstance(ref, str):
        return None
    val = ref.strip()
    if val.startswith("urn:uuid:"):
        return val[len("urn:uuid:") :]
    if "/" in val:
        return val.rsplit("/", 1)[-1]
    return val


def _check_conflicting_reference(
    ref_dict: Any,
    patient: Patient,
    resource_id: str | None,
    field_name: str,
) -> None:
    """Verify that any existing reference object does not point to a different patient."""
    if ref_dict is None:
        return
    if not isinstance(ref_dict, dict):
        raise MalformedResourcePayloadError(
            f"Resource {resource_id or '<unknown>'} has non-dictionary {field_name} reference"
        )

    expected_patient_id = str(patient.id)

    # 1. Validate Reference.reference when present
    ref_str = ref_dict.get("reference")
    if isinstance(ref_str, str) and ref_str.strip():
        extracted = _extract_reference_id(ref_str)
        if extracted and extracted != expected_patient_id and extracted != patient.health_id:
            raise ConflictingPatientReferenceError(
                f"Resource {resource_id or '<unknown>'} has {field_name} referencing "
                f"conflicting patient '{ref_str}' (expected patient {expected_patient_id})"
            )

    # 2. Validate Reference.identifier when present
    ident = ref_dict.get("identifier")
    if ident is not None:
        if not isinstance(ident, dict):
            raise ConflictingPatientReferenceError(
                f"Resource {resource_id or '<unknown>'} has malformed identifier in {field_name}"
            )
        # Empty identifier dictionary is allowed (optional field absent/empty)
        if ident:
            system = ident.get("system")
            value = ident.get("value")

            # Validate system if present
            if system is not None and (
                not isinstance(system, str) or system != PULSEOS_HEALTH_ID_SYSTEM
            ):
                raise ConflictingPatientReferenceError(
                    f"Resource {resource_id or '<unknown>'} has {field_name} with unknown "
                    f"or conflicting identifier system {system!r} "
                    f"(expected {PULSEOS_HEALTH_ID_SYSTEM!r})"
                )

            # Validate value
            if value is not None:
                if not isinstance(value, str) or (
                    value != patient.health_id and value != expected_patient_id
                ):
                    raise ConflictingPatientReferenceError(
                        f"Resource {resource_id or '<unknown>'} has {field_name} with conflicting "
                        f"patient identifier value {value!r} (expected {patient.health_id!r})"
                    )
            elif system is not None:
                # System is present without a valid value: ambiguous / fail safely
                raise ConflictingPatientReferenceError(
                    f"Resource {resource_id or '<unknown>'} has {field_name} with ambiguous "
                    f"patient identifier (system provided without value)"
                )


def validate_and_attach_patient(
    resource_data: bytes | str | dict[str, Any],
    patient: Patient,
    *,
    expected_resource_type: str | None = None,
    bundle_context: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Parse, validate, and inject the canonical patient reference into a clinical resource.

    Enforces:
    1. Valid JSON object structure.
    2. resourceType is one of the supported types (and matches expected_resource_type if set).
    3. Any existing patient reference (subject or patient) must not conflict with target patient.
    4. Canonical patient reference is injected into the exact field defined by FHIR R4
       (e.g., ``subject`` for Condition, ``patient`` for Immunization).
    5. Spurious cross-field references (e.g. ``patient`` on Condition) are stripped if valid,
       or rejected if conflicting.
    6. For DiagnosticReport, embedded Observation results are converted into contained resources
       with local fragment references (#<id>). Existing references must resolve to a valid
       contained Observation or to an entry in the exported Bundle; dangling or unresolvable
       references are rejected.
    """
    if isinstance(resource_data, (bytes, str)):
        try:
            parsed = json.loads(resource_data)
        except (ValueError, UnicodeDecodeError) as exc:
            raise MalformedResourcePayloadError(
                f"Stored resource is not valid JSON ({type(exc).__name__})"
            ) from exc
    elif isinstance(resource_data, dict):
        parsed = json.loads(json.dumps(resource_data))  # deep copy
    else:
        raise MalformedResourcePayloadError(
            f"Expected JSON bytes, string, or dict, got {type(resource_data).__name__}"
        )

    if not isinstance(parsed, dict):
        raise MalformedResourcePayloadError("Top level of stored resource is not a JSON object")

    resource_type = parsed.get("resourceType")
    if not isinstance(resource_type, str):
        raise MalformedResourcePayloadError("Stored resource has no resourceType string")

    if resource_type not in SUPPORTED_EXPORT_RESOURCE_TYPES:
        raise FHIRSerializationError(
            f"Unsupported FHIR resource type for export: {resource_type!r}"
        )

    if expected_resource_type and resource_type != expected_resource_type:
        raise FHIRSerializationError(
            f"Resource type mismatch: expected {expected_resource_type!r}, got {resource_type!r}"
        )

    resource_id = parsed.get("id")
    target_field = RESOURCE_PATIENT_REFERENCE_FIELDS[resource_type]

    # Check for conflicting references in subject or patient fields
    for field_name in ("subject", "patient"):
        if field_name in parsed:
            _check_conflicting_reference(parsed[field_name], patient, resource_id, field_name)

    # Remove the alternate reference field if present
    alternate_field = "patient" if target_field == "subject" else "subject"
    if alternate_field in parsed:
        del parsed[alternate_field]

    # Inject canonical patient reference for this resource type
    parsed[target_field] = canonical_patient_reference(patient)

    # For DiagnosticReport, transform embedded Observation results into contained
    # resources with local fragment references (#<id>) and resolve/validate references
    if resource_type == "DiagnosticReport":
        existing_contained = parsed.get("contained")
        contained_list: list[dict[str, Any]] = []
        used_local_ids: set[str] = set()
        contained_observation_ids: set[str] = set()

        if existing_contained is not None:
            if not isinstance(existing_contained, list):
                raise MalformedResourcePayloadError(
                    "DiagnosticReport contained field must be a list"
                )
            for c_item in existing_contained:
                if not isinstance(c_item, dict):
                    raise MalformedResourcePayloadError(
                        "DiagnosticReport contained item must be a JSON object"
                    )
                if c_item.get("resourceType") == "Observation":
                    for f in ("subject", "patient"):
                        if f in c_item:
                            _check_conflicting_reference(c_item[f], patient, c_item.get("id"), f)
                    if "patient" in c_item:
                        del c_item["patient"]
                    c_item["subject"] = canonical_patient_reference(patient)
                    c_id = c_item.get("id")
                    if isinstance(c_id, str) and c_id.strip():
                        contained_observation_ids.add(c_id.strip())
                c_id = c_item.get("id")
                if isinstance(c_id, str) and c_id.strip():
                    used_local_ids.add(c_id.strip())
                contained_list.append(c_item)

        if "result" in parsed:
            raw_results = parsed["result"]
            if not isinstance(raw_results, list):
                raise MalformedResourcePayloadError("DiagnosticReport result field must be a list")

            # First pass: process and contain all embedded Observation resources
            embedded_ref_by_idx: dict[int, dict[str, Any]] = {}
            for idx, item in enumerate(raw_results):
                if isinstance(item, dict) and item.get("resourceType") == "Observation":
                    # Contained Observation resource: validate patient identity
                    for f in ("subject", "patient"):
                        if f in item:
                            _check_conflicting_reference(item[f], patient, item.get("id"), f)
                    if "patient" in item:
                        del item["patient"]
                    item["subject"] = canonical_patient_reference(patient)

                    # Ensure valid, unique local id
                    raw_id = item.get("id")
                    if (
                        isinstance(raw_id, str)
                        and raw_id.strip()
                        and raw_id.strip() not in used_local_ids
                    ):
                        local_id = raw_id.strip()
                    else:
                        local_id = f"obs-{idx + 1}"
                        while local_id in used_local_ids:
                            local_id = f"obs-{idx + 1}-{uuid4().hex[:6]}"
                    item["id"] = local_id
                    used_local_ids.add(local_id)
                    contained_observation_ids.add(local_id)

                    contained_list.append(item)

                    # Create Reference pointing to local contained resource
                    ref_obj: dict[str, Any] = {"reference": f"#{local_id}"}
                    code_val = item.get("code")
                    if isinstance(code_val, dict):
                        display_text = code_val.get("text")
                        if (
                            not display_text
                            and isinstance(code_val.get("coding"), list)
                            and code_val["coding"]
                        ):
                            coding0 = code_val["coding"][0]
                            if isinstance(coding0, dict):
                                display_text = coding0.get("display")
                        if display_text and isinstance(display_text, str):
                            ref_obj["display"] = display_text
                    embedded_ref_by_idx[idx] = ref_obj

            # Second pass: assemble validated result references
            result_refs: list[dict[str, Any]] = []
            for idx, item in enumerate(raw_results):
                if idx in embedded_ref_by_idx:
                    result_refs.append(embedded_ref_by_idx[idx])
                elif (
                    isinstance(item, dict)
                    and "reference" in item
                    and isinstance(item["reference"], str)
                    and "resourceType" not in item
                ):
                    ref_str = item["reference"].strip()
                    if not ref_str:
                        raise MalformedResourcePayloadError(
                            f"DiagnosticReport {resource_id or '<unknown>'} "
                            "has empty reference string in result"
                        )
                    if ref_str.startswith("#"):
                        target_id = ref_str[1:]
                        if not target_id or target_id not in contained_observation_ids:
                            raise MalformedResourcePayloadError(
                                f"DiagnosticReport {resource_id or '<unknown>'} "
                                f"has dangling fragment reference {ref_str!r}"
                            )
                        result_refs.append(dict(item))
                    else:
                        # Bundle-local reference: must resolve to an actual entry in
                        # the exported Bundle
                        if bundle_context and ref_str in bundle_context:
                            target_full_url = bundle_context[ref_str]
                            ref_obj = dict(item)
                            ref_obj["reference"] = target_full_url
                            result_refs.append(ref_obj)
                        else:
                            raise MalformedResourcePayloadError(
                                f"DiagnosticReport {resource_id or '<unknown>'} "
                                f"has unresolvable reference {ref_str!r}"
                            )
                else:
                    raise MalformedResourcePayloadError(
                        f"DiagnosticReport {resource_id or '<unknown>'} "
                        f"has invalid result entry: {item!r}"
                    )

            parsed["result"] = result_refs

        if contained_list:
            parsed["contained"] = contained_list

    return parsed


def create_fhir_bundle(
    patient: Patient,
    records_and_payloads: Sequence[tuple[MedicalRecord, bytes]],
    *,
    bundle_id: UUID | None = None,
    timestamp: datetime | None = None,
) -> dict[str, Any]:
    """Assemble a FHIR R4 Bundle (type: collection) for the given patient and records.

    The first entry is always the FHIR R4 Patient resource. Subsequent entries contain
    the validated clinical resources with canonical patient references. Cross-resource
    references within the bundle are resolved to the matching entry's canonical fullUrl.
    """
    bid = bundle_id or uuid4()
    ts = timestamp or datetime.now(UTC)

    # First verify ownership and index resolvable bundle entries for cross-resource references
    resolvable_observations: dict[str, str] = {}
    for record, payload_bytes in records_and_payloads:
        if record.patient_id != patient.id:
            raise ConflictingPatientReferenceError(
                f"Record {record.id} belongs to patient {record.patient_id}, not {patient.id}"
            )
        try:
            raw_parsed = json.loads(payload_bytes)
        except Exception:
            continue
        if isinstance(raw_parsed, dict) and raw_parsed.get("resourceType") == "Observation":
            entry_full_url = f"urn:uuid:{record.id}"
            resolvable_observations[entry_full_url] = entry_full_url
            resolvable_observations[str(record.id)] = entry_full_url
            raw_id = raw_parsed.get("id")
            if isinstance(raw_id, str) and raw_id.strip():
                clean_id = raw_id.strip()
                resolvable_observations[f"Observation/{clean_id}"] = entry_full_url
                resolvable_observations[f"urn:uuid:{clean_id}"] = entry_full_url
            resolvable_observations[f"Observation/{record.id}"] = entry_full_url

    bundle: dict[str, Any] = {
        "resourceType": "Bundle",
        "id": str(bid),
        "type": "collection",
        "timestamp": ts.isoformat(),
        "entry": [
            {
                "fullUrl": f"urn:uuid:{patient.id}",
                "resource": build_patient_resource(patient),
            }
        ],
    }

    for record, payload_bytes in records_and_payloads:
        validated_resource = validate_and_attach_patient(
            payload_bytes,
            patient,
            bundle_context=resolvable_observations,
        )
        bundle["entry"].append(
            {
                "fullUrl": f"urn:uuid:{record.id}",
                "resource": validated_resource,
            }
        )

    return bundle


def serialize_bundle_to_json(bundle: dict[str, Any]) -> bytes:
    """Serialize the FHIR Bundle dict to JSON bytes."""
    return json.dumps(bundle, separators=(",", ":"), ensure_ascii=False, sort_keys=True).encode(
        "utf-8"
    )
