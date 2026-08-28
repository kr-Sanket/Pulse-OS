"""Hospitals domain service: organization registration and lookup.

Framework-free; owns no transaction — the request scope commits (app/core/db.py).
"""

from collections.abc import Sequence
from uuid import UUID

from app.modules.hospitals.errors import (
    HospitalValidationError,
)
from app.modules.hospitals.models import Hospital, HospitalStatus
from app.modules.hospitals.repository import HospitalRepository


class HospitalService:
    def __init__(self, hospitals: HospitalRepository) -> None:
        self._hospitals = hospitals

    async def create_hospital(
        self,
        *,
        hospital_id: str,
        name: str,
        address: str | None = None,
        status: HospitalStatus = HospitalStatus.PENDING,
    ) -> Hospital:
        """Create a new care organization (Hospital)."""
        clean_hid = hospital_id.strip()
        clean_name = name.strip()
        clean_address = address.strip() if address is not None else None

        if not clean_hid:
            raise HospitalValidationError("Hospital ID must not be blank.")
        if not clean_name:
            raise HospitalValidationError("Hospital name must not be blank.")

        hospital = Hospital(
            hospital_id=clean_hid,
            name=clean_name,
            address=clean_address,
            status=status,
        )
        return await self._hospitals.add(hospital)

    async def get_hospital(self, id: UUID) -> Hospital | None:
        return await self._hospitals.get_by_id(id)

    async def get_by_hospital_id(self, hospital_id: str) -> Hospital | None:
        return await self._hospitals.get_by_hospital_id(hospital_id.strip())

    async def list_hospitals(self) -> Sequence[Hospital]:
        return await self._hospitals.list_all()
