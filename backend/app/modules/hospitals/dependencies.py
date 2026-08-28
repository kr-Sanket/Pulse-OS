"""Hospitals module dependency wiring (composition only — no logic)."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.modules.hospitals.repository import HospitalRepository
from app.modules.hospitals.service import HospitalService


def get_hospital_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> HospitalService:
    return HospitalService(hospitals=HospitalRepository(session))


HospitalServiceDep = Annotated[HospitalService, Depends(get_hospital_service)]
