"""Pulse Health ID generation and validation — ADR-012, docs/DOMAIN_MODEL.md §4.

Format ``PHI-IND-YYYY-XXXXXXC``: 6 cryptographically random Crockford-Base32 characters
(no ``I L O U`` — unambiguous to read aloud, type, and print) plus an ISO 7064 mod 37-2
check character computed over the alphanumeric characters of the full ID (hyphens are
display-only). The check character makes an ID offline-validatable before any API call.

Uniqueness is NOT guaranteed here — callers draw a candidate and INSERT against the DB
unique constraint, redrawing on collision (draw-and-insert, no sequences, no locks).
"""

import re
import secrets
from datetime import UTC, datetime
from typing import Final

HEALTH_ID_PREFIX: Final = "PHI-IND"

# Crockford Base32: excludes I, L, O, U.
_CROCKFORD_ALPHABET: Final = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_RANDOM_LENGTH: Final = 6

# ISO 7064 mod 37-2 character set: values 0-35 for 0-9A-Z, plus '*' as value 36.
_ISO7064_ALPHABET: Final = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ*"

_HEALTH_ID_PATTERN: Final = re.compile(
    rf"^{HEALTH_ID_PREFIX}-(?P<year>\d{{4}})-"
    rf"(?P<body>[{_CROCKFORD_ALPHABET}]{{{_RANDOM_LENGTH}}})(?P<check>[0-9A-Z*])$"
)


def compute_check_character(alphanumeric_payload: str) -> str:
    """ISO 7064 mod 37-2 check character (the recursive 'pure system' algorithm,
    as used by e.g. ISBT 128). Payload must already be uppercase 0-9/A-Z."""
    value = 0
    for char in alphanumeric_payload:
        value = ((value + _ISO7064_ALPHABET.index(char)) * 2) % 37
    return _ISO7064_ALPHABET[(38 - value) % 37]


def _checksum_payload(year: int, body: str) -> str:
    # Hyphens are visual grouping only; the checksum covers every meaningful character.
    return f"{HEALTH_ID_PREFIX.replace('-', '')}{year:04d}{body}"


def generate_health_id(year: int | None = None) -> str:
    """Draw one random candidate Health ID (caller handles DB-uniqueness).

    Candidates whose check character falls outside the Crockford alphabet
    (``I L O U *`` — ~1/7 of draws) are redrawn so every character of an issued ID
    stays unambiguous; validation itself remains strict ISO 7064.
    """
    issue_year = year if year is not None else datetime.now(UTC).year
    while True:
        body = "".join(secrets.choice(_CROCKFORD_ALPHABET) for _ in range(_RANDOM_LENGTH))
        check = compute_check_character(_checksum_payload(issue_year, body))
        if check in _CROCKFORD_ALPHABET:
            return f"{HEALTH_ID_PREFIX}-{issue_year:04d}-{body}{check}"


def is_valid_health_id(candidate: str) -> bool:
    """Offline validation: format + ISO 7064 check character. Case-insensitive input
    (reception desks type lowercase); hyphens are required in their display positions."""
    match = _HEALTH_ID_PATTERN.fullmatch(candidate.strip().upper())
    if match is None:
        return False
    payload = _checksum_payload(int(match["year"]), match["body"])
    return compute_check_character(payload) == match["check"]
