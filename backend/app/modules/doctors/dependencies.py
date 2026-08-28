"""Doctors module dependency wiring (composition only — no logic)."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.modules.auth.accounts import UserAccountService
from app.modules.auth.dependencies import get_user_account_service
from app.modules.doctors.repository import DoctorRepository
from app.modules.doctors.service import DoctorService
from app.modules.hospitals.dependencies import get_hospital_service
from app.modules.hospitals.service import HospitalService


def get_doctor_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    accounts: Annotated[UserAccountService, Depends(get_user_account_service)],
    hospitals: Annotated[HospitalService, Depends(get_hospital_service)],
) -> DoctorService:
    return DoctorService(
        doctors=DoctorRepository(session),
        accounts=accounts,
        hospitals=hospitals,
    )


DoctorServiceDep = Annotated[DoctorService, Depends(get_doctor_service)]
