"""Record endpoints (M2): upload, relationship-scoped metadata reads, presigned downloads.

M2 access model — deliberately narrow (module docstring of service.py): patients see their
own records, hospital admins see their own hospital's uploads, doctors see NOTHING here
until the consent module (M3) adds ``consent.enforce()`` + audit in front of these reads.
"""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from app.modules.auth.dependencies import CurrentUser, require_role
from app.modules.auth.domain import AuthenticatedUser, Role
from app.modules.records.dependencies import RecordServiceDep, parse_cursor, to_http_error
from app.modules.records.errors import RecordsError
from app.modules.records.schemas import (
    DownloadUrlResponse,
    RecordCategoryListResponse,
    RecordCategoryResponse,
    RecordListResponse,
    RecordMetadataResponse,
)
from app.modules.records.service import FileUpload
from app.shared.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

records_router = APIRouter(prefix="/records", tags=["records"])
categories_router = APIRouter(prefix="/record-categories", tags=["records"])

# The two roles with a layer-2 relationship to records at M2 (see module docstring).
RequireRecordActor = require_role(Role.PATIENT, Role.HOSPITAL_ADMIN)
RecordActor = Annotated[AuthenticatedUser, Depends(RequireRecordActor)]


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
            )
    except RecordsError as exc:
        raise to_http_error(exc) from exc
    return RecordMetadataResponse.from_view(view)


@records_router.get("", response_model=RecordListResponse)
async def list_records(
    user: RecordActor,
    service: RecordServiceDep,
    category: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> RecordListResponse:
    """The caller's records, newest first, cursor-paginated, optionally by category.

    Roles: PATIENT (own records) or HOSPITAL_ADMIN (records their hospital uploaded).
    Consent requirement: none — both scopes are ADR-013 layer-2 relationships.
    Failure modes: 401, 403, 404 (no profile row), 422 (bad cursor/limit/category).
    """
    try:
        page = await service.list_for_caller(
            user, category_code=category, after=parse_cursor(cursor), limit=limit
        )
    except RecordsError as exc:
        raise to_http_error(exc) from exc
    return RecordListResponse(
        items=[RecordMetadataResponse.from_view(view) for view in page.items],
        next_cursor=page.next_cursor,
    )


@records_router.get("/{record_id}", response_model=RecordMetadataResponse)
async def read_record_metadata(
    record_id: UUID,
    user: RecordActor,
    service: RecordServiceDep,
) -> RecordMetadataResponse:
    """Metadata of one record within the caller's relationship scope.

    Roles: PATIENT (own) or HOSPITAL_ADMIN (own hospital's upload). A record outside the
    caller's scope answers 404, never 403 (existence must not leak, API_GUIDELINES).
    Failure modes: 401, 403, 404.
    """
    try:
        view = await service.get_for_caller(user, record_id)
    except RecordsError as exc:
        raise to_http_error(exc) from exc
    return RecordMetadataResponse.from_view(view)


@records_router.post("/{record_id}/download-url", response_model=DownloadUrlResponse)
async def create_download_url(
    record_id: UUID,
    user: RecordActor,
    service: RecordServiceDep,
) -> DownloadUrlResponse:
    """Issue a short-lived presigned download URL for the record's file.

    Roles: PATIENT (own) or HOSPITAL_ADMIN (own hospital's upload) — the URL is issued
    only after the relationship check (docs/SECURITY.md). M3 adds the consent check +
    audit-log write here for doctor access. Failure modes: 401, 403, 404, 503 (storage).
    """
    try:
        link = await service.create_download_link(user, record_id)
    except RecordsError as exc:
        raise to_http_error(exc) from exc
    return DownloadUrlResponse(url=link.url, expires_in_seconds=link.expires_in_seconds)
