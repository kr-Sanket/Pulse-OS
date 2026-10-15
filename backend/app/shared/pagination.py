"""Cursor pagination primitives (docs/API_GUIDELINES.md: ``?cursor=&limit=``, max 100,
response ``{items, nextCursor}``; offset pagination is not used).

Two cursor shapes, both opaque to clients, whose format may change without an API version
bump:

* :class:`CursorKey` — a keyset over ``(created_at, id)``, newest first. The default for
  listings whose natural order is when the row appeared (consent requests, grants, audit,
  the doctor roster).
* :class:`DateCursor` — a keyset over ``(date_of_service, id)`` in either direction, for
  listings ordered by a *clinical* date rather than a row's insertion time. It carries the
  sort it was issued for, because the same position means different things in each
  direction and a cursor used under the other one would silently return a wrong page.

Why a second shape rather than a wider first one: ``CursorKey`` is consumed by four
modules, and every one of them wants exactly the ordering it already has. Widening it
would make every caller state a direction it does not vary.
"""

import base64
import binascii
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

MAX_PAGE_SIZE: Final = 100
DEFAULT_PAGE_SIZE: Final = 20

_SEPARATOR: Final = "|"


class InvalidCursorError(Exception):
    """The supplied cursor is not one we issued (corrupted, truncated, or forged)."""


@dataclass(frozen=True, slots=True)
class CursorKey:
    """The keyset position after which the next page starts."""

    created_at: datetime
    item_id: UUID


def encode_cursor(key: CursorKey) -> str:
    raw = f"{key.created_at.isoformat()}{_SEPARATOR}{key.item_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> CursorKey:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        created_at_part, _, id_part = raw.partition(_SEPARATOR)
        return CursorKey(created_at=datetime.fromisoformat(created_at_part), item_id=UUID(id_part))
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise InvalidCursorError() from exc


class SortDirection(StrEnum):
    """Which end of a date-ordered listing comes first.

    The values are the wire format (``?sort=newest``) *and* part of the cursor payload, so
    renaming a member is an API change.
    """

    NEWEST_FIRST = "newest"
    OLDEST_FIRST = "oldest"


@dataclass(frozen=True, slots=True)
class DateCursor:
    """The keyset position after which the next page of a date-ordered listing starts.

    ``sort_date`` is a calendar date, not an instant, and is **not unique** — a patient
    routinely has several records on one day (39 distinct dates across 103 in the demo
    corpus). ``created_at`` orders same-date records by insertion time, and ``item_id``
    is the ultimate tie-breaker when insertion times are also identical.
    """

    sort: SortDirection
    sort_date: date
    item_id: UUID
    created_at: datetime | None = None


def encode_date_cursor(cursor: DateCursor) -> str:
    if cursor.created_at is not None:
        raw = (
            f"{cursor.sort.value}{_SEPARATOR}"
            f"{cursor.sort_date.isoformat()}{_SEPARATOR}"
            f"{cursor.created_at.isoformat()}{_SEPARATOR}"
            f"{cursor.item_id}"
        )
    else:
        raw = (
            f"{cursor.sort.value}{_SEPARATOR}"
            f"{cursor.sort_date.isoformat()}{_SEPARATOR}"
            f"{cursor.item_id}"
        )
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_date_cursor(token: str) -> DateCursor:
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        parts = raw.split(_SEPARATOR)
        if len(parts) == 4:
            sort_part, date_part, created_at_part, id_part = parts
            return DateCursor(
                sort=SortDirection(sort_part),
                sort_date=date.fromisoformat(date_part),
                item_id=UUID(id_part),
                created_at=datetime.fromisoformat(created_at_part),
            )
        if len(parts) == 3:
            sort_part, date_part, id_part = parts
            return DateCursor(
                sort=SortDirection(sort_part),
                sort_date=date.fromisoformat(date_part),
                item_id=UUID(id_part),
            )
        raise ValueError("Invalid cursor segment count")
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise InvalidCursorError() from exc
