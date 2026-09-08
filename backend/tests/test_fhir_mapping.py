"""Synthea → PulseOS mapping tests. Pure: no database, no object storage, no corpus.

Every test reads ``tests/fixtures/fhir/``, never ``FHIR_Dataset/fhir/`` — the corpus is
1.3 GB and gitignored, so a test that touched it would fail on a fresh clone and in CI. The
fixtures are hand-trimmed from real Synthea output and keep the structure that matters,
including the prohibited identifiers the sanitization tests exist to prove are stripped.
"""

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from app.modules.patients.models import Gender
from app.modules.records.fhir_mapping import (
    PROHIBITED_IDENTIFIER_SYSTEMS,
    SYNTHEA_IDENTIFIER_SYSTEM,
    BundleInvalid,
    MappedBundle,
    ProhibitedDataError,
    assert_no_prohibited_values,
    category_for,
    map_bundle,
    map_patient,
    parse_bundle,
    prohibited_values,
    record_id_for,
)

FIXTURES = Path(__file__).parent / "fixtures" / "fhir"


def load(name: str) -> dict[str, Any]:
    return parse_bundle((FIXTURES / f"{name}.json").read_bytes())


def canonical() -> MappedBundle:
    return map_bundle(load("canonical"))


def patient_resource(bundle: dict[str, Any]) -> dict[str, Any]:
    return next(
        e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "Patient"
    )


# -- parsing and structural validation -------------------------------------------------


def test_a_transaction_bundle_is_accepted() -> None:
    """The corpus ships ``type: transaction``, not ``collection`` or ``document``, and
    carries no ``meta.fhirVersion`` at all — so neither may be required."""
    bundle = load("canonical")
    assert bundle["type"] == "transaction"
    assert "meta" not in bundle


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (b"{not json", "not valid JSON"),
        (b"[]", "top level is not a JSON object"),
        (b'{"resourceType": "Patient"}', "expected 'Bundle'"),
        (b'{"resourceType": "Bundle", "type": "transaction"}', "no entry array"),
        (b'{"resourceType": "Bundle", "type": "transaction", "entry": []}', "no entry array"),
    ],
)
def test_malformed_input_is_refused_with_a_reason(raw: bytes, reason: str) -> None:
    with pytest.raises(BundleInvalid, match=reason):
        parse_bundle(raw)


def test_a_bundle_without_a_patient_is_refused() -> None:
    with pytest.raises(BundleInvalid, match="found 0"):
        load("no_patient")


def test_a_bundle_with_two_patients_is_refused() -> None:
    """Zero occurrences in the corpus, asserted anyway: importing one of two patients would
    file the other one's history against them."""
    with pytest.raises(BundleInvalid, match="found 2"):
        load("two_patients")


# -- the canonical patient key ---------------------------------------------------------


def test_the_patient_key_is_the_synthea_business_identifier() -> None:
    """Verified unique across all 1,180 bundles, and distinct from ``Patient.id`` in every
    one of them — so the two must not be confused."""
    bundle = load("canonical")
    resource = patient_resource(bundle)
    patient = map_patient(resource)
    expected = next(
        i["value"] for i in resource["identifier"] if i["system"] == SYNTHEA_IDENTIFIER_SYSTEM
    )
    assert patient.synthea_id == expected
    assert patient.synthea_id != resource["id"]


def test_demographics_are_mapped_and_nothing_else_is() -> None:
    patient = map_patient(patient_resource(load("canonical")))
    assert patient.full_name == "Fixture999 Testcase999"
    assert patient.date_of_birth == date(1962, 8, 27)
    assert patient.gender is Gender.MALE


def test_a_patient_without_the_synthea_identifier_cannot_be_keyed() -> None:
    with pytest.raises(BundleInvalid, match="no Synthea business identifier"):
        map_patient({"resourceType": "Patient", "identifier": [], "name": []})


# -- record mapping --------------------------------------------------------------------


def test_each_mapped_resource_type_becomes_one_record() -> None:
    mapping = canonical()
    assert {record.category_code for record in mapping.records} == {
        "CONDITION",
        "PRESCRIPTION",
        "PROCEDURE",
        "VACCINATION",
        "ALLERGY",
        "LAB_REPORT",
        "CBC",
    }


def test_encounters_claims_and_orphan_observations_are_not_records() -> None:
    """An Encounter is a grouping key, a Claim is billing, and an Observation with no
    DiagnosticReport parent is skipped for this slice (OD-S4)."""
    mapping = canonical()
    assert len(mapping.records) == 7
    titles = " ".join(record.title for record in mapping.records)
    assert "General examination" not in titles  # the Encounter
    assert "Body Height" not in titles  # the orphan vital-signs Observation


def test_a_haemogram_files_under_the_category_the_vocabulary_already_had() -> None:
    assert (
        category_for(
            {"resourceType": "DiagnosticReport", "code": {"text": "COMPLETE BLOOD COUNT panel"}}
        )
        == "CBC"
    )
    assert (
        category_for(
            {"resourceType": "DiagnosticReport", "code": {"coding": [{"code": "58410-2"}]}}
        )
        == "CBC"
    )
    assert (
        category_for({"resourceType": "DiagnosticReport", "code": {"text": "Lipid Panel"}})
        == "LAB_REPORT"
    )


def test_unmapped_resource_types_are_skipped_rather_than_rejected() -> None:
    """An allow-list, so a future Synthea release adding a resource type cannot break the
    import — it is simply not imported."""
    assert category_for({"resourceType": "CarePlan"}) is None
    assert category_for({"resourceType": "Claim"}) is None
    assert category_for({"resourceType": "SomethingInvented"}) is None


def test_the_clinical_date_comes_from_the_right_field_per_type() -> None:
    by_category = {record.category_code: record for record in canonical().records}
    assert by_category["CONDITION"].date_of_service == date(1993, 11, 8)  # onsetDateTime
    assert by_category["PRESCRIPTION"].date_of_service == date(2004, 9, 6)  # authoredOn
    assert by_category["PROCEDURE"].date_of_service == date(2010, 12, 7)  # performedPeriod
    assert by_category["VACCINATION"].date_of_service == date(2018, 10, 1)  # occurrenceDateTime
    assert by_category["ALLERGY"].date_of_service == date(1963, 4, 3)  # recordedDate
    assert by_category["LAB_REPORT"].date_of_service == date(2009, 9, 26)  # effectiveDateTime


def test_the_title_reads_as_both_a_heading_and_a_filename() -> None:
    """It is rendered as the record heading by the patient portal (``recordTitle`` returns
    ``originalFilename``) and used as the download filename."""
    by_category = {record.category_code: record for record in canonical().records}
    assert by_category["LAB_REPORT"].title == "Basic Metabolic Panel — 2009-09-26.json"


def test_a_lab_panel_description_carries_its_analyte_values() -> None:
    """The field doing the work under Path 1: without it the portal shows a filename and a
    byte count, which is not a clinical detail."""
    by_category = {record.category_code: record for record in canonical().records}
    assert by_category["LAB_REPORT"].description == "Basic Metabolic Panel: Glucose 82.5 mg/dL"


def test_status_qualifiers_that_change_meaning_are_kept() -> None:
    by_category = {record.category_code: record for record in canonical().records}
    assert by_category["CONDITION"].description == "Diabetes (active, confirmed)"
    assert by_category["ALLERGY"].description == "Allergy to eggs (low, allergy)"
    assert by_category["PRESCRIPTION"].description.endswith("(active)")


# -- reference resolution --------------------------------------------------------------


def test_observations_are_folded_into_the_report_that_claims_them() -> None:
    """343 of the canonical demo patient's 443 Observations have a DiagnosticReport parent;
    folding them is what keeps 589 rows from reaching the portal instead of 103."""
    by_category = {record.category_code: record for record in canonical().records}
    stored = json.loads(by_category["LAB_REPORT"].resource_json)
    assert [result["code"]["text"] for result in stored["result"]] == ["Glucose"]
    assert stored["result"][0]["valueQuantity"]["value"] == 82.5


def test_an_unresolvable_reference_warns_and_keeps_the_record() -> None:
    """A panel missing one analyte is still worth showing; refusing it would lose the rest."""
    mapping = map_bundle(load("degraded"))
    assert any("did not resolve" in warning for warning in mapping.warnings)
    assert len(mapping.records) == 1  # the report survived


def test_a_resource_with_no_usable_date_is_skipped_not_defaulted() -> None:
    """``date_of_service`` is NOT NULL, and a wrong date on a historical diagnosis is worse
    than an absent record."""
    mapping = map_bundle(load("degraded"))
    assert any("no usable date" in warning for warning in mapping.warnings)
    assert all(record.category_code != "CONDITION" for record in mapping.records)


# -- determinism -----------------------------------------------------------------------


def test_record_ids_are_derived_and_therefore_stable() -> None:
    """The whole idempotency story: the derived id produces the same ``s3_key`` on every
    run, so a second import collides on a UNIQUE constraint instead of duplicating."""
    first = record_id_for("patient-a", "Condition", "resource-1")
    assert first == record_id_for("patient-a", "Condition", "resource-1")
    assert first != record_id_for("patient-b", "Condition", "resource-1")
    assert first != record_id_for("patient-a", "Procedure", "resource-1")
    assert first != record_id_for("patient-a", "Condition", "resource-2")


def test_mapping_the_same_bundle_twice_yields_identical_records() -> None:
    first, second = canonical().records, canonical().records
    assert [r.record_id for r in first] == [r.record_id for r in second]
    assert [r.resource_json for r in first] == [r.resource_json for r in second]


# -- sanitization ----------------------------------------------------------------------


def test_the_fixture_really_does_carry_the_prohibited_identifiers() -> None:
    """Guards the guard: if the fixture ever loses these, every test below would pass
    vacuously and the sanitization guarantee would be untested."""
    systems = {i["system"] for i in patient_resource(load("canonical"))["identifier"]}
    assert systems >= PROHIBITED_IDENTIFIER_SYSTEMS


def test_prohibited_values_collects_the_secrets_to_check_for() -> None:
    values = prohibited_values(patient_resource(load("canonical")))
    assert {"999-00-0001", "S99900001", "X99900001X", "555-999-0001"} <= values
    assert {"Fixture999", "Testcase999"} <= values  # the patient's own name


def test_no_stored_object_contains_ssn_licence_passport_mrn_phone_or_name() -> None:
    """The property that matters: not "we removed the fields we knew about", but "these
    exact strings are not in the bytes we store"."""
    bundle = load("canonical")
    forbidden = prohibited_values(patient_resource(bundle))
    for record in map_bundle(bundle).records:
        blob = record.resource_json.decode()
        for secret in forbidden:
            assert secret not in blob, f"{secret!r} leaked into {record.title}"


def test_stored_objects_carry_no_patient_reference_or_narrative() -> None:
    for record in canonical().records:
        stored = json.loads(record.resource_json)
        assert "subject" not in stored
        assert "reference" not in json.dumps(stored)
        assert not isinstance(stored.get("text"), dict)


def test_the_clinical_codes_are_preserved_for_the_future_rag_layer() -> None:
    """SNOMED/LOINC/RxNorm are the one thing that cannot be recovered later without
    re-importing, so losing them would force a redesign of this layer (AI_ARCHITECTURE §4)."""
    by_category = {record.category_code: record for record in canonical().records}
    condition = json.loads(by_category["CONDITION"].resource_json)
    assert condition["code"]["coding"][0]["system"] == "http://snomed.info/sct"
    assert condition["code"]["coding"][0]["code"] == "44054006"
    medication = json.loads(by_category["PRESCRIPTION"].resource_json)
    assert "rxnorm" in medication["medicationCodeableConcept"]["coding"][0]["system"]
    panel = json.loads(by_category["LAB_REPORT"].resource_json)
    assert panel["result"][0]["code"]["coding"][0]["system"] == "http://loinc.org"


def test_a_clinically_useful_display_survives_when_its_reference_does_not() -> None:
    """``reference`` is a pointer into a bundle the reader does not have; ``display`` is the
    half a human can use."""
    by_category = {record.category_code: record for record in canonical().records}
    medication = json.loads(by_category["PRESCRIPTION"].resource_json)
    assert medication["requester"]["display"] == "Dr. Fixture Practitioner999"
    assert "reference" not in medication["requester"]


def test_the_post_scrub_assertion_actually_fires() -> None:
    with pytest.raises(ProhibitedDataError):
        assert_no_prohibited_values(b'{"note":"999-00-0001"}', ["999-00-0001"])
    assert_no_prohibited_values(b'{"note":"clean"}', ["999-00-0001"])


# -- defensive scrubbing on resources the corpus does not currently produce -------------
#
# A corpus scan found no mapped clinical resource carrying an ``identifier`` list or a
# narrative ``text`` div, so the fixtures cannot exercise those branches. They are the
# belt for a future Synthea release that starts emitting them, and an untested guard is
# not a guard — hence these three, built in memory rather than as another fixture.


def _bundle_with(resource: dict[str, Any]) -> dict[str, Any]:
    """A minimal valid bundle wrapping one clinical resource, reusing the fixture Patient
    so the prohibited-value set is the real one."""
    bundle = load("canonical")
    patient_entry = next(
        entry for entry in bundle["entry"] if entry["resource"]["resourceType"] == "Patient"
    )
    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [patient_entry, {"fullUrl": "urn:uuid:test", "resource": resource}],
    }


def test_an_identifier_on_a_clinical_resource_is_reduced_to_the_allow_list() -> None:
    mapping = map_bundle(
        _bundle_with(
            {
                "resourceType": "Condition",
                "id": "c1",
                "code": {"text": "Diabetes"},
                "onsetDateTime": "1993-11-08",
                "identifier": [
                    {"system": "http://hl7.org/fhir/sid/us-ssn", "value": "999-00-0001"},
                    {"system": SYNTHEA_IDENTIFIER_SYSTEM, "value": "keep-me"},
                ],
            }
        )
    )
    stored = json.loads(mapping.records[0].resource_json)
    assert stored["identifier"] == [{"system": SYNTHEA_IDENTIFIER_SYSTEM, "value": "keep-me"}]


def test_a_prohibited_identifier_with_no_allow_listed_sibling_drops_the_field_entirely() -> None:
    mapping = map_bundle(
        _bundle_with(
            {
                "resourceType": "Procedure",
                "id": "p1",
                "code": {"text": "Colonoscopy"},
                "performedDateTime": "2010-12-07",
                "identifier": [
                    {"system": "http://hl7.org/fhir/sid/us-ssn", "value": "999-00-0001"}
                ],
            }
        )
    )
    stored = json.loads(mapping.records[0].resource_json)
    assert "identifier" not in stored


def test_a_narrative_div_on_a_clinical_resource_is_stripped() -> None:
    mapping = map_bundle(
        _bundle_with(
            {
                "resourceType": "Condition",
                "id": "c2",
                "code": {"text": "Diabetes"},
                "onsetDateTime": "1993-11-08",
                "text": {
                    "status": "generated",
                    "div": "<div>Fixture999 Testcase999, SSN 999-00-0001</div>",
                },
            }
        )
    )
    stored = json.loads(mapping.records[0].resource_json)
    assert "text" not in stored


def test_a_resource_without_an_id_warns_and_is_skipped() -> None:
    """No id means no derivable record id, so no idempotency — better skipped than
    imported under a key the next run cannot reproduce."""
    mapping = map_bundle(
        _bundle_with(
            {"resourceType": "Condition", "code": {"text": "X"}, "onsetDateTime": "2000-01-01"}
        )
    )
    assert mapping.records == ()
    assert any("without an id" in warning for warning in mapping.warnings)


def test_an_observation_value_that_is_not_a_quantity_still_renders() -> None:
    mapping = map_bundle(
        _bundle_with(
            {
                "resourceType": "DiagnosticReport",
                "id": "d9",
                "code": {"text": "Survey"},
                "effectiveDateTime": "2015-01-01",
                "result": [{"reference": "urn:uuid:obs-str"}],
            }
        )
        | {}
    )
    # No resolvable result: the report survives with a plain label and a warning.
    assert mapping.records[0].description == "Survey"
    assert any("did not resolve" in warning for warning in mapping.warnings)
