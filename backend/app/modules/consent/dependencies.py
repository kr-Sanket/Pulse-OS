"""Consent module dependency wiring (composition only — no logic)."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.modules.auth.accounts import UserAccountService
from app.modules.auth.dependencies import get_user_account_service
from app.modules.consent.repository import ConsentRepository
from app.modules.consent.service import ConsentService
from app.modules.doctors.dependencies import get_doctor_service
from app.modules.doctors.service import DoctorService
from app.modules.hospitals.dependencies import get_hospital_service
from app.modules.hospitals.service import HospitalService
from app.modules.patients.dependencies import get_patient_service
from app.modules.patients.service import PatientService
from app.modules.records.dependencies import get_record_service
from app.modules.records.service import RecordService


def get_consent_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    accounts: Annotated[UserAccountService, Depends(get_user_account_service)],
    patients: Annotated[PatientService, Depends(get_patient_service)],
    doctors: Annotated[DoctorService, Depends(get_doctor_service)],
    hospitals: Annotated[HospitalService, Depends(get_hospital_service)],
    records: Annotated[RecordService, Depends(get_record_service)],
) -> ConsentService:
    return ConsentService(
        consent=ConsentRepository(session),
        accounts=accounts,
        patients=patients,
        doctors=doctors,
        hospitals=hospitals,
        records=records,
    )


ConsentServiceDep = Annotated[ConsentService, Depends(get_consent_service)]
