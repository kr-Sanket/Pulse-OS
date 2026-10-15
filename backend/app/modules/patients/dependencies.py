"""Patients module dependency wiring (composition only — no logic)."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.modules.auth.accounts import UserAccountService
from app.modules.auth.dependencies import get_user_account_service
from app.modules.patients.repository import PatientRepository
from app.modules.patients.service import PatientService
from app.modules.records.directory import (
    HospitalVerificationDirectoryService,
    hospital_verification_directory,
)


def get_patient_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    accounts: Annotated[UserAccountService, Depends(get_user_account_service)],
) -> PatientService:
    # Both depend on get_db_session; FastAPI caches it per request, so the account
    # service and the patient repository share one session/transaction.
    return PatientService(accounts=accounts, patients=PatientRepository(session))


PatientServiceDep = Annotated[PatientService, Depends(get_patient_service)]


def get_hospital_verification(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> HospitalVerificationDirectoryService:
    # records owns hospitals and their verification status; patients reads the one fact
    # it needs through records' published directory (docs/SYSTEM_ARCHITECTURE.md rule 1).
    return hospital_verification_directory(session)


HospitalVerificationDep = Annotated[
    HospitalVerificationDirectoryService, Depends(get_hospital_verification)
]
