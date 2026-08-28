"""Hospital domain and service unit tests."""

import asyncio
from uuid import uuid4

import pytest
from app.modules.hospitals.errors import DuplicateHospitalIdError, HospitalValidationError
from app.modules.hospitals.models import HospitalStatus
from app.modules.hospitals.repository import HospitalRepository
from app.modules.hospitals.service import HospitalService

from tests.support import sqlite_session


def test_create_hospital_success() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            service = HospitalService(HospitalRepository(session))
            hospital = await service.create_hospital(
                hospital_id="HID-0001",
                name="Tata Main Hospital",
                address="C Road, Northern Town, Jamshedpur",
            )
            assert hospital.id is not None
            assert hospital.hospital_id == "HID-0001"
            assert hospital.name == "Tata Main Hospital"
            assert hospital.address == "C Road, Northern Town, Jamshedpur"
            assert hospital.status is HospitalStatus.PENDING

    asyncio.run(scenario())


def test_create_hospital_with_status_verified() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            service = HospitalService(HospitalRepository(session))
            hospital = await service.create_hospital(
                hospital_id="HID-0002",
                name="CMC Vellore",
                address="Ida Scudder Road, Vellore",
                status=HospitalStatus.VERIFIED,
            )
            assert hospital.status is HospitalStatus.VERIFIED

    asyncio.run(scenario())


def test_get_hospital_by_id_and_hospital_id() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            service = HospitalService(HospitalRepository(session))
            created = await service.create_hospital(
                hospital_id="HID-0003",
                name="Apollo Hospital",
            )
            by_id = await service.get_hospital(created.id)
            assert by_id is not None
            assert by_id.name == "Apollo Hospital"

            by_hid = await service.get_by_hospital_id("HID-0003")
            assert by_hid is not None
            assert by_hid.id == created.id

            assert await service.get_hospital(uuid4()) is None
            assert await service.get_by_hospital_id("HID-UNKNOWN") is None

    asyncio.run(scenario())


def test_duplicate_hospital_id_raises_error() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            service = HospitalService(HospitalRepository(session))
            await service.create_hospital(
                hospital_id="HID-0001",
                name="Hospital A",
            )
            with pytest.raises(DuplicateHospitalIdError):
                await service.create_hospital(
                    hospital_id="HID-0001",
                    name="Hospital B",
                )

    asyncio.run(scenario())


def test_hospital_validation_errors() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            service = HospitalService(HospitalRepository(session))
            with pytest.raises(HospitalValidationError, match="Hospital ID"):
                await service.create_hospital(
                    hospital_id="   ",
                    name="Valid Name",
                )
            with pytest.raises(HospitalValidationError, match="Hospital name"):
                await service.create_hospital(
                    hospital_id="HID-0001",
                    name="   ",
                )

    asyncio.run(scenario())


def test_list_hospitals() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            service = HospitalService(HospitalRepository(session))
            await service.create_hospital(hospital_id="HID-B", name="Hospital Bravo")
            await service.create_hospital(hospital_id="HID-A", name="Hospital Alpha")

            hospitals = await service.list_hospitals()
            assert len(hospitals) == 2
            # Ordered by name
            assert hospitals[0].name == "Hospital Alpha"
            assert hospitals[1].name == "Hospital Bravo"

    asyncio.run(scenario())
