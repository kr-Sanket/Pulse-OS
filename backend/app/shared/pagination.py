"""Cursor pagination primitives (docs/API_GUIDELINES.md: ``?cursor=&limit=``, max 100,
response ``{items, nextCursor}``; offset pagination is not used).

The cursor is an opaque keyset token over ``(created_at, id)`` — the stable sort every
paginated listing uses (newest first, UUID as the tie-breaker). Clients must treat it as
a black box; its format may change without an API version bump.
"""

import base64
import binascii
from dataclasses import dataclass
from datetime import datetime
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
