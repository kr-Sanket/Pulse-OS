"""records module dependency wiring + domain-error → RFC 7807 translation.

Composition only — no business logic. Like the auth module, the boundary-layer error
translator lives here so routers stay thin and services never see HTTP.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db_session
from app.core.queue import JobQueue
from app.modules.auth.accounts import UserAccountService
from app.modules.auth.dependencies import get_user_account_service
from app.modules.consent.dependencies import get_consent_service
from app.modules.consent.service import ConsentService
from app.modules.patients.directory import PatientDirectoryService
from app.modules.patients.repository import PatientRepository
from app.modules.records.errors import (
    ClinicianNotActiveError,
    DoctorNotFoundError,
    EmptyFileError,
    FileTooLargeError,
    HospitalNotFoundError,
    HospitalNotVerifiedError,
    OrgRegistrationConflictError,
    ProfileNotFoundError,
    RecordNotFoundError,
    RecordsError,
    StorageUnavailableError,
    UnknownCategoryError,
    UnknownPatientError,
    UnsupportedFileTypeError,
)
from app.modules.records.organizations import HospitalService
from app.modules.records.repository import (
    DoctorRepository,
    HospitalAdminRepository,
    HospitalRepository,
    MedicalRecordRepository,
    RecordCategoryRepository,
)
from app.modules.records.service import RecordService
from app.modules.records.storage import ObjectStorage
from app.shared.pagination import (
    CursorKey,
    DateCursor,
    InvalidCursorError,
    SortDirection,
    decode_cursor,
    decode_date_cursor,
)


def to_http_error(exc: RecordsError) -> HTTPException:
    """Domain → RFC 7807 translation shared by the records routers."""
    if isinstance(exc, ProfileNotFoundError):
        return HTTPException(status_code=404, detail="Profile not found for this account.")
    if isinstance(exc, RecordNotFoundError):
        return HTTPException(status_code=404, detail="Record not found.")
    if isinstance(exc, DoctorNotFoundError):
        return HTTPException(status_code=404, detail="Doctor not found.")
    if isinstance(exc, HospitalNotFoundError):
        return HTTPException(status_code=404, detail="Hospital not found.")
    if isinstance(exc, ClinicianNotActiveError):
        return HTTPException(
            status_code=403, detail="Your clinician profile is not active at its hospital."
        )
    if isinstance(exc, HospitalNotVerifiedError):
        return HTTPException(status_code=409, detail="Hospital is not verified yet.")
    if isinstance(exc, OrgRegistrationConflictError):
        return HTTPException(status_code=409, detail=exc.detail)
    if isinstance(exc, UnknownPatientError):
        return HTTPException(status_code=422, detail="Unknown patient Health ID.")
    if isinstance(exc, UnknownCategoryError):
        return HTTPException(status_code=422, detail="Unknown record category code.")
    if isinstance(exc, EmptyFileError):
        return HTTPException(status_code=422, detail="Uploaded file is empty.")
    if isinstance(exc, FileTooLargeError):
        return HTTPException(
            status_code=413,
            detail=f"Uploaded file exceeds the {exc.max_bytes}-byte limit.",
        )
    if isinstance(exc, UnsupportedFileTypeError):
        return HTTPException(
            status_code=415,
            detail=f"Unsupported file type; allowed: {', '.join(exc.allowed)}.",
        )
    if isinstance(exc, StorageUnavailableError):
        return HTTPException(status_code=503, detail="File storage is unavailable.")
    # Any RecordsError without a specific mapping is a server-side problem.
    return HTTPException(status_code=500, detail="The operation failed unexpectedly.")


def parse_cursor(cursor: str | None) -> CursorKey | None:
    """Decode an opaque pagination cursor; a forged/corrupted one is a validation error."""
    if cursor is None:
        return None
    try:
        return decode_cursor(cursor)
    except InvalidCursorError:
        raise HTTPException(status_code=422, detail="Invalid pagination cursor.") from None


def parse_date_cursor(cursor: str | None, sort: SortDirection) -> DateCursor | None:
    """Decode a clinical-date cursor and check it belongs to the sort being asked for.

    The pair matters, not just the token. A cursor issued for ``newest`` names a position in
    a sequence that ``oldest`` walks the other way, so honouring it under the other
    direction would silently serve a page from the middle of the wrong end — no error, just
    wrong records. Refusing is the only safe reading, and 422 is what a client that changed
    the sort without resetting the cursor deserves to see.
    """
    if cursor is None:
        return None
    try:
        decoded = decode_date_cursor(cursor)
    except InvalidCursorError:
        raise HTTPException(status_code=422, detail="Invalid pagination cursor.") from None
    if decoded.sort is not sort:
        raise HTTPException(
            status_code=422,
            detail="This pagination cursor was issued for a different sort order.",
        )
    return decoded


def get_request_context(request: Request) -> str | None:
    """The ``X-Request-Id`` correlation key that record-access audit events carry
    (docs/API_GUIDELINES.md). Duplicated from the consent boundary rather than imported
    across it — a four-line transport helper with no domain meaning; it belongs in
    ``app/shared`` once a third module needs it."""
    context: str | None = getattr(request.state, "request_id", None)
    return context


def get_object_storage(request: Request) -> ObjectStorage:
    """The storage chosen at startup (lifespan); tests override this dependency."""
    storage: ObjectStorage = request.app.state.object_storage
    return storage


def get_job_queue(request: Request) -> JobQueue:
    """The queue chosen at startup (lifespan); tests override this dependency."""
    queue: JobQueue = request.app.state.job_queue
    return queue


def get_hospital_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    accounts: Annotated[UserAccountService, Depends(get_user_account_service)],
) -> HospitalService:
    # All repositories share the request's single session/transaction (get_db_session
    # is cached per request by FastAPI).
    return HospitalService(
        accounts=accounts,
        hospitals=HospitalRepository(session),
        admins=HospitalAdminRepository(session),
        doctors=DoctorRepository(session),
    )


def get_record_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
    queue: Annotated[JobQueue, Depends(get_job_queue)],
    consent: Annotated[ConsentService, Depends(get_consent_service)],
) -> RecordService:
    settings = get_settings()
    return RecordService(
        records=MedicalRecordRepository(session),
        categories=RecordCategoryRepository(session),
        admins=HospitalAdminRepository(session),
        doctors=DoctorRepository(session),
        hospitals=HospitalRepository(session),
        patients=PatientDirectoryService(PatientRepository(session)),
        storage=storage,
        queue=queue,
        # The ADR-013 layer-3 choke point. Same request session, so a read and the audit
        # event recording it commit together or not at all.
        consent=consent,
        # The same ConsentService again, under the two other names records knows it by
        # (ADR-020): what a clinician may currently read, and where a listing is recorded.
        # One object, three protocols — the seams are narrow so each call site says which
        # question it is asking, not merely which module it is asking.
        grant_scope=consent,
        listing_auditor=consent,
        record_auditor=consent,
        presign_ttl_seconds=settings.s3_presign_ttl_seconds,
        max_upload_bytes=settings.records_max_upload_bytes,
    )


HospitalServiceDep = Annotated[HospitalService, Depends(get_hospital_service)]
RecordServiceDep = Annotated[RecordService, Depends(get_record_service)]
RequestContextDep = Annotated[str | None, Depends(get_request_context)]
