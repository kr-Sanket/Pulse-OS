"""consent endpoints (M3): access requests, the patient's inbox, per-category decisions,
and grant revocation.

Conventions per docs/API_GUIDELINES.md throughout: ``/api/v1`` base, plural kebab-case
resource nouns (the guideline names ``/access-requests`` and ``/consent-grants``
explicitly), verb sub-resources for actions that are not CRUD, cursor pagination, and
RFC 7807 problem responses. Role gates are declared per route (ADR-013 layer 1); the
relationship checks (is this *your* request, *your* grant) are the service's, and they
answer 404 rather than 403 so existence never leaks.

Routers stay thin: parse, translate category codes into ids, delegate, map domain errors
through ``dependencies.to_http_error``. No handler queries anything or decides anything —
including the state a grant is in, which the service reads from its own clock.
"""

from collections.abc import Mapping, Sequence
from http import HTTPStatus
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.core.errors import problem_response
from app.modules.auth.dependencies import (
    RequireDoctor,
    RequireHospitalAdmin,
    RequirePatient,
    rate_limited,
)
from app.modules.auth.domain import AuthenticatedUser
from app.modules.consent.anchor_service import IntegrityReport, IntegrityStatus
from app.modules.consent.dependencies import (
    PROBLEM,
    AuditAnchorServiceDep,
    AuditBatchServiceDep,
    CategoryVocabulary,
    CategoryVocabularyDep,
    ConsentServiceDep,
    RequestContextDep,
    ResponseSpec,
    parse_cursor,
    resolve_category_codes,
    to_http_error,
)
from app.modules.consent.errors import (
    AuditBatchNotFoundError,
    AuditProofNotFoundError,
    ConsentError,
    RequestNotDecidableError,
)
from app.modules.consent.models import ConsentGrant
from app.modules.consent.schemas import (
    AccessRequestCreateRequest,
    AccessRequestListItemResponse,
    AccessRequestListResponse,
    AccessRequestResponse,
    AuditBatchFindingResponse,
    AuditBatchResponse,
    AuditEventListResponse,
    AuditEventProofResponse,
    AuditEventResponse,
    AuditEventVerificationResponse,
    AuditHospitalResponse,
    AuditIntegrityResponse,
    CategorySelectionRequest,
    ConsentDecisionResponse,
    ConsentGrantListItemResponse,
    ConsentGrantListResponse,
    ConsentGrantResponse,
    DecisionOutcomeResponse,
    HospitalAuditEventListResponse,
    HospitalAuditEventResponse,
    MerkleProofResponse,
    ProofStepResponse,
    SentAccessRequestListResponse,
    SentAccessRequestResponse,
    StaffDisplayResponse,
)
from app.modules.consent.service import (
    AuditPage,
    AuditView,
    DecisionOutcome,
    GrantPage,
    GrantView,
    OrganizationDisplay,
    PersonDisplay,
    RequestPage,
    RequestView,
)
from app.shared.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

access_requests_router = APIRouter(prefix="/access-requests", tags=["consent"])
consent_grants_router = APIRouter(prefix="/consent-grants", tags=["consent"])
# Plural kebab-case after the table it serves (docs/API_GUIDELINES.md), alongside its
# siblings: the trail is consent-owned, so it is this module's surface, not a new one.
audit_logs_router = APIRouter(prefix="/audit-logs", tags=["consent"])
# The hospital's view of the same trail (ADR-023). Mounted under /hospitals/me because the
# scope is the caller's own hospital and the URL should say so — the `/hospitals` prefix is
# otherwise the records module's, and ownership of the *data* decides the module while the
# URL only decides the shape (the rule ADR-020 set).
hospital_audit_logs_router = APIRouter(prefix="/hospitals/me/audit-logs", tags=["hospitals"])
# Read-only verification of sealed Merkle batches against the database (ADR-027).
audit_batches_router = APIRouter(prefix="/audit-batches", tags=["audit"])

PatientUser = Annotated[AuthenticatedUser, Depends(RequirePatient)]
HospitalAdminUser = Annotated[AuthenticatedUser, Depends(RequireHospitalAdmin)]
DoctorUser = Annotated[AuthenticatedUser, Depends(RequireDoctor)]

_UNAUTHENTICATED: ResponseSpec = {
    401: {"description": "Missing or invalid credentials", "content": PROBLEM}
}
_WRONG_ROLE: ResponseSpec = {403: {"description": "Role not permitted", "content": PROBLEM}}
_NO_PROFILE: ResponseSpec = {
    404: {"description": "No profile for this account", "content": PROBLEM}
}
_INVALID: ResponseSpec = {422: {"description": "Validation failed", "content": PROBLEM}}
#: Declared only on rate-limited routes (ADR-024), so the spec says which they are.
_RATE_LIMITED: ResponseSpec = {429: {"description": "Rate limit exceeded", "content": PROBLEM}}


def _to_staff_display(person: PersonDisplay | None) -> StaffDisplayResponse | None:
    """The single place a projected identity becomes wire shape. Every listing that names
    somebody goes through here, so "what a patient may see of staff" is one decision."""
    if person is None:
        return None
    return StaffDisplayResponse(
        full_name=person.full_name,
        specialty=person.specialty,
        hospital_name=person.hospital_name,
    )


def _to_response(view: RequestView, vocabulary: CategoryVocabulary) -> AccessRequestResponse:
    request = view.request
    return AccessRequestResponse(
        id=request.id,
        status=view.status,
        purpose=request.purpose,
        category_codes=[
            vocabulary.by_id[category_id] for category_id in view.requested_category_ids
        ],
        requester_doctor_id=request.requester_doctor_id,
        requester_hospital_id=request.requester_hospital_id,
        expires_at=request.expires_at,
        created_at=request.created_at,
    )


def _to_request_list_item(
    view: RequestView, vocabulary: CategoryVocabulary
) -> AccessRequestListItemResponse:
    """The same projection as a single request, plus who asked — built from that projection
    rather than beside it, so the two cannot drift."""
    return AccessRequestListItemResponse(
        **_to_response(view, vocabulary).model_dump(),
        requester=_to_staff_display(view.requester),
        requester_hospital_name=view.requester_hospital_name,
    )


def _to_sent_list_response(
    page: RequestPage, vocabulary: CategoryVocabulary
) -> SentAccessRequestListResponse:
    """The requester's own listing: the shared item projection plus the subject.

    ``patient_health_id`` is indexed rather than defaulted — the service populates it for
    every row of this listing, and ``consent_requests.patient_id`` is a NOT NULL foreign
    key to a table whose rows are never deleted, so a missing entry is a corrupt database,
    not a case to paper over. The category vocabulary is indexed the same way above.
    """
    return SentAccessRequestListResponse(
        items=[
            SentAccessRequestResponse(
                **_to_request_list_item(view, vocabulary).model_dump(),
                patient_health_id=_required_health_id(view),
            )
            for view in page.items
        ],
        next_cursor=page.next_cursor,
    )


def _required_health_id(view: RequestView) -> str:
    health_id = view.patient_health_id
    if health_id is None:
        raise KeyError("sent listing built without a patient Health ID")
    return health_id


def _to_list_response(
    page: RequestPage, vocabulary: CategoryVocabulary
) -> AccessRequestListResponse:
    return AccessRequestListResponse(
        items=[_to_request_list_item(view, vocabulary) for view in page.items],
        next_cursor=page.next_cursor,
    )


def _to_outcome_response(
    outcome: DecisionOutcome, vocabulary: CategoryVocabulary
) -> DecisionOutcomeResponse:
    return DecisionOutcomeResponse(
        request_id=outcome.request.id,
        request_status=outcome.request.status,
        decisions=[
            ConsentDecisionResponse(
                id=decision.id,
                category_code=vocabulary.by_id[decision.category_id],
                status=decision.status,
                decided_at=decision.created_at,
            )
            for decision in outcome.decisions
        ],
        grants=[_to_grant_response(grant, vocabulary) for grant in outcome.grants],
    )


def _to_grant_response(grant: ConsentGrant, vocabulary: CategoryVocabulary) -> ConsentGrantResponse:
    return ConsentGrantResponse(
        id=grant.id,
        category_code=vocabulary.by_id[grant.category_id],
        grantee_doctor_id=grant.grantee_doctor_id,
        granted_at=grant.created_at,
        expires_at=grant.expires_at,
        revoked_at=grant.revoked_at,
    )


def _to_grant_list_item(
    view: GrantView, vocabulary: CategoryVocabulary
) -> ConsentGrantListItemResponse:
    """The same projection as a single grant, plus the state the service read for it —
    built from that projection rather than beside it, so the two cannot drift."""
    return ConsentGrantListItemResponse(
        **_to_grant_response(view.grant, vocabulary).model_dump(),
        status=view.state,
        grantee=_to_staff_display(view.grantee),
    )


def _to_audit_response(
    view: AuditView, vocabulary: CategoryVocabulary, integrity: IntegrityReport
) -> AuditEventResponse:
    """Straight projection of the row, plus the actor's name where the service resolved one.
    The one translation is the category, which the API addresses by code everywhere — the
    same swap every other response here performs. ``integrity`` is resolved for the whole
    page at once (ADR-026), never per row."""
    entry = view.entry
    category_id = entry.target_category_id
    return AuditEventResponse(
        integrity=AuditIntegrityResponse.from_report(integrity),
        id=entry.id,
        action=entry.action,
        actor_user_id=entry.actor_user_id,
        actor_role=entry.actor_role,
        target_record_id=entry.target_record_id,
        target_category_code=None if category_id is None else vocabulary.by_id[category_id],
        target_request_id=entry.target_request_id,
        occurred_at=entry.occurred_at,
        event_hash=entry.event_hash,
        actor=_to_staff_display(view.actor),
        actor_hospital=_to_audit_hospital(view.hospital),
    )


def _to_audit_hospital(hospital: OrganizationDisplay | None) -> AuditHospitalResponse | None:
    """The historical attribution, or nothing. Never falls back to the actor's current
    hospital: an absent attribution is the truthful answer for a patient's own action and
    for every event written before migration 0005 (ADR-025)."""
    if hospital is None:
        return None
    return AuditHospitalResponse(hid=hospital.hid, name=hospital.name)


def _to_hospital_audit_list_response(page: AuditPage) -> HospitalAuditEventListResponse:
    """The hospital projection: no patient id, no hash, no clinical fact (see the schema)."""
    return HospitalAuditEventListResponse(
        items=[
            HospitalAuditEventResponse(
                id=view.entry.id,
                action=view.entry.action,
                actor_user_id=view.entry.actor_user_id,
                actor_role=view.entry.actor_role,
                actor=_to_staff_display(view.actor),
                target_record_id=view.entry.target_record_id,
                occurred_at=view.entry.occurred_at,
            )
            for view in page.items
        ],
        next_cursor=page.next_cursor,
    )


def _to_audit_list_response(
    page: AuditPage,
    vocabulary: CategoryVocabulary,
    integrity: Mapping[UUID, IntegrityReport],
) -> AuditEventListResponse:
    return AuditEventListResponse(
        items=[
            _to_audit_response(view, vocabulary, integrity[view.entry.id]) for view in page.items
        ],
        next_cursor=page.next_cursor,
    )


def _to_grant_list_response(
    page: GrantPage, vocabulary: CategoryVocabulary
) -> ConsentGrantListResponse:
    return ConsentGrantListResponse(
        items=[_to_grant_list_item(view, vocabulary) for view in page.items],
        next_cursor=page.next_cursor,
    )


@access_requests_router.post(
    "",
    status_code=201,
    response_model=AccessRequestResponse,
    responses={
        **_UNAUTHENTICATED,
        403: {"description": "Not a doctor, or the clinician is not active", "content": PROBLEM},
        **_NO_PROFILE,
        409: {
            "description": "A category is already actively granted, or already asked for on "
            "an open request",
            "content": PROBLEM,
        },
        **_INVALID,
        **_RATE_LIMITED,
    },
)
async def create_access_request(
    body: AccessRequestCreateRequest,
    user: DoctorUser,
    _limit: Annotated[AuthenticatedUser, Depends(rate_limited("access_request_create"))],
    service: ConsentServiceDep,
    vocabulary: CategoryVocabularyDep,
    request_context: RequestContextDep,
) -> AccessRequestResponse:
    """Ask a patient for access to a set of record categories.

    Roles: DOCTOR, and the clinician profile must be ACTIVE at its hospital (ADR-015).
    Consent requirement: none — this *asks* for consent, it reads nothing.
    Duplicates are refused with 409, before anything is written: a category this clinician
    already holds an active grant for, or one already asked for on an open (PENDING,
    unexpired) request of theirs to the same patient that has not yet been answered for it.
    Failure modes: 401, 403 (wrong role or inactive clinician), 404 (no clinician profile),
    409 (duplicate, as above), 422 (validation, unknown Health ID, unknown category code).
    """
    try:
        view = await service.create_request(
            user,
            patient_health_id=body.patient_health_id,
            category_ids=resolve_category_codes(vocabulary, body.category_codes),
            purpose=body.purpose,
            request_context=request_context,
        )
    except ConsentError as exc:
        raise to_http_error(exc) from exc
    return _to_response(view, vocabulary)


@access_requests_router.get(
    "/inbox",
    response_model=AccessRequestListResponse,
    responses={**_UNAUTHENTICATED, **_WRONG_ROLE, **_NO_PROFILE, **_INVALID},
)
async def list_inbox(
    user: PatientUser,
    service: ConsentServiceDep,
    vocabulary: CategoryVocabularyDep,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> AccessRequestListResponse:
    """The patient's consent inbox: requests naming them, newest first.

    Roles: PATIENT (own inbox only — the scope comes from the token, never from a
    parameter). Consent requirement: none; a request is not record content.
    Failure modes: 401, 403, 404 (no patient profile), 422 (bad cursor or limit).
    """
    try:
        page = await service.list_inbox(user, after=parse_cursor(cursor), limit=limit)
    except ConsentError as exc:
        raise to_http_error(exc) from exc
    return _to_list_response(page, vocabulary)


@access_requests_router.get(
    "/sent",
    response_model=SentAccessRequestListResponse,
    responses={**_UNAUTHENTICATED, **_WRONG_ROLE, **_NO_PROFILE, **_INVALID},
)
async def list_sent_requests(
    user: DoctorUser,
    service: ConsentServiceDep,
    vocabulary: CategoryVocabularyDep,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> SentAccessRequestListResponse:
    """The clinician's own outgoing requests, newest first.

    Each row names its subject by Health ID — the identifier the clinician supplied to raise
    the request — because a listing of one's own requests is unreadable without knowing who
    each one is about. Nothing else off the patient row is exposed.

    Roles: DOCTOR (own requests only). A non-ACTIVE clinician may still read this: seeing
    what you asked for is not a clinical capability. The response reports status only —
    what may actually be read is answered per read by the enforcement check, never by a
    listing. Consent requirement: none.
    Failure modes: 401, 403, 404 (no clinician profile), 422 (bad cursor or limit).
    """
    try:
        page = await service.list_sent_requests(user, after=parse_cursor(cursor), limit=limit)
    except ConsentError as exc:
        raise to_http_error(exc) from exc
    return _to_sent_list_response(page, vocabulary)


@access_requests_router.post(
    "/{request_id}/approve",
    response_model=DecisionOutcomeResponse,
    responses={
        **_UNAUTHENTICATED,
        **_WRONG_ROLE,
        404: {"description": "No such request for this patient", "content": PROBLEM},
        409: {
            "description": "Request closed, category already answered, or category already "
            "actively granted",
            "content": PROBLEM,
        },
        **_INVALID,
    },
)
async def approve_categories(
    request: Request,
    request_id: UUID,
    body: CategorySelectionRequest,
    user: PatientUser,
    service: ConsentServiceDep,
    vocabulary: CategoryVocabularyDep,
    request_context: RequestContextDep,
) -> DecisionOutcomeResponse | JSONResponse:
    """Approve some of the categories an access request asked for.

    Each approval is recorded permanently and produces the grant that enforcement reads.
    Roles: PATIENT, and only for their own request — another patient's request answers 404,
    never 403. Consent requirement: this *is* the consent decision.
    Failure modes: 401, 403, 404, 409 (request expired/decided/cancelled, a category
    already answered, or a category this clinician already holds an active grant for),
    422 (unknown code, or a category this request never asked for).
    """
    return await _decide(
        request,
        service.approve_categories,
        request_id,
        body,
        user,
        service,
        vocabulary,
        request_context,
    )


@access_requests_router.post(
    "/{request_id}/reject",
    response_model=DecisionOutcomeResponse,
    responses={
        **_UNAUTHENTICATED,
        **_WRONG_ROLE,
        404: {"description": "No such request for this patient", "content": PROBLEM},
        409: {"description": "Request closed, or category already answered", "content": PROBLEM},
        **_INVALID,
    },
)
async def reject_categories(
    request: Request,
    request_id: UUID,
    body: CategorySelectionRequest,
    user: PatientUser,
    service: ConsentServiceDep,
    vocabulary: CategoryVocabularyDep,
    request_context: RequestContextDep,
) -> DecisionOutcomeResponse | JSONResponse:
    """Refuse some of the categories an access request asked for.

    A rejection is recorded as permanently as an approval and grants nothing, so it never
    meets the "already actively granted" conflict an approval can.
    Roles: PATIENT, and only for their own request — another patient's request answers 404,
    never 403. Consent requirement: this *is* the consent decision.
    Failure modes: 401, 403, 404, 409 (request expired/decided/cancelled, or a category
    already answered), 422 (unknown code, or a category this request never asked for).
    """
    return await _decide(
        request,
        service.reject_categories,
        request_id,
        body,
        user,
        service,
        vocabulary,
        request_context,
    )


class _DecisionOperation(Protocol):
    """Approve and reject share a call shape; this is it, so the helper below stays typed."""

    async def __call__(
        self,
        caller: AuthenticatedUser,
        request_id: UUID,
        category_ids: Sequence[UUID],
        *,
        request_context: str | None = None,
    ) -> DecisionOutcome: ...


async def _decide(
    http_request: Request,
    operation: _DecisionOperation,
    request_id: UUID,
    body: CategorySelectionRequest,
    user: AuthenticatedUser,
    service: ConsentServiceDep,
    vocabulary: CategoryVocabulary,
    request_context: str | None,
) -> DecisionOutcomeResponse | JSONResponse:
    """Approve and reject differ only in which service method runs, so they share this.

    A request that is no longer decidable is the one refusal **returned rather than
    raised** (the ADR-017 technique). The service raises it before any decision, grant,
    audit row or notification is written; the only state it may leave pending is the
    request's own lazy PENDING → EXPIRED transition. Raising would roll that back and leave
    an expired request stored as PENDING; returning lets the request transaction commit it.
    Same status and problem+json body either way. Every other failure keeps raising, so a
    partially applied decision still rolls back.
    """
    try:
        outcome = await operation(
            user,
            request_id,
            resolve_category_codes(vocabulary, body.category_codes),
            request_context=request_context,
        )
    except RequestNotDecidableError as exc:
        http_error = to_http_error(exc)
        return problem_response(
            http_request,
            status_code=http_error.status_code,
            title=HTTPStatus(http_error.status_code).phrase,
            detail=http_error.detail if isinstance(http_error.detail, str) else None,
        )
    except ConsentError as exc:
        raise to_http_error(exc) from exc
    return _to_outcome_response(outcome, vocabulary)


@consent_grants_router.get(
    "",
    response_model=ConsentGrantListResponse,
    responses={**_UNAUTHENTICATED, **_WRONG_ROLE, **_NO_PROFILE, **_INVALID},
)
async def list_grants(
    user: PatientUser,
    service: ConsentServiceDep,
    vocabulary: CategoryVocabularyDep,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> ConsentGrantListResponse:
    """Every grant ever derived for the patient, newest first, each with its current state.

    The patient's own history, revoked and expired grants included: who may read their
    records today is only half the question this page answers, and access that has been
    withdrawn is a fact its owner is entitled to keep seeing. ``status`` distinguishes the
    three cases, read from the server's clock with the predicate enforcement uses, so a
    client never has to judge expiry itself.

    Roles: PATIENT (own grants only — the scope comes from the token, never a parameter; a
    grantee clinician has no listing here, by design). Consent requirement: none, a grant
    is not record content. Reading one's own consent state is not an access event, so
    nothing is audited — the trail records grants being created and revoked, which is where
    a change to who can read anything actually happens.
    Failure modes: 401, 403, 404 (no patient profile), 422 (bad cursor or limit).
    """
    try:
        page = await service.list_grants(user, after=parse_cursor(cursor), limit=limit)
    except ConsentError as exc:
        raise to_http_error(exc) from exc
    return _to_grant_list_response(page, vocabulary)


@consent_grants_router.post(
    "/{grant_id}/revoke",
    response_model=ConsentGrantResponse,
    responses={
        **_UNAUTHENTICATED,
        **_WRONG_ROLE,
        404: {"description": "No such grant for this patient", "content": PROBLEM},
    },
)
async def revoke_grant(
    grant_id: UUID,
    user: PatientUser,
    service: ConsentServiceDep,
    vocabulary: CategoryVocabularyDep,
    request_context: RequestContextDep,
) -> ConsentGrantResponse:
    """Withdraw a grant. Takes effect for the very next read — no cache, no grace period.

    Idempotent: revoking an already-revoked grant returns it unchanged.
    Roles: PATIENT, and only their own grant — another patient's answers 404.
    Consent requirement: this *is* the consent decision. Failure modes: 401, 403, 404.
    """
    try:
        grant = await service.revoke_grant(user, grant_id, request_context=request_context)
    except ConsentError as exc:
        raise to_http_error(exc) from exc
    return _to_grant_response(grant, vocabulary)


@audit_logs_router.get(
    "",
    response_model=AuditEventListResponse,
    responses={**_UNAUTHENTICATED, **_WRONG_ROLE, **_NO_PROFILE, **_INVALID},
)
async def list_audit_events(
    user: PatientUser,
    service: ConsentServiceDep,
    anchors: AuditAnchorServiceDep,
    vocabulary: CategoryVocabularyDep,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> AuditEventListResponse:
    """The patient's own audit trail, most recent event first.

    Every consent decision, revocation and record access concerning this patient, refusals
    included — the append-only log is what makes the platform's promise checkable by the
    person it is about. Ordered and paginated on the application-assigned event time, which
    is also the value the tamper-evidence hash covers.

    Roles: PATIENT (own trail only — the scope comes from the token, never a parameter; no
    clinician or administrator reads a patient's log through this API). Consent requirement:
    none, an audit entry is not record content, and it names no file, date or description.
    Reading the trail is not itself an audited event.
    Failure modes: 401, 403, 404 (no patient profile), 422 (bad cursor or limit).
    """
    try:
        page = await service.list_audit_events(user, after=parse_cursor(cursor), limit=limit)
    except ConsentError as exc:
        raise to_http_error(exc) from exc
    # One anchor query for the page, then a comparison per row (ADR-026) — the listing costs
    # one extra statement whether it shows one event or twenty-five.
    integrity = await anchors.verify_many([view.entry for view in page.items])
    return _to_audit_list_response(page, vocabulary, integrity)


@audit_logs_router.get(
    "/{audit_log_id}/verification",
    response_model=AuditEventVerificationResponse,
    responses={
        **_UNAUTHENTICATED,
        **_WRONG_ROLE,
        404: {"description": "No such audit event for this patient", "content": PROBLEM},
    },
)
async def verify_audit_event(
    audit_log_id: UUID,
    user: PatientUser,
    anchors: AuditAnchorServiceDep,
) -> AuditEventVerificationResponse:
    """Check one entry of the caller's own trail against its blockchain anchor (ADR-026).

    Three stored copies are compared: the digest recomputed from the event's own columns,
    the digest recorded on the event, and the digest recorded on the anchor when it was
    published. ``VERIFIED`` means all three agree and the anchor's reference is the one this
    network produces for that digest. ``EVENT_ALTERED`` means the event no longer matches
    what was anchored; ``ANCHOR_ALTERED`` means the anchor row does not match its own
    network; ``NOT_ANCHORED`` means no anchor exists yet and says nothing about integrity.

    **This grants no new visibility.** The event is resolved under the caller's patient
    scope, so an entry belonging to somebody else answers 404 exactly as a nonexistent one
    does; a patient can verify only what they could already read in their own trail. The
    response carries no digest and no hashed payload — only the verdict and the two facts
    that make an anchor checkable, its network and its transaction reference.

    There is deliberately no endpoint for anchoring, and none for verifying an arbitrary
    hash: anchoring is an operator sweep (``scripts/anchor_audit_events.py``), and a public
    "verify this digest" surface would be an oracle for guessing audit content.

    Roles: PATIENT (own trail only). Consent requirement: none — a verdict is not record
    content. Reading it is not itself an audited event, as with the listing.
    Failure modes: 401, 403, 404 (no such event for this caller), 422 (malformed id).
    """
    try:
        report = await anchors.verify_for_caller(user, audit_log_id)
    except ConsentError as exc:
        raise to_http_error(exc) from exc
    return AuditEventVerificationResponse.from_report(report)


@audit_logs_router.get(
    "/{audit_log_id}/proof",
    response_model=AuditEventProofResponse,
    responses={
        **_UNAUTHENTICATED,
        **_WRONG_ROLE,
        404: {"description": "No such audit event or proof for this patient", "content": PROBLEM},
    },
)
async def get_audit_event_proof(
    audit_log_id: UUID,
    user: PatientUser,
    anchors: AuditAnchorServiceDep,
    batches: AuditBatchServiceDep,
) -> AuditEventProofResponse:
    """Get the cryptographic Merkle membership proof for an entry of the caller's trail (ADR-027).

    Proves that this audit record is a committed leaf in an immutable Merkle batch.
    Re-verifies the proof against the batch's root and recomputes the event digest.
    Contains zero PHI.

    Roles: PATIENT (own trail only). Enforces patient isolation: another patient's
    event answers 404.
    Failure modes: 401, 403, 404 (no such event for this caller, or unbatched event),
    422 (malformed id).
    """
    try:
        report = await anchors.verify_for_caller(user, audit_log_id)
    except ConsentError as exc:
        raise to_http_error(exc) from exc

    proof_res = await batches.get_proof_for_event(audit_log_id)
    if proof_res is None:
        raise to_http_error(AuditProofNotFoundError())

    # Patient isolation is enforced by anchors.verify_for_caller (404 for other patients).
    # batches.get_proof_for_event generates and verifies the Merkle inclusion proof.
    # Primary-key lookups hit SQLAlchemy's session identity map.
    #
    # Incorporate both event digest validity and cryptographic Merkle proof validity:
    # never return status=VERIFIED if is_proof_valid or is_event_valid is false.
    # VERIFIED only when the proof path and the event's own verdict both say so; otherwise
    # the worse of the two, so this surface can never disagree with the list or detail one.
    if not proof_res.is_event_valid or report.status is IntegrityStatus.EVENT_ALTERED:
        final_status = IntegrityStatus.EVENT_ALTERED
    elif not proof_res.is_proof_valid or report.status is not IntegrityStatus.VERIFIED:
        final_status = IntegrityStatus.ANCHOR_ALTERED
    else:
        final_status = IntegrityStatus.VERIFIED

    return AuditEventProofResponse(
        audit_log_id=proof_res.audit_log_id,
        status=final_status,
        batch_number=proof_res.batch_number,
        batch_id=proof_res.batch_id,
        leaf_index=proof_res.leaf_index,
        leaf_count=proof_res.leaf_count,
        root=proof_res.root,
        commitment=proof_res.commitment,
        event_digest=proof_res.event_digest,
        recomputed_digest=proof_res.recomputed_digest,
        is_event_valid=proof_res.is_event_valid,
        is_proof_valid=proof_res.is_proof_valid,
        proof_steps_count=proof_res.proof_steps_count,
        proof=(
            MerkleProofResponse(
                leaf_index=proof_res.proof.leaf_index,
                leaf_count=proof_res.proof.leaf_count,
                steps=[
                    ProofStepResponse(
                        sibling=s.sibling,
                        sibling_on_left=s.sibling_on_left,
                    )
                    for s in proof_res.proof.steps
                ],
            )
            if proof_res.proof is not None
            else None
        ),
    )


@hospital_audit_logs_router.get("", response_model=HospitalAuditEventListResponse)
async def list_hospital_audit_events(
    user: HospitalAdminUser,
    service: ConsentServiceDep,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> HospitalAuditEventListResponse:
    """This hospital's own activity on the append-only trail, most recent event first.

    The organisation's view of the log the patient reads: every upload, read, download and
    refusal its staff generated, and every access request its clinicians raised. Ordered and
    paginated on the application-assigned event time.

    Roles: HOSPITAL_ADMIN. **The scope is the caller's own hospital, derived server-side
    from their admin profile — there is no hospital parameter, so no administrator can read
    another hospital's activity by changing a query string.** Attribution is the
    ``actor_hospital_id`` recorded when each event was written (ADR-023), never the actor's
    present affiliation, so a clinician who transfers hospitals leaves their history behind.

    Discloses the action, when it happened, who did it and which record it concerned — and
    deliberately no patient identifier, no tamper-evidence digest and no clinical fact: this
    answers "what has my hospital done", not "who are my hospital's patients".

    Two absences are expected rather than faults: patient-actor events have no hospital and
    never appear here, and events written before migration 0005 carry no attribution, so a
    hospital's log begins at that migration. Reading the trail is not itself audited.

    Consent requirement: none — an audit entry is not record content.
    Failure modes: 401, 403 (wrong role), 404 (no hospital-admin profile), 422 (bad cursor
    or limit).
    """
    try:
        page = await service.list_hospital_audit_events(
            user, after=parse_cursor(cursor), limit=limit
        )
    except ConsentError as exc:
        raise to_http_error(exc) from exc
    return _to_hospital_audit_list_response(page)


@audit_batches_router.get(
    "/{batch_number}",
    response_model=AuditBatchResponse,
    responses={
        **_UNAUTHENTICATED,
        404: {"description": "Audit batch not found", "content": PROBLEM},
        **_INVALID,
        **_RATE_LIMITED,
    },
)
async def verify_audit_batch(
    batch_number: int,
    user: Annotated[AuthenticatedUser, Depends(rate_limited("audit_batch_verify"))],
    batches: AuditBatchServiceDep,
) -> AuditBatchResponse:
    """Independently verify a sealed Merkle batch against the database (ADR-027).

    Recomputes the domain-separated Merkle root and Keccak commitment from the batch's
    members and compares them with persisted values. Reports any tampering or inconsistencies.
    Contains zero PHI and zero patient identifiers.

    Roles: Any authenticated user (PATIENT, DOCTOR, HOSPITAL_ADMIN, SYSTEM_ADMIN) — batch
    roots and commitments are public-by-design attestation material. Rate limited
    (``audit_batch_verify``, ADR-024) because each call recomputes the whole batch.
    Findings may name an ``audit_log_id`` (an opaque UUID, never content or a patient id).
    Failure modes: 401, 404 (no such batch), 422 (batch_number < 1), 429.
    """
    del user  # auth + rate-limit gate guarantees an authenticated, unthrottled caller
    if batch_number < 1:
        raise HTTPException(status_code=422, detail="batch_number must be at least 1")
    res = await batches.verify_batch(batch_number)
    if res is None:
        raise to_http_error(AuditBatchNotFoundError())
    return AuditBatchResponse(
        batch_number=res.batch_number,
        batch_id=res.batch_id,
        protocol_version=res.protocol_version,
        hash_version=res.hash_version,
        leaf_count=res.leaf_count,
        root=res.root,
        commitment=res.commitment,
        first_occurred_at=res.first_occurred_at,
        last_occurred_at=res.last_occurred_at,
        is_valid=res.is_valid,
        status="VALID" if res.is_valid else "TAMPERED",
        findings=[
            AuditBatchFindingResponse(
                kind=f.kind.value,
                batch_number=f.batch_number,
                audit_log_id=f.audit_log_id,
            )
            for f in res.findings
        ],
    )
