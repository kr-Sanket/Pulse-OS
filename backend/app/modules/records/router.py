"""Record endpoints (M2): upload, relationship-scoped metadata reads, presigned downloads.

Access model (module docstring of service.py): patients read their own records, hospital
admins read their own hospital's uploads (ADR-013 layer 2, decided in this module), and
clinicians read what an active consent grant covers (layer 3, decided by ``consent.enforce``
and audited there). Uploading and listing stay narrower than reading — a clinician has no
listing scope and no upload path here.
"""

from datetime import date
from http import HTTPStatus
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse

from app.core.errors import problem_response
from app.modules.auth.dependencies import CurrentUser, rate_limited, require_role
from app.modules.auth.domain import AuthenticatedUser, Role
from app.modules.records.dependencies import (
    RecordServiceDep,
    RequestContextDep,
    parse_date_cursor,
    to_http_error,
)
from app.modules.records.errors import RecordsError
from app.modules.records.schemas import (
    DownloadUrlResponse,
    GrantedRecordListResponse,
    GrantedRecordResponse,
    RecordCategoryListResponse,
    RecordCategoryResponse,
    RecordExistenceResponse,
    RecordListResponse,
    RecordMetadataResponse,
)
from app.modules.records.service import FileUpload
from app.shared.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, SortDirection

records_router = APIRouter(prefix="/records", tags=["records"])
categories_router = APIRouter(prefix="/record-categories", tags=["records"])
# A top-level resource rather than a sub-path of /records: `/records/existence` only works
# because it is declared before `/records/{record_id}`, and a second literal competing with
# a UUID path parameter is a trap waiting for whoever reorders these routes. This one
# cannot shadow anything. It stays in this module because `records` owns the data —
# ownership decides the module, the URL only decides the shape (docs/API_GUIDELINES.md).
granted_records_router = APIRouter(prefix="/granted-records", tags=["records"])

# Writing and listing need a relationship this module can evaluate on its own.
RequireRecordActor = require_role(Role.PATIENT, Role.HOSPITAL_ADMIN)
RecordActor = Annotated[AuthenticatedUser, Depends(RequireRecordActor)]

# Reading one known record additionally admits clinicians, whose access is decided by
# consent rather than by any relationship records can see (ADR-013 layer 3). SYSTEM_ADMIN
# is absent from both gates: no admin break-glass exists (docs/SECURITY.md).
RequireRecordReader = require_role(Role.PATIENT, Role.HOSPITAL_ADMIN, Role.DOCTOR)
RecordReader = Annotated[AuthenticatedUser, Depends(RequireRecordReader)]

# Discovering that records exist is a clinician-only capability: a patient already knows
# what they hold, and no hospital or platform admin has any reason to probe a Health ID.
RequireClinician = require_role(Role.DOCTOR)
Clinician = Annotated[AuthenticatedUser, Depends(RequireClinician)]


def _problem(request: Request, exc: RecordsError) -> JSONResponse:
    """Build the RFC 7807 response for a failed read — to be **returned, never raised**.

    A raised ``HTTPException`` unwinds the request's dependency stack, and the rollback in
    ``get_db_session`` takes the audit row consent just wrote for the refusal with it. The
    M3 gate requires attempted unauthorized reads to be denied *and logged*
    (.claude/ROADMAP.md), so on these two paths the refusal has to commit. Returning the
    identical problem+json body keeps the wire contract unchanged; only the unwinding
    differs. Read paths mutate nothing else, so committing on refusal is safe: the audit
    row is the whole of the transaction.
    """
    http_error = to_http_error(exc)
    detail = http_error.detail if isinstance(http_error.detail, str) else None
    return problem_response(
        request,
        status_code=http_error.status_code,
        title=HTTPStatus(http_error.status_code).phrase,
        detail=detail,
    )


@categories_router.get("", response_model=RecordCategoryListResponse)
async def list_record_categories(
    user: CurrentUser,
    service: RecordServiceDep,
) -> RecordCategoryListResponse:
    """The record-category controlled vocabulary (docs/DOMAIN_MODEL.md §1).

    Roles: any authenticated user (reference data, no PHI). Failure modes: 401.
    """
    categories = await service.list_categories()
    return RecordCategoryListResponse(
        items=[RecordCategoryResponse.model_validate(category) for category in categories]
    )


@records_router.post("", status_code=201, response_model=RecordMetadataResponse)
async def upload_record(
    user: RecordActor,
    service: RecordServiceDep,
    request_context: RequestContextDep,
    file: Annotated[UploadFile, File()],
    category_code: Annotated[str, Form(alias="categoryCode", min_length=1, max_length=32)],
    date_of_service: Annotated[date, Form(alias="dateOfService")],
    description: Annotated[str | None, Form(max_length=255)] = None,
    patient_health_id: Annotated[
        str | None, Form(alias="patientHealthId", min_length=1, max_length=20)
    ] = None,
) -> RecordMetadataResponse:
    """Upload one medical document (multipart) and create its metadata row.

    Roles: HOSPITAL_ADMIN (uploads for a patient by Health ID — requires ``patientHealthId``
    and a VERIFIED hospital) or PATIENT (uploads to their own locker — ``patientHealthId``
    must be absent). Consent requirement: none — uploading creates data, it reads nothing.
    Failure modes: 401, 403, 404 (no profile row), 409 (hospital unverified),
    413 (too large), 415 (bad type), 422 (validation / unknown Health ID or category /
    future date), 503 (storage down — nothing is persisted).
    """
    if date_of_service > date.today():
        raise HTTPException(status_code=422, detail="dateOfService must not be in the future.")
    # Read at most cap+1 bytes so an oversized body can never exhaust memory.
    data = await file.read(service.max_upload_bytes + 1)
    payload = FileUpload(
        filename=file.filename or "document",
        content_type=file.content_type or "",
        data=data,
    )
    try:
        if user.role is Role.HOSPITAL_ADMIN:
            if patient_health_id is None:
                raise HTTPException(
                    status_code=422, detail="patientHealthId is required for hospital uploads."
                )
            view = await service.upload_for_health_id(
                user,
                patient_health_id=patient_health_id,
                category_code=category_code,
                date_of_service=date_of_service,
                description=description,
                file=payload,
                request_context=request_context,
            )
        else:  # PATIENT — the role gate admits no other role
            if patient_health_id is not None:
                raise HTTPException(
                    status_code=422,
                    detail="patientHealthId is not allowed on locker uploads.",
                )
            view = await service.upload_to_own_locker(
                user,
                category_code=category_code,
                date_of_service=date_of_service,
                description=description,
                file=payload,
                request_context=request_context,
            )
    except RecordsError as exc:
        raise to_http_error(exc) from exc
    return RecordMetadataResponse.from_view(view)


@records_router.get("", response_model=RecordListResponse)
async def list_records(
    user: RecordActor,
    service: RecordServiceDep,
    category: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    search: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    sort: Annotated[SortDirection, Query()] = SortDirection.NEWEST_FIRST,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> RecordListResponse:
    """The caller's records in clinical-date order, cursor-paginated, filterable.

    Ordered by ``dateOfService`` — the date care happened — newest first by default, with
    the record id as a tie-breaker so same-day records have a stable total order.
    ``search`` is a case-insensitive substring of the filename or description; LIKE
    metacharacters in it are literal.

    ``sort``, ``search`` and ``category`` select *which* sequence is paginated, so a cursor
    only means something alongside the same three. A cursor issued under the other sort is
    refused rather than honoured (422); changing ``search`` or ``category`` is the client's
    cue to drop the cursor.

    Roles: PATIENT (own records) or HOSPITAL_ADMIN (records their hospital uploaded).
    Consent requirement: none — both scopes are ADR-013 layer-2 relationships.
    Failure modes: 401, 403, 404 (no profile row), 422 (bad cursor/limit/category/sort, or a
    cursor that does not belong to the requested sort).
    """
    try:
        page = await service.list_for_caller(
            user,
            category_code=category,
            search=search,
            sort=sort,
            after=parse_date_cursor(cursor, sort),
            limit=limit,
        )
    except RecordsError as exc:
        raise to_http_error(exc) from exc
    return RecordListResponse(
        items=[RecordMetadataResponse.from_view(view) for view in page.items],
        next_cursor=page.next_cursor,
    )


@records_router.get(
    "/existence",
    response_model=RecordExistenceResponse,
    responses={429: {"description": "Rate limit exceeded"}},
)
async def list_record_existence(
    user: Clinician,
    _limit: Annotated[AuthenticatedUser, Depends(rate_limited("record_existence"))],
    service: RecordServiceDep,
    patient_health_id: Annotated[str, Query(alias="patientHealthId", min_length=1, max_length=20)],
) -> RecordExistenceResponse:
    """Which record categories a patient holds anything in — existence only.

    Step 1 of the consent flow (docs/SYSTEM_ARCHITECTURE.md): the clinician learns that
    records exist so they can ask for the right categories. The response carries a code and
    a display name per category and nothing else — no record id, filename, hospital, date,
    description or count — so a caller with no grant learns only what step 1 allows.

    Roles: DOCTOR, and the clinician profile must be ACTIVE at its hospital (ADR-015).
    Consent requirement: none, and deliberately so — ``consent.enforce`` answers whether a
    *record* may be read, which cannot be answered before any grant exists. Every read past
    this point still crosses it. Nothing here is audited: no record was accessed.
    Failure modes: 401, 403 (wrong role or inactive clinician), 404 (no clinician profile),
    422 (missing/oversized Health ID, or no patient with that Health ID).
    """
    try:
        categories = await service.list_existing_categories(
            user, patient_health_id=patient_health_id
        )
    except RecordsError as exc:
        raise to_http_error(exc) from exc
    return RecordExistenceResponse(
        items=[RecordCategoryResponse.model_validate(category) for category in categories]
    )


@records_router.get("/{record_id}", response_model=RecordMetadataResponse)
async def read_record_metadata(
    request: Request,
    record_id: UUID,
    user: RecordReader,
    service: RecordServiceDep,
    request_context: RequestContextDep,
) -> RecordMetadataResponse | JSONResponse:
    """Metadata of one record the caller is authorized to see.

    Roles: PATIENT (own), HOSPITAL_ADMIN (own hospital's upload), DOCTOR (an active consent
    grant for the record's category). Consent requirement: enforced for patients and
    clinicians at the single choke point; a hospital's own upload is a layer-2 relationship
    instead. Every outcome, allowed or refused, is audited. A record the caller may not see
    answers 404, never 403 (existence must not leak, API_GUIDELINES).
    Failure modes: 401, 403, 404.
    """
    try:
        view = await service.get_for_caller(user, record_id, request_context=request_context)
    except RecordsError as exc:
        return _problem(request, exc)  # returned, not raised — see _problem
    return RecordMetadataResponse.from_view(view)


@records_router.post("/{record_id}/download-url", response_model=DownloadUrlResponse)
async def create_download_url(
    request: Request,
    record_id: UUID,
    user: RecordReader,
    service: RecordServiceDep,
    request_context: RequestContextDep,
) -> DownloadUrlResponse | JSONResponse:
    """Issue a short-lived presigned download URL for the record's file.

    Roles: as for reading metadata. The URL is issued only after the same authorization
    (docs/SECURITY.md), and the event is audited as a download rather than a view.
    Failure modes: 401, 403, 404, 503 (storage).
    """
    try:
        link = await service.create_download_link(user, record_id, request_context=request_context)
    except RecordsError as exc:
        return _problem(request, exc)  # returned, not raised — see _problem
    return DownloadUrlResponse(url=link.url, expires_in_seconds=link.expires_in_seconds)


@granted_records_router.get(
    "",
    response_model=GrantedRecordListResponse,
    responses={429: {"description": "Rate limit exceeded"}},
)
async def list_granted_records(
    user: Clinician,
    _limit: Annotated[AuthenticatedUser, Depends(rate_limited("granted_records"))],
    service: RecordServiceDep,
    request_context: RequestContextDep,
    patient_health_id: Annotated[str, Query(alias="patientHealthId", min_length=1, max_length=20)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> GrantedRecordListResponse:
    """The records one patient's consent currently lets this clinician read, newest first.

    Step 4 of the consent flow (docs/SYSTEM_ARCHITECTURE.md) and the step that closes it:
    after ``/records/existence`` says a category holds something and the patient approves a
    request for it, this is where the clinician learns the record ids. Each item is the
    narrow chooser projection of ``GrantedRecordResponse`` — no filename, description, size
    or content type; those are disclosed by ``GET /records/{record_id}``, one authorized and
    audited read at a time.

    ``grantedCategories`` reports the scope the page was drawn from, so an empty list under
    a live grant is distinguishable from having no grant at all.

    Roles: DOCTOR, and the clinician profile must be ACTIVE (ADR-015). Consent requirement:
    the page is filtered by the categories consent reports as granted — a filter, never a
    verdict. Nothing here permits a read: every record opened from this page still passes
    ``consent.enforce``, so an id learned here is refused the moment its grant is revoked.
    A clinician with no live grant receives an empty page rather than a 403: they already
    know this patient exists, having searched the Health ID, so there is no existence left
    to protect.

    Audited: exactly one event per request — ``RECORDS_LISTED``, or ``ACCESS_DENIED`` when
    nothing is in scope. Unlike the single-record reads, this handler *raises* its failures
    (ADR-017 does not apply): every ``RecordsError`` below is raised while resolving the
    clinician or the patient, which happens before the audit row is written, so no unwind
    can discard a trail entry.

    Failure modes: 401, 403 (wrong role or inactive clinician), 404 (no clinician profile),
    422 (missing/oversized Health ID, unknown Health ID, bad cursor or limit).
    """
    try:
        page = await service.list_shared_for_clinician(
            user,
            patient_health_id=patient_health_id,
            # This listing offers no sort control; its cursor is always newest-first.
            after=parse_date_cursor(cursor, SortDirection.NEWEST_FIRST),
            limit=limit,
            request_context=request_context,
        )
    except RecordsError as exc:
        raise to_http_error(exc) from exc
    return GrantedRecordListResponse(
        granted_categories=[
            RecordCategoryResponse.model_validate(category) for category in page.granted_categories
        ],
        items=[GrantedRecordResponse.from_view(view) for view in page.items],
        next_cursor=page.next_cursor,
    )
