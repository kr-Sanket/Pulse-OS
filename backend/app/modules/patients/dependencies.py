"""Patients module dependency wiring (composition only — no logic)."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.modules.auth.accounts import UserAccountService
from app.modules.auth.dependencies import get_user_account_service
from app.modules.patients.repository import PatientRepository
from app.modules.patients.service import PatientService


def get_patient_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    accounts: Annotated[UserAccountService, Depends(get_user_account_service)],
) -> PatientService:
    # Both depend on get_db_session; FastAPI caches it per request, so the account
    # service and the patient repository share one session/transaction.
    return PatientService(accounts=accounts, patients=PatientRepository(session))


PatientServiceDep = Annotated[PatientService, Depends(get_patient_service)]
