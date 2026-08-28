"""Records module dependency wiring (composition only — no logic)."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.modules.doctors.dependencies import get_doctor_service
from app.modules.doctors.service import DoctorService
from app.modules.hospitals.dependencies import get_hospital_service
from app.modules.hospitals.service import HospitalService
from app.modules.patients.dependencies import get_patient_service
from app.modules.patients.service import PatientService
from app.modules.records.repository import (
    MedicalRecordRepository,
    RecordCategoryRepository,
)
from app.modules.records.service import RecordService


def get_record_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    patients: Annotated[PatientService, Depends(get_patient_service)],
    hospitals: Annotated[HospitalService, Depends(get_hospital_service)],
    doctors: Annotated[DoctorService, Depends(get_doctor_service)],
) -> RecordService:
    return RecordService(
        records=MedicalRecordRepository(session),
        categories=RecordCategoryRepository(session),
        patients=patients,
        hospitals=hospitals,
        doctors=doctors,
    )


RecordServiceDep = Annotated[RecordService, Depends(get_record_service)]
