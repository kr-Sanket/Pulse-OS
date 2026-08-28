"""Audit module dependency wiring (composition only — no logic)."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.modules.audit.anchor import DbAuditAnchor
from app.modules.audit.repository import AuditEventRepository
from app.modules.audit.service import AuditService
from app.modules.auth.accounts import UserAccountService
from app.modules.auth.dependencies import get_user_account_service
from app.modules.patients.dependencies import get_patient_service
from app.modules.patients.service import PatientService


def get_audit_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    accounts: Annotated[UserAccountService, Depends(get_user_account_service)],
    patients: Annotated[PatientService, Depends(get_patient_service)],
) -> AuditService:
    return AuditService(
        audit=AuditEventRepository(session),
        accounts=accounts,
        patients=patients,
        anchor=DbAuditAnchor(),
    )


AuditServiceDep = Annotated[AuditService, Depends(get_audit_service)]
