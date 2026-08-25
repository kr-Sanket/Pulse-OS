"""Internal authenticated-identity types — the only auth objects other modules depend on.

ADR-011 confines the external provider (Firebase) behind this module's port; ADR-013's
layer 1 (static role gate) consumes ``Role``. Layers 2 (relationship) and 3 (consent) are
implemented by their owning modules in later milestones.
"""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class Role(StrEnum):
    """The four platform roles (docs/DOMAIN_MODEL.md §3, ADR-013).

    SYSTEM_ADMIN is a platform-operations role with a hard invariant: it can never
    read medical content, so it must never appear in a role gate on a PHI endpoint.
    """

    PATIENT = "PATIENT"
    DOCTOR = "DOCTOR"
    HOSPITAL_ADMIN = "HOSPITAL_ADMIN"
    SYSTEM_ADMIN = "SYSTEM_ADMIN"


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """Request-scoped identity carried through the application — nothing more.

    ``user_id`` is the internal User UUID (docs/DOMAIN_MODEL.md: all FKs are UUIDs;
    business identifiers like the Health ID never appear in the auth context).
    """

    user_id: UUID
    firebase_uid: str
    role: Role
