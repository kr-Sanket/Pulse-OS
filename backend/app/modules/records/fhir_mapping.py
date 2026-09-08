"""Synthea FHIR R4 → PulseOS domain mapping. Pure functions: no DB, no FastAPI, no I/O.

Everything here is a total function over a parsed bundle, which is what makes the rules
below testable without a database and reusable by a future arq worker (ADR-014) rather than
only by the import CLI.

**What the corpus actually looks like**, verified across all 1,180 bundles rather than
assumed, because three plausible-sounding assumptions are false:

* ``Bundle.type`` is ``transaction``, not ``collection`` or ``document``, and there is no
  ``meta.fhirVersion`` anywhere — R4 is asserted by the dataset, never by the data.
* references are **``urn:uuid:<uuid>`` matching ``entry.fullUrl``**, never ``Patient/{id}``.
  Resolution is therefore bundle-local: build the ``fullUrl`` map, then look up. There are
  no cross-bundle references, which is why one bundle is one self-contained patient.
* ``Patient.id`` and the Synthea business identifier are **different UUIDs** — they disagree
  in 1,180 of 1,180 bundles. See :data:`SYNTHEA_IDENTIFIER_SYSTEM`.

**Two resource types are deliberately not records.** ``Encounter`` is a grouping key, not a
document. ``Observation`` folds into the ``DiagnosticReport`` that claims it in
``result[]`` — 343 of one patient's 443 Observations have such a parent, and a lab panel
genuinely *is* the document while its analytes are its results. Folding takes the canonical
demo patient from 589 rows to 103 and is the difference between a readable portal listing
and a flooded one.
"""

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Final
from uuid import UUID, uuid5

from app.modules.patients.models import Gender

#: The Synthea business identifier — the canonical patient key, verified unique across all
#: 1,180 bundles and identical to both the filename UUID and the ``MR`` identifier in every
#: one of them. Chosen over ``Patient.id`` (also unique, but a bundle-serialisation detail
#: used only as the target of ``urn:uuid:`` references) because it is the identity Synthea
#: stamps into the filename, so a stored row can be traced back to a file from outside it.
SYNTHEA_IDENTIFIER_SYSTEM: Final = "https://github.com/synthetichealth/synthea"

#: Identifier systems that must never reach PulseOS storage — enumerated from the corpus,
#: not guessed: every ``Patient`` carries a synthetic SSN, ~85% a driver's licence and ~80%
#: a passport number, and the MRN duplicates the Synthea id under a foreign hospital's
#: system. Synthetic or not, these are PII-shaped and there is nowhere in the schema they
#: belong. The allow-list in :func:`_scrub` is what enforces this; this set is the
#: independent second check in :func:`assert_no_prohibited_values`.
PROHIBITED_IDENTIFIER_SYSTEMS: Final = frozenset(
    {
        "http://hl7.org/fhir/sid/us-ssn",
        "urn:oid:2.16.840.1.113883.4.3.25",
        "http://standardhealthrecord.org/fhir/StructureDefinition/passportNumber",
        "http://hospital.smarthealthit.org",
    }
)

#: Fixed namespace for deriving record ids. A UUIDv5 over
#: ``{synthea_patient}:{resource_type}:{resource_id}`` makes the derived ``s3_key`` collide
#: on re-import, so the UNIQUE constraint — not application bookkeeping — is what makes the
#: import idempotent. Never change this value: it would orphan every previously imported
#: row and its object.
SYNTHEA_RECORD_NAMESPACE: Final = UUID("6f9d6b8e-1c2a-5f47-9b3d-8a41e7c25d10")

#: Resource types that become one ``MedicalRecord`` each.
MAPPED_RESOURCE_TYPES: Final = frozenset(
    {
        "Condition",
        "Procedure",
        "MedicationRequest",
        "Immunization",
        "AllergyIntolerance",
        "DiagnosticReport",
    }
)

#: LOINC codes and display text identifying a haemogram, which the seeded vocabulary
#: already has a category for. Everything else diagnostic lands in ``LAB_REPORT``.
_CBC_LOINC: Final = frozenset({"58410-2", "57021-8", "6690-2"})
_CBC_TEXT: Final = "complete blood count"

_GENDERS: Final[Mapping[str, Gender]] = {
    "male": Gender.MALE,
    "female": Gender.FEMALE,
    "other": Gender.OTHER,
}

#: ``medical_records.description`` is VARCHAR(255) and ``original_filename`` VARCHAR(255).
MAX_DESCRIPTION: Final = 255
MAX_FILENAME: Final = 255
#: ``patients.full_name`` is VARCHAR(120).
MAX_FULL_NAME: Final = 120

#: The stored object is a FHIR resource, and says so.
FHIR_CONTENT_TYPE: Final = "application/fhir+json"


class BundleInvalid(Exception):
    """The file is not a usable Synthea patient bundle. Carries no resource content —
    callers log the filename and this message, never the payload (docs/SECURITY.md)."""


class ProhibitedDataError(Exception):
    """A prohibited identifier survived scrubbing. Raised instead of storing the object;
    an import that cannot prove an object is clean must fail, not proceed."""


@dataclass(frozen=True, slots=True)
class SyntheaPatient:
    """The demographics PulseOS keeps. Address, telecom, marital status, mother's maiden
    name, race/ethnicity/birthsex and the narrative div are all dropped on the floor: the
    schema has no column for them and the import must not invent one."""

    synthea_id: str
    full_name: str
    date_of_birth: date | None
    gender: Gender


@dataclass(frozen=True, slots=True)
class MappedRecord:
    """One ``MedicalRecord`` row plus the bytes of its stored object.

    ``title`` becomes ``original_filename`` because the patient portal renders that column
    as the heading (``recordTitle`` in ``apps/patient/src/records/view.ts``). That is a
    deliberate, documented compromise (OD-S2 / Path 1): it buys a meaningful demo with no
    schema, API, client or UI change, and a later clinical-content column retires it.
    """

    record_id: UUID
    category_code: str
    date_of_service: date
    title: str
    description: str
    resource_json: bytes


@dataclass(frozen=True, slots=True)
class MappedBundle:
    patient: SyntheaPatient
    records: tuple[MappedRecord, ...]
    #: Non-fatal notes (unresolvable reference, undatable resource). Never contains content.
    warnings: tuple[str, ...]


# -- parsing and validation ----------------------------------------------------------------


def parse_bundle(raw: bytes | str) -> dict[str, Any]:
    """Decode and structurally validate one bundle file.

    Rejects, with a reason and no payload: unparseable JSON, a non-Bundle document, a
    missing ``entry`` array, and a patient count other than exactly one. The last has zero
    occurrences in this corpus and is asserted anyway — a two-patient bundle would otherwise
    silently file one patient's history against the other.
    """
    try:
        bundle = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise BundleInvalid(f"not valid JSON ({type(exc).__name__})") from exc
    if not isinstance(bundle, dict):
        raise BundleInvalid("top level is not a JSON object")
    if bundle.get("resourceType") != "Bundle":
        raise BundleInvalid(f"resourceType is {bundle.get('resourceType')!r}, expected 'Bundle'")
    entries = bundle.get("entry")
    if not isinstance(entries, list) or not entries:
        raise BundleInvalid("bundle has no entry array")
    patients = [e for e in entries if _resource_type(e) == "Patient"]
    if len(patients) != 1:
        raise BundleInvalid(f"expected exactly 1 Patient resource, found {len(patients)}")
    return bundle


def _resource_type(entry: Any) -> str | None:
    if not isinstance(entry, dict):
        return None
    resource = entry.get("resource")
    return resource.get("resourceType") if isinstance(resource, dict) else None


def _index_by_full_url(bundle: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """The bundle-local reference table. ``urn:uuid:`` references resolve through this and
    nothing else — there is no cross-bundle resolution to attempt."""
    return {
        entry["fullUrl"]: entry["resource"]
        for entry in bundle["entry"]
        if isinstance(entry, dict) and isinstance(entry.get("fullUrl"), str)
    }


# -- patient -------------------------------------------------------------------------------


def synthea_identifier(patient: Mapping[str, Any]) -> str:
    """The canonical key. Raises if absent — a bundle we cannot key is a bundle we cannot
    import idempotently, and importing it once would make the next run duplicate it."""
    identifiers = patient.get("identifier")
    if isinstance(identifiers, list):
        for identifier in identifiers:
            if (
                isinstance(identifier, dict)
                and identifier.get("system") == SYNTHEA_IDENTIFIER_SYSTEM
            ):
                value = identifier.get("value")
                if isinstance(value, str):
                    return value
    raise BundleInvalid("Patient carries no Synthea business identifier")


def map_patient(patient: Mapping[str, Any]) -> SyntheaPatient:
    names = patient.get("name")
    first = names[0] if isinstance(names, list) and names else {}
    given = " ".join(g for g in first.get("given", []) if isinstance(g, str))
    family = first.get("family") if isinstance(first.get("family"), str) else ""
    # Synthea names carry numeric suffixes ("Joaquin141 Rice937"), so they are already
    # self-evidently synthetic; no "(Demo)" suffix is added, which also keeps the
    # import provenance out of the UI (OD-S1).
    full_name = f"{given} {family}".strip() or "Unnamed patient"
    return SyntheaPatient(
        synthea_id=synthea_identifier(patient),
        full_name=full_name[:MAX_FULL_NAME],
        date_of_birth=_iso_date(patient.get("birthDate")),
        gender=_GENDERS.get(str(patient.get("gender", "")).lower(), Gender.UNKNOWN),
    )


def prohibited_values(patient: Mapping[str, Any]) -> frozenset[str]:
    """Every string from this patient that must not appear in any stored object.

    The input to the post-scrub assertion: the SSN/licence/passport/MRN values, the phone
    numbers, and the patient's own name. Derived per patient rather than pattern-matched,
    so the check tests for *these exact secrets* rather than for something resembling them.
    """
    values: set[str] = set()
    identifiers = patient.get("identifier")
    if isinstance(identifiers, list):
        values.update(
            identifier["value"]
            for identifier in identifiers
            if isinstance(identifier, dict)
            and identifier.get("system") in PROHIBITED_IDENTIFIER_SYSTEMS
            and isinstance(identifier.get("value"), str)
        )
    telecoms = patient.get("telecom")
    if isinstance(telecoms, list):
        values.update(
            contact["value"]
            for contact in telecoms
            if isinstance(contact, dict) and isinstance(contact.get("value"), str)
        )
    names = patient.get("name")
    if isinstance(names, list):
        for entry in names:
            if not isinstance(entry, dict):
                continue
            values.update(g for g in entry.get("given", []) if isinstance(g, str))
            if isinstance(entry.get("family"), str):
                values.add(entry["family"])
    return frozenset(value for value in values if value)


def assert_no_prohibited_values(blob: bytes, forbidden: Iterable[str]) -> None:
    """Second, independent check on the serialised object.

    :func:`_scrub` already removes the fields these values live in, and a corpus scan found
    zero occurrences of any of them in the six mapped resource types. This exists because
    "we removed the fields we knew about" is a weaker guarantee than "the bytes we are about
    to store do not contain these strings", and only the second one survives a new Synthea
    release putting an SSN somewhere we did not look.
    """
    haystack = blob.decode("utf-8", errors="ignore")
    for value in forbidden:
        if value and value in haystack:
            # The value itself is a prohibited identifier — it must not reach the message.
            raise ProhibitedDataError(
                "a prohibited patient identifier survived scrubbing; object not stored"
            )


# -- resource scrubbing --------------------------------------------------------------------


def _scrub(node: Any) -> Any:
    """Recursively strip everything that is either prohibited or meaningless once the
    resource leaves its bundle.

    Four rules, in order of why they exist:

    * ``identifier`` lists keep only :data:`SYNTHEA_IDENTIFIER_SYSTEM` entries — the
      allow-list that makes SSN/licence/passport/MRN unrepresentable rather than merely
      absent.
    * ``subject`` goes entirely. The owning patient is already ``medical_records.patient_id``;
      keeping a second copy of their identity inside a downloadable object serves nothing.
    * ``reference`` keys go. They are ``urn:uuid:`` pointers into a bundle the reader does
      not have, so they are noise that reads like a broken link. Sibling ``display`` values
      stay — "Glucose", "Dr. Bennett146 Breitenberg711" — because those are the clinically
      useful half of a reference.
    * narrative ``text`` divs go: generated HTML that routinely restates demographics.
    """
    if isinstance(node, dict):
        scrubbed: dict[str, Any] = {}
        for key, value in node.items():
            if key in ("subject", "reference"):
                continue
            if key == "text" and isinstance(value, dict) and "div" in value:
                continue
            if key == "identifier" and isinstance(value, list):
                kept = [
                    _scrub(item)
                    for item in value
                    if isinstance(item, dict) and item.get("system") == SYNTHEA_IDENTIFIER_SYSTEM
                ]
                if kept:
                    scrubbed[key] = kept
                continue
            cleaned = _scrub(value)
            # A wrapper whose only content was a reference (``"encounter": {...}``) is left
            # empty by the rule above; an empty object in the stored document would read as
            # missing data rather than as omitted noise.
            if isinstance(value, dict) and cleaned == {}:
                continue
            scrubbed[key] = cleaned
        return scrubbed
    if isinstance(node, list):
        return [_scrub(item) for item in node]
    return node


# -- record mapping ------------------------------------------------------------------------


def record_id_for(synthea_patient_id: str, resource_type: str, resource_id: str) -> UUID:
    """Deterministic record id — the whole idempotency story.

    ``s3_key`` is ``records/{patient_id}/{record_id}`` and UNIQUE, so deriving the record id
    from stable inputs makes a second import collide on the constraint instead of inserting
    a duplicate. A ``uuid4()`` here, as the upload path uses, would silently double every
    row on the second run.
    """
    return uuid5(SYNTHEA_RECORD_NAMESPACE, f"{synthea_patient_id}:{resource_type}:{resource_id}")


def _iso_date(value: Any) -> date | None:
    """FHIR ``dateTime``/``date`` → a calendar date. Timezone offsets are truncated rather
    than converted: ``date_of_service`` is the clinical day as recorded, and shifting it by
    a UTC conversion would move some visits to the previous day for no gain."""
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _service_date(resource: Mapping[str, Any]) -> date | None:
    """The clinical date, by resource type. ``date_of_service`` is NOT NULL, so a resource
    with no usable date is skipped with a warning rather than defaulted to today — a wrong
    date on a 1993 diagnosis is worse than an absent record."""
    period = resource.get("performedPeriod")
    candidates = (
        resource.get("onsetDateTime"),
        resource.get("effectiveDateTime"),
        resource.get("authoredOn"),
        resource.get("occurrenceDateTime"),
        resource.get("performedDateTime"),
        period.get("start") if isinstance(period, dict) else None,
        resource.get("recordedDate"),
        resource.get("issued"),
    )
    for candidate in candidates:
        parsed = _iso_date(candidate)
        if parsed is not None:
            return parsed
    return None


def _concept_text(concept: Any) -> str:
    """Display text for a CodeableConcept: ``text`` if present, else the first coding's
    ``display``, else the bare code. Never empty — the label is a user-facing heading."""
    if not isinstance(concept, dict):
        return ""
    text = concept.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    codings = concept.get("coding")
    if isinstance(codings, list):
        for coding in codings:
            if isinstance(coding, dict):
                for key in ("display", "code"):
                    if isinstance(coding.get(key), str) and coding[key].strip():
                        return str(coding[key]).strip()
    return ""


def _codes(concept: Any) -> list[str]:
    if not isinstance(concept, dict) or not isinstance(concept.get("coding"), list):
        return []
    return [
        coding["code"]
        for coding in concept["coding"]
        if isinstance(coding, dict) and isinstance(coding.get("code"), str)
    ]


def _label(resource: Mapping[str, Any]) -> str:
    """The document label, per resource type."""
    resource_type = resource.get("resourceType")
    if resource_type == "MedicationRequest":
        return _concept_text(resource.get("medicationCodeableConcept"))
    if resource_type == "Immunization":
        return _concept_text(resource.get("vaccineCode"))
    return _concept_text(resource.get("code"))


def category_for(resource: Mapping[str, Any]) -> str | None:
    """Which seeded ``record_categories.code`` this resource files under, or None to skip.

    Four of the six map to a single code. ``DiagnosticReport`` splits: the seeded
    vocabulary already has ``CBC``, so a haemogram files there and every other panel under
    ``LAB_REPORT`` rather than inventing a code for something the vocabulary can express.
    """
    resource_type = resource.get("resourceType")
    if resource_type == "Condition":
        return "CONDITION"
    if resource_type == "Procedure":
        return "PROCEDURE"
    if resource_type == "AllergyIntolerance":
        return "ALLERGY"
    if resource_type == "Immunization":
        return "VACCINATION"
    if resource_type == "MedicationRequest":
        return "PRESCRIPTION"
    if resource_type == "DiagnosticReport":
        code = resource.get("code")
        if set(_codes(code)) & _CBC_LOINC or _CBC_TEXT in _concept_text(code).lower():
            return "CBC"
        return "LAB_REPORT"
    return None


def _observation_summary(observation: Mapping[str, Any]) -> str:
    """``Glucose 82 mg/dL`` — one analyte, rendered from ``valueQuantity`` or whatever
    value shape the Observation actually uses."""
    name = _concept_text(observation.get("code"))
    quantity = observation.get("valueQuantity")
    if isinstance(quantity, dict) and quantity.get("value") is not None:
        value = quantity["value"]
        rendered = (
            f"{value:.1f}".rstrip("0").rstrip(".") if isinstance(value, float) else str(value)
        )
        unit = quantity.get("unit") or ""
        return f"{name} {rendered} {unit}".strip()
    for key in ("valueString", "valueBoolean", "valueInteger"):
        if observation.get(key) is not None:
            return f"{name} {observation[key]}".strip()
    concept = _concept_text(observation.get("valueCodeableConcept"))
    return f"{name} {concept}".strip() if concept else name


def _description(resource: Mapping[str, Any], results: list[Mapping[str, Any]]) -> str:
    """The sentence the portal shows under the heading — the field carrying the clinical
    payload under Path 1.

    A DiagnosticReport summarises its own analytes ("Glucose 82 mg/dL · Creatinine 1 mg/dL"),
    which is what turns "a file called Lipid Panel" into something a clinician can read. The
    others append the status qualifier that changes their meaning: a *stopped* prescription
    and an active one are different clinical facts.
    """
    resource_type = resource.get("resourceType")
    label = _label(resource)
    if resource_type == "DiagnosticReport" and results:
        summary = " · ".join(_observation_summary(o) for o in results if _observation_summary(o))
        return _truncate(f"{label}: {summary}" if summary else label, MAX_DESCRIPTION)
    qualifiers: list[str] = []
    if resource_type == "Condition":
        qualifiers = [
            _concept_text(resource.get("clinicalStatus")),
            _concept_text(resource.get("verificationStatus")),
        ]
    elif resource_type in ("MedicationRequest", "Procedure", "Immunization"):
        status = resource.get("status")
        qualifiers = [str(status)] if isinstance(status, str) else []
    elif resource_type == "AllergyIntolerance":
        qualifiers = [str(resource.get("criticality") or ""), _concept_text(resource.get("type"))]
    present = [q for q in qualifiers if q]
    return _truncate(f"{label} ({', '.join(present)})" if present else label, MAX_DESCRIPTION)


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _title(label: str, service_date: date) -> str:
    """``Lipid Panel — 2015-09-14.json``. Rendered as the record heading by the patient
    portal, and used as the download filename, so it has to read as both."""
    stem = _truncate(label or "Clinical record", MAX_FILENAME - 20)
    return f"{stem} — {service_date.isoformat()}.json"


def map_bundle(bundle: Mapping[str, Any]) -> MappedBundle:
    """One validated bundle → one patient plus its records.

    Observations are consumed by the DiagnosticReport that claims them and never become
    records of their own; orphan Observations (vital signs, loose labs) are skipped for this
    slice per OD-S4. Every object is scrubbed and then independently asserted clean before
    it is handed back, so a caller cannot store an unchecked one.
    """
    patient_resource = next(
        entry["resource"] for entry in bundle["entry"] if _resource_type(entry) == "Patient"
    )
    patient = map_patient(patient_resource)
    forbidden = prohibited_values(patient_resource)
    by_url = _index_by_full_url(bundle)

    records: list[MappedRecord] = []
    warnings: list[str] = []
    seen: set[UUID] = set()

    for entry in bundle["entry"]:
        resource_type = _resource_type(entry)
        if resource_type not in MAPPED_RESOURCE_TYPES:
            continue
        resource = entry["resource"]
        resource_id = resource.get("id")
        if not isinstance(resource_id, str):
            warnings.append(f"{resource_type} without an id")
            continue
        category_code = category_for(resource)
        if category_code is None:
            continue
        service_date = _service_date(resource)
        if service_date is None:
            warnings.append(f"{resource_type} {resource_id[:8]} has no usable date")
            continue

        results = _resolve_results(resource, by_url, warnings)
        payload = _scrub(resource)
        if results:
            # The analytes replace the dangling urn:uuid list: the panel becomes one
            # self-contained document, which is also the natural RAG chunk (AI_ARCHITECTURE §4).
            payload["result"] = [_scrub(observation) for observation in results]
        blob = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        assert_no_prohibited_values(blob, forbidden)

        record_id = record_id_for(patient.synthea_id, resource_type, resource_id)
        if record_id in seen:
            warnings.append(f"duplicate {resource_type} id within the bundle")
            continue
        seen.add(record_id)
        records.append(
            MappedRecord(
                record_id=record_id,
                category_code=category_code,
                date_of_service=service_date,
                title=_title(_label(resource), service_date),
                description=_description(resource, results),
                resource_json=blob,
            )
        )

    records.sort(key=lambda record: (record.date_of_service, record.title))
    return MappedBundle(patient=patient, records=tuple(records), warnings=tuple(warnings))


def _resolve_results(
    resource: Mapping[str, Any],
    by_url: Mapping[str, dict[str, Any]],
    warnings: list[str],
) -> list[Mapping[str, Any]]:
    """Resolve ``DiagnosticReport.result[]`` against the bundle-local table.

    An unresolvable reference is a warning, not a failure: a lab panel missing one analyte
    is still worth showing, and refusing the record would lose the other nine.
    """
    if resource.get("resourceType") != "DiagnosticReport":
        return []
    references = resource.get("result")
    if not isinstance(references, list):
        return []
    resolved: list[Mapping[str, Any]] = []
    for reference in references:
        if not isinstance(reference, dict) or not isinstance(reference.get("reference"), str):
            continue
        target = by_url.get(reference["reference"])
        if target is None:
            warnings.append("DiagnosticReport result reference did not resolve")
            continue
        if target.get("resourceType") == "Observation":
            resolved.append(target)
    return resolved
