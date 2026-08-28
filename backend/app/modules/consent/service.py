"""Consent domain service: access request lifecycle, decisions, active grants, and enforcement.

Framework-free; owns no transaction — the request scope commits (app/core/db.py).
Cross-module boundaries use explicit service interfaces
(auth, patients, doctors, hospitals, records).

CORE SECURITY INVARIANT:
Consent is the single choke point for medical record content (ADR-013).
Every access to patient clinical content must pass through enforce().
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.modules.auth.accounts import UserAccountService
from app.modules.auth.domain import Role
from app.modules.consent.errors import (
    AccessRequestNotFoundError,
    ConsentDeniedError,
    ConsentGrantNotFoundError,
    InvalidAccessRequestError,
    InvalidConsentStateError,
    UnauthorizedConsentActionError,
)
from app.modules.consent.models import (
    AccessRequest,
    ConsentDecision,
    ConsentGrant,
    DecisionType,
    RequestStatus,
)
from app.modules.consent.repository import ConsentRepository
from app.modules.consent.schemas import CategoryDecisionItem
from app.modules.doctors.service import DoctorService
from app.modules.hospitals.service import HospitalService
from app.modules.patients.service import PatientService
from app.modules.records.service import RecordService


class ConsentService:
    def __init__(
        self,
        consent: ConsentRepository,
        accounts: UserAccountService,
        patients: PatientService,
        doctors: DoctorService,
        hospitals: HospitalService,
        records: RecordService,
    ) -> None:
        self._consent = consent
        self._accounts = accounts
        self._patients = patients
        self._doctors = doctors
        self._hospitals = hospitals
        self._records = records

    async def create_access_request(
        self,
        *,
        doctor_user_id: UUID,
        patient_id: UUID,
        purpose: str,
        category_ids: Sequence[UUID],
        expires_in_days: int = 7,
    ) -> AccessRequest:
        """Create a Doctor's access request for a set of RecordCategories."""
        clean_purpose = purpose.strip()
        if not clean_purpose:
            raise InvalidAccessRequestError("Purpose must not be blank.")

        if not category_ids:
            raise InvalidAccessRequestError("At least one category must be requested.")

        # Verify requester is a valid Doctor
        doctor = await self._doctors.get_by_user_id(doctor_user_id)
        if doctor is None:
            raise UnauthorizedConsentActionError("Requester is not a registered doctor.")

        # Verify target patient exists
        patient = await self._patients.get_patient_by_id(patient_id)
        if patient is None:
            raise InvalidAccessRequestError("Target patient does not exist.")

        # Verify all requested categories exist
        for cat_id in category_ids:
            cat = await self._records.get_category_by_id(cat_id)
            if cat is None:
                raise InvalidAccessRequestError(f"Record category {cat_id} does not exist.")

        now_utc = datetime.now(UTC)
        expires_at = now_utc + timedelta(days=expires_in_days)

        request = AccessRequest(
            patient_id=patient.id,
            doctor_id=doctor.id,
            hospital_id=doctor.hospital_id,
            purpose=clean_purpose,
            status=RequestStatus.PENDING,
            expires_at=expires_at,
        )
        return await self._consent.create_access_request(request, category_ids)

    async def get_access_request(
        self, request_id: UUID
    ) -> tuple[AccessRequest, Sequence[UUID]] | None:
        req = await self._consent.get_access_request(request_id)
        if req is None:
            return None
        cats = await self._consent.get_request_category_ids(request_id)
        return req, cats

    async def decide_access_request(
        self,
        *,
        patient_user_id: UUID,
        request_id: UUID,
        decisions: Sequence[CategoryDecisionItem],
    ) -> tuple[AccessRequest, Sequence[ConsentDecision], Sequence[ConsentGrant]]:
        """Patient decides (APPROVED | REJECTED) per category for an AccessRequest.
        Appends immutable ConsentDecision rows and spawns active ConsentGrants for approvals.
        """
        patient = await self._patients.get_profile(patient_user_id)
        if patient is None:
            raise UnauthorizedConsentActionError("User is not a registered patient.")

        req = await self._consent.get_access_request(request_id)
        if req is None:
            raise AccessRequestNotFoundError("Access request not found.")

        if req.patient_id != patient.id:
            raise UnauthorizedConsentActionError(
                "Patients may only decide access requests directed to them."
            )

        if req.status is not RequestStatus.PENDING:
            raise InvalidConsentStateError("Access request has already been decided or cancelled.")

        now_utc = datetime.now(UTC)
        if req.expires_at <= now_utc:
            await self._consent.update_request_status(req.id, RequestStatus.EXPIRED)
            raise InvalidConsentStateError("Access request has expired.")

        requested_cat_ids = set(await self._consent.get_request_category_ids(request_id))
        decided_cat_ids = {item.category_id for item in decisions}

        if not requested_cat_ids.issubset(decided_cat_ids):
            raise InvalidConsentStateError(
                "All requested categories must be decided (APPROVED or REJECTED)."
            )

        created_decisions: list[ConsentDecision] = []
        created_grants: list[ConsentGrant] = []

        for item in decisions:
            if item.category_id not in requested_cat_ids:
                continue

            decision = ConsentDecision(
                request_id=req.id,
                patient_id=patient.id,
                doctor_id=req.doctor_id,
                category_id=item.category_id,
                decision=item.decision,
                decided_at=now_utc,
            )
            created_decisions.append(decision)

        persisted_decisions = await self._consent.add_decisions(created_decisions)

        # Spawns active grants for approved categories
        for item, decision_obj in zip(decisions, persisted_decisions, strict=False):
            if item.decision is DecisionType.APPROVED:
                # OD-2: Default 90 days expiry if not custom specified by patient
                grant_expiry = item.expires_at or (now_utc + timedelta(days=90))

                # Deactivate any prior active grant for this (patient, doctor, category)
                await self._consent.deactivate_existing_active_grants(
                    patient_id=patient.id,
                    doctor_id=req.doctor_id,
                    category_id=item.category_id,
                    superseded_at=now_utc,
                )

                grant = ConsentGrant(
                    patient_id=patient.id,
                    doctor_id=req.doctor_id,
                    category_id=item.category_id,
                    decision_id=decision_obj.id,
                    granted_at=now_utc,
                    expires_at=grant_expiry,
                )
                persisted_grant = await self._consent.add_grant(grant)
                created_grants.append(persisted_grant)

        updated_req = await self._consent.update_request_status(req.id, RequestStatus.DECIDED)
        assert updated_req is not None

        return updated_req, persisted_decisions, created_grants

    async def revoke_consent(
        self,
        *,
        patient_user_id: UUID,
        doctor_id: UUID,
        category_id: UUID,
    ) -> ConsentGrant:
        """Patient revokes an active consent grant. Subsequent reads will be denied."""
        patient = await self._patients.get_profile(patient_user_id)
        if patient is None:
            raise UnauthorizedConsentActionError("User is not a registered patient.")

        now_utc = datetime.now(UTC)
        revoked = await self._consent.revoke_grant(
            patient_id=patient.id,
            doctor_id=doctor_id,
            category_id=category_id,
            revoked_at=now_utc,
        )
        if revoked is None:
            raise ConsentGrantNotFoundError("No active consent grant found to revoke.")
        return revoked

    async def enforce(
        self,
        *,
        requester_user_id: UUID,
        patient_id: UUID,
        category_id: UUID,
    ) -> bool:
        """The single consent-enforcement choke point (ADR-013, SYSTEM_ARCHITECTURE.md).

        1. If requester is the Patient who owns the records -> ALLOW.
        2. If requester is a Doctor -> verify active ConsentGrant for (patient, doctor, category).
        3. If requester is System Admin -> STRICTLY DENY (no medical content access).
        4. If requester is Hospital Admin or unauthorized -> DENY.
        """
        user = await self._accounts.get_by_id(requester_user_id)
        if user is None:
            raise ConsentDeniedError("Unknown requester identity.")

        if user.role is Role.PATIENT:
            patient = await self._patients.get_profile(user.id)
            if patient is not None and patient.id == patient_id:
                return True
            raise ConsentDeniedError("Patient cannot access another patient's medical records.")

        if user.role is Role.DOCTOR:
            doctor = await self._doctors.get_by_user_id(user.id)
            if doctor is None:
                raise ConsentDeniedError("Doctor profile not found.")

            now_utc = datetime.now(UTC)
            grant = await self._consent.get_active_grant(
                patient_id=patient_id,
                doctor_id=doctor.id,
                category_id=category_id,
                as_of=now_utc,
            )
            if grant is None:
                raise ConsentDeniedError(
                    "Access denied: no active consent grant for this patient and category."
                )
            return True

        if user.role is Role.SYSTEM_ADMIN:
            raise ConsentDeniedError(
                "System administrators are strictly forbidden from accessing "
                "medical record content."
            )

        raise ConsentDeniedError(
            "Hospital administrators cannot access medical records via consent."
        )

    async def enforce_doctor_access(
        self,
        *,
        doctor_id: UUID,
        patient_id: UUID,
        category_id: UUID,
    ) -> ConsentGrant:
        """Enforce active grant directly against a known Doctor ID."""
        now_utc = datetime.now(UTC)
        grant = await self._consent.get_active_grant(
            patient_id=patient_id,
            doctor_id=doctor_id,
            category_id=category_id,
            as_of=now_utc,
        )
        if grant is None:
            raise ConsentDeniedError(
                "Access denied: no active consent grant for this doctor, patient, and category."
            )
        return grant

    async def get_active_grant(
        self,
        *,
        patient_id: UUID,
        doctor_id: UUID,
        category_id: UUID,
    ) -> ConsentGrant | None:
        now_utc = datetime.now(UTC)
        return await self._consent.get_active_grant(
            patient_id=patient_id,
            doctor_id=doctor_id,
            category_id=category_id,
            as_of=now_utc,
        )

    async def list_active_grants_for_patient(self, patient_user_id: UUID) -> Sequence[ConsentGrant]:
        patient = await self._patients.get_profile(patient_user_id)
        if patient is None:
            return []
        now_utc = datetime.now(UTC)
        return await self._consent.list_active_grants_for_patient(patient.id, as_of=now_utc)

    async def list_requests_for_patient(
        self, patient_user_id: UUID, status: RequestStatus | None = None
    ) -> Sequence[AccessRequest]:
        patient = await self._patients.get_profile(patient_user_id)
        if patient is None:
            return []
        return await self._consent.list_requests_for_patient(patient.id, status=status)

    async def list_requests_for_doctor(
        self, doctor_user_id: UUID, status: RequestStatus | None = None
    ) -> Sequence[AccessRequest]:
        doctor = await self._doctors.get_by_user_id(doctor_user_id)
        if doctor is None:
            return []
        return await self._consent.list_requests_for_doctor(doctor.id, status=status)
