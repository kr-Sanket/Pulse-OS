"""Patients endpoints: registration, own-profile read (M0.3 part 3a), and the
hospital-facing identity lookup that guards an upload (docs/DOMAIN_MODEL.md §3)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.modules.auth.dependencies import (
    RequireHospitalAdmin,
    RequirePatient,
    VerifiedIdentity,
    rate_limited,
    to_http_error,
)
from app.modules.auth.domain import AuthenticatedUser
from app.modules.auth.errors import AuthError
from app.modules.patients.dependencies import PatientServiceDep
from app.modules.patients.errors import (
    InvalidHealthIdError,
    PatientNotFoundError,
    RegistrationConflictError,
)
from app.modules.patients.schemas import (
    PatientLookupResponse,
    PatientProfileResponse,
    PatientRegistrationRequest,
)

router = APIRouter(prefix="/patients", tags=["patients"])


@router.post(
    "/register",
    status_code=201,
    response_model=PatientProfileResponse,
    responses={200: {"model": PatientProfileResponse, "description": "Already registered"}},
)
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


@router.get(
    "/lookup",
    response_model=PatientLookupResponse,
    responses={429: {"description": "Rate limit exceeded"}},
)
async def lookup_patient(
    user: Annotated[AuthenticatedUser, Depends(RequireHospitalAdmin)],
    _limit: Annotated[AuthenticatedUser, Depends(rate_limited("patient_lookup"))],
    service: PatientServiceDep,
    health_id: Annotated[str, Query(alias="healthId", min_length=1, max_length=20)],
) -> PatientLookupResponse:
    """Confirm which patient a Pulse Health ID identifies, by name.

    The safety step in front of ``POST /records``: a hospital files a document against a
    Health ID, nothing can move or delete it afterwards, and until this existed an
    administrator had no way to check whose history they were about to write to. A valid
    Health ID belonging to the wrong patient was therefore an unrecoverable mistake.

    Roles: HOSPITAL_ADMIN only. Not DOCTOR — clinicians discover patients through
    ``GET /records/existence``, which has a different disclosure contract and is left
    untouched. Not SYSTEM_ADMIN — platform operations never require patient identity
    (docs/SECURITY.md). Not PATIENT — a patient looking up other patients is the
    enumeration ADR-012 exists to prevent.

    Discloses exactly the Health ID in canonical form and the patient's name, which is the
    "existence + name confirmation only" row of the RBAC matrix (docs/DOMAIN_MODEL.md §3)
    and no more: no date of birth, no contact details, no internal id, and nothing medical.
    **This confirms an identity; it authorizes nothing.** The upload that follows is
    authorized on its own terms by the records module, which still requires a VERIFIED
    hospital and re-resolves the Health ID itself.

    Consent requirement: none — no record is read, so there is nothing for
    ``consent.enforce`` to rule on. Nothing here is audited, for the same reason
    ``/records/existence`` is not: no record was accessed and no truthful ``AuditAction``
    member exists. That question is open for both endpoints (.claude/TODO.md).

    **Rate limiting: this is a Health-ID oracle and a future rate-limiting surface**, in
    the same family as ``POST /access-requests`` and ``GET /records/existence`` (finding
    M3-D). It is narrower than either — HOSPITAL_ADMIN only, and a malformed ID is refused
    before the database is touched — but it is the first endpoint that returns a *name*,
    so it belongs in the same bucket when that lands.

    Failure modes: 401, 403 (wrong role), 422 (malformed Health ID, or no patient matches
    it — reported distinctly, because ADR-012's check character makes "you typed it wrong"
    and "this person is not on PulseOS" genuinely different answers).
    """
    try:
        patient = await service.lookup_by_health_id(health_id)
    except InvalidHealthIdError as exc:
        raise HTTPException(status_code=422, detail="That is not a valid Pulse Health ID.") from exc
    except PatientNotFoundError as exc:
        raise HTTPException(
            status_code=422, detail="No patient on PulseOS has that Health ID."
        ) from exc
    return PatientLookupResponse.model_validate(patient)
