"""consent API schemas — camelCase wire shapes (docs/API_GUIDELINES.md).

Request bodies extend ``app.shared.schemas.RequestModel`` (unknown fields rejected on
writes); responses extend ``ApiModel``. Listings use the shared ``{items, nextCursor}``
shape and enums serialize as SCREAMING_SNAKE strings.

Two content rules govern everything defined here:

- **Existence vs content** (docs/DATABASE_DESIGN.md §Modeling Rules, docs/SECURITY.md):
  nothing on these models carries record content. A request names categories, never
  filenames, service dates, or descriptions, which leak information by themselves.
- **Categories are addressed by code, never by id.** ``CBC`` is the vocabulary the rest of
  the API already speaks (``POST /records`` takes ``categoryCode``) and the only one
  ``GET /record-categories`` publishes; the internal UUID stays internal. Translation
  happens in ``dependencies.py``.

Requester identity is exposed as opaque UUIDs (docs/API_GUIDELINES.md: public identifiers
are opaque). Rendering a clinician's name and hospital needs the records module and is not
wired yet — see the deferred notes in the router.
"""

from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator

from app.modules.consent.models import ConsentDecisionStatus, ConsentRequestStatus
from app.shared.schemas import ApiModel, RequestModel

#: An access request names at least one category and at most the whole vocabulary
#: (docs/DOMAIN_MODEL.md §1 lists ten). The upper bound is a sanity guard, not policy.
MAX_CATEGORIES_PER_REQUEST = 20


def _clean_codes(value: list[str]) -> list[str]:
    """Uppercase and strip the submitted codes; reject blanks. Duplicates are left for the
    service to collapse — de-duplication is a domain rule, not a wire concern."""
    cleaned = [code.strip().upper() for code in value]
    if any(not code for code in cleaned):
        raise ValueError("category codes must not be blank")
    return cleaned


# -- requests --------------------------------------------------------------------------


class AccessRequestCreateRequest(RequestModel):
    patient_health_id: str = Field(min_length=1, max_length=20)
    category_codes: list[str] = Field(min_length=1, max_length=MAX_CATEGORIES_PER_REQUEST)
    purpose: str = Field(min_length=1, max_length=255)

    _normalize_codes = field_validator("category_codes")(_clean_codes)

    @field_validator("patient_health_id", "purpose")
    @classmethod
    def _stripped_non_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class CategorySelectionRequest(RequestModel):
    """The categories a patient is answering for, shared by approve and reject."""

    category_codes: list[str] = Field(min_length=1, max_length=MAX_CATEGORIES_PER_REQUEST)

    _normalize_codes = field_validator("category_codes")(_clean_codes)


# -- responses -------------------------------------------------------------------------


class AccessRequestResponse(ApiModel):
    """One access request as both parties see it: what was asked, of whom, and whether it
    is still open. What a clinician may actually *read* is never answered here — that is
    ``enforce``'s job on each read (docs/SYSTEM_ARCHITECTURE.md rule 3)."""

    id: UUID
    status: ConsentRequestStatus
    purpose: str
    category_codes: list[str]
    requester_doctor_id: UUID
    requester_hospital_id: UUID
    expires_at: datetime
    created_at: datetime


class AccessRequestListResponse(ApiModel):
    items: list[AccessRequestResponse]
    next_cursor: str | None


class ConsentDecisionResponse(ApiModel):
    """One immutable per-category answer. ``decidedAt`` is the row's creation instant —
    for an append-only record they are the same moment by design."""

    id: UUID
    category_code: str
    status: ConsentDecisionStatus
    decided_at: datetime


class ConsentGrantResponse(ApiModel):
    """An active permission derived from an approval. ``revokedAt`` is null while the
    grant stands; once set, the next read is refused immediately."""

    id: UUID
    category_code: str
    grantee_doctor_id: UUID
    granted_at: datetime
    expires_at: datetime
    revoked_at: datetime | None


class DecisionOutcomeResponse(ApiModel):
    """What one approve or reject call produced. ``grants`` is empty for a rejection, and
    ``requestStatus`` becomes ``DECIDED`` once every requested category has an answer."""

    request_id: UUID
    request_status: ConsentRequestStatus
    decisions: list[ConsentDecisionResponse]
    grants: list[ConsentGrantResponse]
