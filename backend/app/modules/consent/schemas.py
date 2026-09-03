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

from app.modules.auth.domain import Role
from app.modules.consent.models import AuditAction, ConsentDecisionStatus, ConsentRequestStatus
from app.modules.consent.service import ConsentGrantState
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


class StaffDisplayResponse(ApiModel):
    """A member of hospital staff as the patient sees them, wherever this API names one.

    One shape for requesters, grantees and audit actors, because a patient is asking the
    same question in all three places: who is this, and where do they work. It carries no
    identifier — the id it was projected from is already on the row beside it — and no
    registration number, contact detail or employment status.

    ``specialty`` is null when the staff row does not carry one, and always for an
    administrator; ``hospitalName`` is always present, because staff belong to a hospital
    by schema.
    """

    full_name: str
    specialty: str | None
    hospital_name: str


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


class AccessRequestListItemResponse(AccessRequestResponse):
    """A request in a listing: everything above, plus who asked.

    Only the listings carry the names. ``POST /access-requests`` answers the clinician who
    just raised the request, where naming them back would be noise, and resolving it would
    add a lookup to a write path. Both fields are nullable so a row whose requester can no
    longer be resolved still lists, with its ids intact.
    """

    requester: StaffDisplayResponse | None
    #: The hospital the request was raised under — provenance recorded at the time, which
    #: is not necessarily where the requester practises now.
    requester_hospital_name: str | None


class AccessRequestListResponse(ApiModel):
    items: list[AccessRequestListItemResponse]
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


class ConsentGrantListItemResponse(ConsentGrantResponse):
    """A grant in the patient's own listing: everything above, plus how it stands right now.

    ``status`` is derived by the service from ``revokedAt`` and ``expiresAt`` at the moment
    the page is built, using the same predicate enforcement applies — so a client never has
    to decide from its own clock whether a grant would still be honoured. The field is named
    for the wire convention the other listings follow, but it is a reading rather than a
    stored column (``ConsentGrantState`` says so in the domain).

    Only the listing carries it. The single-grant responses answer a change the caller has
    just made, where the resulting state is not in question, and leaving their shape alone
    keeps this addition free of breaking changes.
    """

    status: ConsentGrantState
    #: The clinician the grant was given to. Null only if that staff row cannot be
    #: resolved; the id it was projected from stays on ``granteeDoctorId`` regardless.
    grantee: StaffDisplayResponse | None


class ConsentGrantListResponse(ApiModel):
    items: list[ConsentGrantListItemResponse]
    next_cursor: str | None


class AuditEventResponse(ApiModel):
    """One entry in the patient's append-only trail, as its subject sees it.

    Carries what the row carries and nothing else — no clinician or hospital name, because
    ``AuditLog`` stores neither and this module may not query the tables that do. The actor
    is the opaque user id recorded at the time, alongside the role they *then* held: roles
    change, and the trail must show the authority someone acted under, not today's.

    Three fields are deliberately absent. ``patientId`` is the caller, constant for every
    row in the listing and never part of this API's public vocabulary (a patient is public
    as their Health ID). ``requestContext`` is the ``X-Request-Id`` correlation key, which
    is client-supplied diagnostics rather than a fact about the patient's care. ``createdAt``
    is the row's storage instant, which exists to be compared with ``occurredAt`` during a
    tamper investigation, not to be shown twice in a timeline.

    Exactly one target is set per action — a record for a read, a category for a consent
    decision, a request for one being raised — so all three are nullable. The category is
    given as its code, never its internal id: that is the vocabulary the whole API speaks.

    ``eventHash`` is the tamper-evidence digest ADR-004 anchors on-chain (hashes only, never
    identifiers or PHI), published here so the owner of the trail can verify it. The digest
    algorithm changes to keccak256 at M6 (ADR-019), so it identifies an event's *content*,
    not the event: do not treat it as a stable key.
    """

    id: UUID
    action: AuditAction
    actor_user_id: UUID
    actor_role: Role
    #: The actor's display identity when they are hospital staff. Null for the patient's
    #: own actions — ``actorRole`` already says so — and for any account this module knows
    #: no name for.
    actor: StaffDisplayResponse | None
    target_record_id: UUID | None
    target_category_code: str | None
    target_request_id: UUID | None
    occurred_at: datetime
    event_hash: str


class AuditEventListResponse(ApiModel):
    items: list[AuditEventResponse]
    next_cursor: str | None


class DecisionOutcomeResponse(ApiModel):
    """What one approve or reject call produced. ``grants`` is empty for a rejection, and
    ``requestStatus`` becomes ``DECIDED`` once every requested category has an answer."""

    request_id: UUID
    request_status: ConsentRequestStatus
    decisions: list[ConsentDecisionResponse]
    grants: list[ConsentGrantResponse]
