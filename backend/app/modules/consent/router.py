"""consent endpoints (M3): access requests, the patient's inbox, per-category decisions,
and grant revocation.

Conventions per docs/API_GUIDELINES.md throughout: ``/api/v1`` base, plural kebab-case
resource nouns (the guideline names ``/access-requests`` and ``/consent-grants``
explicitly), verb sub-resources for actions that are not CRUD, cursor pagination, and
RFC 7807 problem responses. Role gates are declared per route (ADR-013 layer 1); the
relationship checks (is this *your* request, *your* grant) are the service's, and they
answer 404 rather than 403 so existence never leaks.

Routers stay thin: parse, translate category codes into ids, delegate, map domain errors
through ``dependencies.to_http_error``. No handler queries anything or decides anything.

Nothing here is mounted in ``app.main`` yet, and the records read path does not call
``consent.enforce`` yet — both land with the integration task.
"""

from collections.abc import Sequence
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.modules.auth.dependencies import RequireDoctor, RequirePatient
from app.modules.auth.domain import AuthenticatedUser
from app.modules.consent.dependencies import (
    PROBLEM,
    CategoryVocabulary,
    CategoryVocabularyDep,
    ConsentServiceDep,
    RequestContextDep,
    ResponseSpec,
    parse_cursor,
    resolve_category_codes,
    to_http_error,
)
from app.modules.consent.errors import ConsentError
from app.modules.consent.models import ConsentGrant
from app.modules.consent.schemas import (
    AccessRequestCreateRequest,
    AccessRequestListResponse,
    AccessRequestResponse,
    CategorySelectionRequest,
    ConsentDecisionResponse,
    ConsentGrantResponse,
    DecisionOutcomeResponse,
)
from app.modules.consent.service import DecisionOutcome, RequestPage, RequestView
from app.shared.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

access_requests_router = APIRouter(prefix="/access-requests", tags=["consent"])
consent_grants_router = APIRouter(prefix="/consent-grants", tags=["consent"])

PatientUser = Annotated[AuthenticatedUser, Depends(RequirePatient)]
DoctorUser = Annotated[AuthenticatedUser, Depends(RequireDoctor)]

_UNAUTHENTICATED: ResponseSpec = {
    401: {"description": "Missing or invalid credentials", "content": PROBLEM}
}
_WRONG_ROLE: ResponseSpec = {403: {"description": "Role not permitted", "content": PROBLEM}}
_NO_PROFILE: ResponseSpec = {
    404: {"description": "No profile for this account", "content": PROBLEM}
}
_INVALID: ResponseSpec = {422: {"description": "Validation failed", "content": PROBLEM}}


def _to_response(view: RequestView, vocabulary: CategoryVocabulary) -> AccessRequestResponse:
    request = view.request
    return AccessRequestResponse(
        id=request.id,
        status=request.status,
        purpose=request.purpose,
        category_codes=[
            vocabulary.by_id[category_id] for category_id in view.requested_category_ids
        ],
        requester_doctor_id=request.requester_doctor_id,
        requester_hospital_id=request.requester_hospital_id,
        expires_at=request.expires_at,
        created_at=request.created_at,
    )


def _to_list_response(
    page: RequestPage, vocabulary: CategoryVocabulary
) -> AccessRequestListResponse:
    return AccessRequestListResponse(
        items=[_to_response(view, vocabulary) for view in page.items],
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


@access_requests_router.post(
    "",
    status_code=201,
    response_model=AccessRequestResponse,
    responses={
        **_UNAUTHENTICATED,
        403: {"description": "Not a doctor, or the clinician is not active", "content": PROBLEM},
        **_NO_PROFILE,
        **_INVALID,
    },
)
async def create_access_request(
    body: AccessRequestCreateRequest,
    user: DoctorUser,
    service: ConsentServiceDep,
    vocabulary: CategoryVocabularyDep,
    request_context: RequestContextDep,
) -> AccessRequestResponse:
    """Ask a patient for access to a set of record categories.

    Roles: DOCTOR, and the clinician profile must be ACTIVE at its hospital (ADR-015).
    Consent requirement: none — this *asks* for consent, it reads nothing.
    Failure modes: 401, 403 (wrong role or inactive clinician), 404 (no clinician profile),
    422 (validation, unknown Health ID, unknown category code).
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
    response_model=AccessRequestListResponse,
    responses={**_UNAUTHENTICATED, **_WRONG_ROLE, **_NO_PROFILE, **_INVALID},
)
async def list_sent_requests(
    user: DoctorUser,
    service: ConsentServiceDep,
    vocabulary: CategoryVocabularyDep,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> AccessRequestListResponse:
    """The clinician's own outgoing requests, newest first.

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
    return _to_list_response(page, vocabulary)


@access_requests_router.post(
    "/{request_id}/approve",
    response_model=DecisionOutcomeResponse,
    responses={
        **_UNAUTHENTICATED,
        **_WRONG_ROLE,
        404: {"description": "No such request for this patient", "content": PROBLEM},
        409: {"description": "Request closed, or category already answered", "content": PROBLEM},
        **_INVALID,
    },
)
async def approve_categories(
    request_id: UUID,
    body: CategorySelectionRequest,
    user: PatientUser,
    service: ConsentServiceDep,
    vocabulary: CategoryVocabularyDep,
    request_context: RequestContextDep,
) -> DecisionOutcomeResponse:
    """Approve some of the categories an access request asked for.

    Each approval is recorded permanently and produces the grant that enforcement reads.
    Roles: PATIENT, and only for their own request — another patient's request answers 404,
    never 403. Consent requirement: this *is* the consent decision.
    Failure modes: 401, 403, 404, 409 (request expired/decided/cancelled, or a category
    already answered), 422 (unknown code, or a category this request never asked for).
    """
    return await _decide(
        service.approve_categories, request_id, body, user, service, vocabulary, request_context
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
    request_id: UUID,
    body: CategorySelectionRequest,
    user: PatientUser,
    service: ConsentServiceDep,
    vocabulary: CategoryVocabularyDep,
    request_context: RequestContextDep,
) -> DecisionOutcomeResponse:
    """Refuse some of the categories an access request asked for.

    A rejection is recorded as permanently as an approval and grants nothing.
    Roles/failures: as for approve.
    """
    return await _decide(
        service.reject_categories, request_id, body, user, service, vocabulary, request_context
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
    operation: _DecisionOperation,
    request_id: UUID,
    body: CategorySelectionRequest,
    user: AuthenticatedUser,
    service: ConsentServiceDep,
    vocabulary: CategoryVocabulary,
    request_context: str | None,
) -> DecisionOutcomeResponse:
    """Approve and reject differ only in which service method runs, so they share this."""
    try:
        outcome = await operation(
            user,
            request_id,
            resolve_category_codes(vocabulary, body.category_codes),
            request_context=request_context,
        )
    except ConsentError as exc:
        raise to_http_error(exc) from exc
    return _to_outcome_response(outcome, vocabulary)


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
