"""Cursor pagination primitives: opaque, round-trippable, and strict on garbage."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.shared.pagination import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    CursorKey,
    InvalidCursorError,
    decode_cursor,
    encode_cursor,
)


def test_cursor_round_trip_preserves_key() -> None:
    key = CursorKey(created_at=datetime(2026, 8, 28, 12, 30, 45, tzinfo=UTC), item_id=uuid4())
    assert decode_cursor(encode_cursor(key)) == key


def test_cursor_round_trip_with_naive_timestamp() -> None:
    # SQLite returns naive datetimes; the cursor must survive both flavors.
    key = CursorKey(created_at=datetime(2026, 8, 28, 12, 30, 45), item_id=uuid4())
    assert decode_cursor(encode_cursor(key)) == key


def test_cursor_is_opaque_not_plaintext() -> None:
    key = CursorKey(created_at=datetime(2026, 8, 28), item_id=uuid4())
    assert str(key.item_id) not in encode_cursor(key)


@pytest.mark.parametrize(
    "garbage",
    [
        "",
        "not-base64!!!",
        "aGVsbG8=",  # valid base64, wrong payload ("hello")
        "MjAyNi0wMS0wMQ==",  # date only, no separator/uuid
    ],
)
def test_invalid_cursors_are_rejected(garbage: str) -> None:
    with pytest.raises(InvalidCursorError):
        decode_cursor(garbage)


def test_page_size_constants_match_api_guidelines() -> None:
    assert MAX_PAGE_SIZE == 100  # docs/API_GUIDELINES.md: limit max 100
    assert 1 <= DEFAULT_PAGE_SIZE <= MAX_PAGE_SIZE
