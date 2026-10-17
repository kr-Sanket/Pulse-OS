"""Hospital + doctor endpoints (M2: onboarding, verification, doctor management).

Flow design: ADR-015. RBAC: docs/DOMAIN_MODEL.md §3 (role gates here are layer 1; the
own-hospital scoping inside the service is layer 2).
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.modules.auth.dependencies import (
    RequireDoctor,
    RequireHospitalAdmin,
    RequireSystemAdmin,
    VerifiedIdentity,
)
from app.modules.auth.dependencies import to_http_error as auth_to_http_error
from app.modules.auth.domain import AuthenticatedUser
from app.modules.auth.errors import AuthError
from app.modules.records.dependencies import HospitalServiceDep, parse_cursor, to_http_error
from app.modules.records.errors import HospitalNotFoundError, RecordsError
from app.modules.records.models import DoctorStatus, HospitalVerificationStatus
from app.modules.records.schemas import (
    DoctorListResponse,
    DoctorProfileResponse,
    DoctorRegistrationRequest,
    DoctorResponse,
    HospitalAdminProfileResponse,
    HospitalListResponse,
    HospitalRegistrationRequest,
    HospitalResponse,
)
from app.shared.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

hospitals_router = APIRouter(prefix="/hospitals", tags=["hospitals"])
doctors_router = APIRouter(prefix="/doctors", tags=["doctors"])

HospitalAdminUser = Annotated[AuthenticatedUser, Depends(RequireHospitalAdmin)]


@hospitals_router.post(
    "/register",
    status_code=201,
    response_model=HospitalAdminProfileResponse,
    responses={200: {"model": HospitalAdminProfileResponse, "description": "Already registered"}},
)
async def register_hospital(
    body: HospitalRegistrationRequest,
    identity: VerifiedIdentity,
    service: HospitalServiceDep,
    response: Response,
) -> HospitalAdminProfileResponse:
    """Register a new hospital with the caller as its admin (ADR-015 step 1).

    Roles: any *verified* identity — PulseOS claims are not required yet. Idempotent:
    repeat calls return the existing hospital with 200. The hospital starts PENDING;
    a System Admin must verify it before it can register doctors or upload records.
    Failure modes: 401, 409 (registered with a different role), 422, 503 (auth provider
    down — nothing is persisted).
    """
    try:
        outcome = await service.register_hospital(
            identity,
            hospital_name=body.hospital_name,
            hospital_address=body.hospital_address,
            admin_full_name=body.admin_full_name,
        )
    except RecordsError as exc:
        raise to_http_error(exc) from exc
    except AuthError as exc:  # claim provisioning failed → transaction rolled back
        raise auth_to_http_error(exc) from exc
    if not outcome.created:
        response.status_code = 200
    return HospitalAdminProfileResponse.build(outcome.hospital, outcome.admin)


@hospitals_router.get("/me", response_model=HospitalAdminProfileResponse)
async def read_own_hospital(
    user: HospitalAdminUser,
    service: HospitalServiceDep,
) -> HospitalAdminProfileResponse:
    """The caller's own hospital (ADR-013 layers 1+2 by construction).

    Roles: HOSPITAL_ADMIN. Failure modes: 401, 403, 404 (no admin profile row).
    """
    try:
        admin, hospital = await service.get_own_hospital(user.user_id)
    except RecordsError as exc:
        raise to_http_error(exc) from exc
    return HospitalAdminProfileResponse.build(hospital, admin)


@hospitals_router.get("", response_model=HospitalListResponse)
async def list_hospitals(
    user: Annotated[AuthenticatedUser, Depends(RequireSystemAdmin)],
    service: HospitalServiceDep,
    status: Annotated[
        HospitalVerificationStatus | None,
        Query(
            description="Filter by verification status (PENDING or VERIFIED).",
        ),
    ] = None,
) -> HospitalListResponse:
    """List registered hospitals for platform administration.

    Roles: SYSTEM_ADMIN (platform operations — touches no medical content).
    Failure modes: 401, 403, 422.
    """
    hospitals = await service.list_hospitals(verification_status=status)
    return HospitalListResponse(
        items=[HospitalResponse.model_validate(hospital) for hospital in hospitals]
    )


@hospitals_router.post("/{hid}/verify", response_model=HospitalResponse)
async def verify_hospital(
    hid: str,
    user: Annotated[AuthenticatedUser, Depends(RequireSystemAdmin)],
    service: HospitalServiceDep,
) -> HospitalResponse:
    """Mark a hospital VERIFIED (ADR-015 step 2). Idempotent.

    Roles: SYSTEM_ADMIN (platform operations — touches no medical content).
    Failure modes: 401, 403, 404 (unknown HID).
    """
    try:
        hospital = await service.verify_hospital(hid, verifier_user_id=user.user_id)
    except RecordsError as exc:
        raise to_http_error(exc) from exc
    return HospitalResponse.model_validate(hospital)


@hospitals_router.get("/me/doctors", response_model=DoctorListResponse)
async def list_own_hospital_doctors(
    user: HospitalAdminUser,
    service: HospitalServiceDep,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> DoctorListResponse:
    """The caller's hospital's doctors, newest first, cursor-paginated.

    Roles: HOSPITAL_ADMIN (own hospital only — other hospitals' rosters are invisible).
    Failure modes: 401, 403, 404 (no admin profile), 422 (bad cursor/limit).
    """
    try:
        page = await service.list_own_hospital_doctors(
            user.user_id, after=parse_cursor(cursor), limit=limit
        )
    except RecordsError as exc:
        raise to_http_error(exc) from exc
    return DoctorListResponse(
        items=[DoctorResponse.model_validate(doctor) for doctor in page.doctors],
        next_cursor=page.next_cursor,
    )


@hospitals_router.post("/me/doctors/{doctor_id}/activate", response_model=DoctorResponse)
async def activate_doctor(
    doctor_id: UUID,
    user: HospitalAdminUser,
    service: HospitalServiceDep,
) -> DoctorResponse:
    """Activate a doctor of the caller's hospital (ADR-015 step 3). Idempotent.

    Roles: HOSPITAL_ADMIN. Failure modes: 401, 403, 404 (unknown doctor OR a doctor of
    another hospital — indistinguishable by design).
    """
    return await _set_doctor_status(service, user, doctor_id, DoctorStatus.ACTIVE)


@hospitals_router.post("/me/doctors/{doctor_id}/deactivate", response_model=DoctorResponse)
async def deactivate_doctor(
    doctor_id: UUID,
    user: HospitalAdminUser,
    service: HospitalServiceDep,
) -> DoctorResponse:
    """Deactivate (remove) a doctor of the caller's hospital. Idempotent.

    The row is kept (DISABLED) — identities referenced by records/audit are never deleted
    (docs/DATABASE_DESIGN.md principle 5). Roles/failures: as for activate.
    """
    return await _set_doctor_status(service, user, doctor_id, DoctorStatus.DISABLED)


async def _set_doctor_status(
    service: HospitalServiceDep,
    user: AuthenticatedUser,
    doctor_id: UUID,
    status: DoctorStatus,
) -> DoctorResponse:
    try:
        doctor = await service.set_doctor_status(user.user_id, doctor_id, status)
    except RecordsError as exc:
        raise to_http_error(exc) from exc
    return DoctorResponse.model_validate(doctor)


@doctors_router.post(
    "/register",
    status_code=201,
    response_model=DoctorProfileResponse,
    responses={200: {"model": DoctorProfileResponse, "description": "Already registered"}},
)
async def register_doctor(
    body: DoctorRegistrationRequest,
    identity: VerifiedIdentity,
    service: HospitalServiceDep,
    response: Response,
) -> DoctorProfileResponse:
    """Register the caller as a doctor of a VERIFIED hospital (ADR-015 step 3).

    Roles: any *verified* identity — PulseOS claims are not required yet. Idempotent
    (repeat calls → 200). The profile starts PENDING until the hospital admin activates
    it. Failure modes: 401, 409 (different role / hospital not verified), 422 (validation
    or unknown hospital HID), 503 (auth provider down — nothing is persisted).
    """
    try:
        outcome = await service.register_doctor(
            identity,
            full_name=body.full_name,
            specialty=body.specialty,
            registration_number=body.registration_number,
            hospital_hid=body.hospital_hid,
        )
    except HospitalNotFoundError as exc:
        # A body-field reference, not a URI resource — validation, not 404.
        raise HTTPException(status_code=422, detail="Unknown hospital HID.") from exc
    except RecordsError as exc:
        raise to_http_error(exc) from exc
    except AuthError as exc:
        raise auth_to_http_error(exc) from exc
    if not outcome.created:
        response.status_code = 200
    return DoctorProfileResponse.build(outcome.doctor, outcome.hospital)


@doctors_router.get("/me", response_model=DoctorProfileResponse)
async def read_own_doctor_profile(
    user: Annotated[AuthenticatedUser, Depends(RequireDoctor)],
    service: HospitalServiceDep,
) -> DoctorProfileResponse:
    """The caller's own doctor profile with hospital context.

    Roles: DOCTOR. Failure modes: 401, 403, 404 (no doctor profile row).
    """
    try:
        doctor, hospital = await service.get_own_doctor_profile(user.user_id)
    except RecordsError as exc:
        raise to_http_error(exc) from exc
    return DoctorProfileResponse.build(doctor, hospital)
