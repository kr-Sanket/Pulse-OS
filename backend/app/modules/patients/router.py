"""Patients endpoints: registration and own-profile read (M0.3 part 3a)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response

from app.modules.auth.dependencies import RequirePatient, VerifiedIdentity, to_http_error
from app.modules.auth.domain import AuthenticatedUser
from app.modules.auth.errors import AuthError
from app.modules.patients.dependencies import PatientServiceDep
from app.modules.patients.errors import RegistrationConflictError
from app.modules.patients.schemas import PatientProfileResponse, PatientRegistrationRequest

router = APIRouter(prefix="/patients", tags=["patients"])


@router.post("/register", status_code=201, response_model=PatientProfileResponse)
async def register_patient(
    body: PatientRegistrationRequest,
    identity: VerifiedIdentity,
    service: PatientServiceDep,
    response: Response,
) -> PatientProfileResponse:
    """Register the authenticated Firebase subject as a patient and issue a Health ID.

    Roles: any *verified* identity — PulseOS claims are not required yet (this endpoint
    creates them). Idempotent: repeat calls return the existing profile with 200.
    Failure modes: 401 (bad token), 409 (registered with a different role),
    422 (validation), 503 (auth provider down — nothing is persisted).
    """
    try:
        outcome = await service.register(
            identity,
            full_name=body.full_name,
            date_of_birth=body.date_of_birth,
            gender=body.gender,
        )
    except RegistrationConflictError as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    except AuthError as exc:  # claim provisioning failed → transaction rolled back
        raise to_http_error(exc) from exc
    if not outcome.created:
        response.status_code = 200
    return PatientProfileResponse.model_validate(outcome.patient)


@router.get("/me", response_model=PatientProfileResponse)
async def read_own_profile(
    user: Annotated[AuthenticatedUser, Depends(RequirePatient)],
    service: PatientServiceDep,
) -> PatientProfileResponse:
    """Return the caller's own patient profile.

    Roles: PATIENT (ADR-013 layer 1 + own-profile relationship by construction).
    Failure modes: 401, 403 (wrong role / unprovisioned), 404 (no profile row).
    """
    patient = await service.get_profile(user.user_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient profile not found.")
    return PatientProfileResponse.model_validate(patient)
