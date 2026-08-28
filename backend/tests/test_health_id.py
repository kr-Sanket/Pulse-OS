"""Health ID generator/validator tests — ADR-012, docs/DOMAIN_MODEL.md §4."""

import re

from app.modules.patients.health_id import (
    compute_check_character,
    generate_health_id,
    is_valid_health_id,
)

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_FORMAT = re.compile(rf"^PHI-IND-\d{{4}}-[{_CROCKFORD}]{{6}}[{_CROCKFORD}]$")


def test_generated_ids_match_format_and_validate() -> None:
    for _ in range(200):
        health_id = generate_health_id(2026)
        assert _FORMAT.fullmatch(health_id), health_id
        assert is_valid_health_id(health_id), health_id


def test_generated_ids_are_random_not_sequential() -> None:
    draws = {generate_health_id(2026) for _ in range(200)}
    assert len(draws) == 200  # no repeats in a tiny sample of a 1.07B space


def test_year_is_embedded() -> None:
    assert generate_health_id(2031).startswith("PHI-IND-2031-")


def test_check_character_is_deterministic() -> None:
    assert compute_check_character("PHIIND20267K3M99") == "X"
    assert compute_check_character("PHIIND20267K3M99") == compute_check_character(
        "PHIIND20267K3M99"
    )


def test_documented_example_is_genuinely_valid() -> None:
    # docs/DOMAIN_MODEL.md §4 and API_GUIDELINES both cite this exact ID.
    assert is_valid_health_id("PHI-IND-2026-7K3M99X")


def test_validation_is_case_insensitive_and_tolerates_whitespace() -> None:
    assert is_valid_health_id("  phi-ind-2026-7k3m99x ")


def test_every_single_character_substitution_is_detected() -> None:
    # ISO 7064 mod 37-2 catches all single substitutions; verify exhaustively.
    health_id = "PHI-IND-2026-7K3M99X"
    body_start = len("PHI-IND-2026-")
    for position in range(body_start, body_start + 6):
        for replacement in _CROCKFORD:
            if replacement == health_id[position]:
                continue
            mutated = health_id[:position] + replacement + health_id[position + 1 :]
            assert not is_valid_health_id(mutated), mutated


def test_adjacent_transpositions_are_detected() -> None:
    health_id = "PHI-IND-2026-7K3M99X"
    body_start = len("PHI-IND-2026-")
    for position in range(body_start, body_start + 5):
        a, b = health_id[position], health_id[position + 1]
        if a == b:
            continue
        swapped = health_id[:position] + b + a + health_id[position + 2 :]
        assert not is_valid_health_id(swapped), swapped


def test_invalid_shapes_are_rejected() -> None:
    invalid = [
        "",
        "PHI-IND-2026-7K3M99",  # missing check character
        "PHI-IND-2026-7K3M99X9",  # too long
        "PHI-IND-26-7K3M99X",  # bad year
        "ABC-IND-2026-7K3M99X",  # wrong namespace
        "PHI-IND-2026-7K3I99X",  # 'I' is not in the Crockford alphabet
        "PHI-IND-2026-000001",  # the rejected sequential style (no check character)
        "PHIIND20267K3M99X",  # hyphens are part of the display format
    ]
    for candidate in invalid:
        assert not is_valid_health_id(candidate), candidate


def test_check_character_of_issued_ids_stays_in_crockford_alphabet() -> None:
    # Generation redraws when the ISO 7064 check char would be I/L/O/U/* so every
    # character of an issued ID is unambiguous.
    for _ in range(300):
        assert generate_health_id(2026)[-1] in _CROCKFORD
