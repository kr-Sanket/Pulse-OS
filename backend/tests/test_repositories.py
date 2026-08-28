"""Repository CRUD + integrity-error translation, against in-memory SQLite."""

import asyncio
from uuid import uuid4

import pytest
from app.modules.auth.domain import Role
from app.modules.auth.errors import DuplicateUserError
from app.modules.auth.models import User
from app.modules.auth.repository import UserRepository
from app.modules.patients.errors import DuplicateHealthIdError, DuplicatePatientError
from app.modules.patients.models import Patient
from app.modules.patients.repository import PatientRepository

from tests.support import sqlite_session


def test_user_repository_add_and_lookups() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            repo = UserRepository(session)
            user = await repo.add(
                User(firebase_uid="fb-1", role=Role.PATIENT, phone="+911234", email="a@b.c")
            )
            assert user.id is not None

            by_uid = await repo.get_by_firebase_uid("fb-1")
            assert by_uid is not None and by_uid.id == user.id
            by_id = await repo.get_by_id(user.id)
            assert by_id is not None and by_id.firebase_uid == "fb-1"
            assert await repo.get_by_firebase_uid("fb-unknown") is None

    asyncio.run(scenario())


def test_user_repository_translates_duplicate_firebase_uid() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            repo = UserRepository(session)
            await repo.add(User(firebase_uid="fb-1", role=Role.PATIENT))
            with pytest.raises(DuplicateUserError):
                await repo.add(User(firebase_uid="fb-1", role=Role.PATIENT))
            # The savepoint contained the failure: the session must still be usable.
            await repo.add(User(firebase_uid="fb-2", role=Role.DOCTOR))

    asyncio.run(scenario())


def test_patient_repository_add_and_lookup() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            user = await UserRepository(session).add(User(firebase_uid="fb-1", role=Role.PATIENT))
            repo = PatientRepository(session)
            patient = await repo.add(
                Patient(user_id=user.id, health_id="PHI-IND-2026-7K3M99X", full_name="Asha Rao")
            )
            found = await repo.get_by_user_id(user.id)
            assert found is not None and found.id == patient.id
            assert await repo.get_by_user_id(uuid4()) is None

    asyncio.run(scenario())


def test_patient_repository_distinguishes_unique_violations() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            users = UserRepository(session)
            first = await users.add(User(firebase_uid="fb-1", role=Role.PATIENT))
            second = await users.add(User(firebase_uid="fb-2", role=Role.PATIENT))
            repo = PatientRepository(session)
            await repo.add(
                Patient(user_id=first.id, health_id="PHI-IND-2026-7K3M99X", full_name="A")
            )

            with pytest.raises(DuplicateHealthIdError):
                await repo.add(
                    Patient(user_id=second.id, health_id="PHI-IND-2026-7K3M99X", full_name="B")
                )
            with pytest.raises(DuplicatePatientError):
                await repo.add(
                    Patient(user_id=first.id, health_id="PHI-IND-2026-TNE7WRA", full_name="C")
                )
            # Session still usable after both contained failures.
            await repo.add(
                Patient(user_id=second.id, health_id="PHI-IND-2026-TNE7WRA", full_name="B")
            )

    asyncio.run(scenario())
