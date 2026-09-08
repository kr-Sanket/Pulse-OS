"""PatientService unit tests: registration, idempotency, draw-and-insert, claims."""

import asyncio
from collections.abc import Iterator
from datetime import date
from uuid import UUID, uuid4

import pytest
from app.modules.auth.accounts import UserAccountService
from app.modules.auth.domain import Role
from app.modules.auth.errors import AuthProviderUnavailableError
from app.modules.auth.fake import FakeAuthProvider
from app.modules.auth.provider import VerifiedToken
from app.modules.auth.repository import UserRepository
from app.modules.auth.service import ROLE_CLAIM, USER_ID_CLAIM
from app.modules.patients.errors import (
    HealthIdAllocationError,
    InvalidHealthIdError,
    PatientNotFoundError,
    RegistrationConflictError,
)
from app.modules.patients.health_id import generate_health_id, is_valid_health_id
from app.modules.patients.models import Gender
from app.modules.patients.repository import PatientRepository
from app.modules.patients.service import PatientService
from sqlalchemy.ext.asyncio import AsyncSession

from tests.support import sqlite_session

IDENTITY = VerifiedToken(
    firebase_uid="fb-new",
    claims={"phone_number": "+911234567890", "email": "asha@example.test"},
)


def _service(
    session: AsyncSession,
    provider: FakeAuthProvider,
    health_ids: Iterator[str] | None = None,
) -> PatientService:
    accounts = UserAccountService(UserRepository(session), provider)
    patients = PatientRepository(session)
    if health_ids is None:
        return PatientService(accounts=accounts, patients=patients)
    return PatientService(
        accounts=accounts, patients=patients, health_id_factory=lambda: next(health_ids)
    )


def test_register_creates_user_patient_and_provisions_claims() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            provider = FakeAuthProvider()
            outcome = await _service(session, provider).register(
                IDENTITY, full_name="Asha Rao", date_of_birth=None, gender=None
            )

            assert outcome.created is True
            assert is_valid_health_id(outcome.patient.health_id)

            user = await UserRepository(session).get_by_firebase_uid("fb-new")
            assert user is not None
            assert user.role is Role.PATIENT
            assert user.phone == "+911234567890"  # verified contact points from the token
            assert user.email == "asha@example.test"

            claims = provider.custom_claims["fb-new"]
            assert claims[ROLE_CLAIM] == "PATIENT"
            assert UUID(str(claims[USER_ID_CLAIM])) == user.id

    asyncio.run(scenario())


def test_second_registration_is_idempotent_and_reprovisions_claims() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            provider = FakeAuthProvider()
            service = _service(session, provider)
            first = await service.register(
                IDENTITY, full_name="Asha Rao", date_of_birth=None, gender=None
            )
            provider.custom_claims.clear()  # simulate a lost earlier claim write

            second = await service.register(
                IDENTITY, full_name="Different Name", date_of_birth=None, gender=None
            )

            assert second.created is False
            assert second.patient.health_id == first.patient.health_id
            assert second.patient.full_name == "Asha Rao"  # no silent profile rewrite
            assert provider.custom_claims["fb-new"][ROLE_CLAIM] == "PATIENT"  # healed

    asyncio.run(scenario())


def test_register_conflicts_when_account_has_another_role() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            provider = FakeAuthProvider()
            accounts = UserAccountService(UserRepository(session), provider)
            await accounts.create_user(firebase_uid="fb-new", role=Role.DOCTOR)

            with pytest.raises(RegistrationConflictError):
                await _service(session, provider).register(
                    IDENTITY, full_name="Asha Rao", date_of_birth=None, gender=None
                )

    asyncio.run(scenario())


def test_health_id_collision_triggers_redraw() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            provider = FakeAuthProvider()
            taken, fresh = "PHI-IND-2026-7K3M99X", "PHI-IND-2026-TNE7WRA"
            # Occupy `taken` under a different account.
            other = VerifiedToken(firebase_uid="fb-other", claims={})
            await _service(session, provider, iter([taken])).register(
                other, full_name="First", date_of_birth=None, gender=None
            )

            outcome = await _service(session, provider, iter([taken, taken, fresh])).register(
                IDENTITY, full_name="Asha Rao", date_of_birth=None, gender=None
            )
            assert outcome.patient.health_id == fresh  # drew twice into the collision

    asyncio.run(scenario())


def test_health_id_exhaustion_raises() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            provider = FakeAuthProvider()
            taken = "PHI-IND-2026-7K3M99X"
            other = VerifiedToken(firebase_uid="fb-other", claims={})
            await _service(session, provider, iter([taken])).register(
                other, full_name="First", date_of_birth=None, gender=None
            )

            always_taken = _service(session, provider, iter([taken] * 100))
            with pytest.raises(HealthIdAllocationError):
                await always_taken.register(
                    IDENTITY, full_name="Asha Rao", date_of_birth=None, gender=None
                )

    asyncio.run(scenario())


def test_claim_provisioning_failure_propagates() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            provider = FakeAuthProvider()
            provider.set_claims_error = AuthProviderUnavailableError()
            with pytest.raises(AuthProviderUnavailableError):
                await _service(session, provider).register(
                    IDENTITY, full_name="Asha Rao", date_of_birth=None, gender=None
                )

    asyncio.run(scenario())


# -- identity lookup (the hospital upload's confirmation step) --------------------------


def test_lookup_resolves_a_health_id_to_its_patient() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            service = _service(session, FakeAuthProvider())
            registered = await service.register(
                IDENTITY, full_name="Asha Rao", date_of_birth=None, gender=None
            )

            found = await service.lookup_by_health_id(registered.patient.health_id)

            assert found.id == registered.patient.id
            assert found.full_name == "Asha Rao"

    asyncio.run(scenario())


def test_lookup_normalises_the_health_id_as_typed_at_a_desk() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            service = _service(session, FakeAuthProvider())
            registered = await service.register(
                IDENTITY, full_name="Asha Rao", date_of_birth=None, gender=None
            )
            typed = f"  {registered.patient.health_id.lower()}  "

            found = await service.lookup_by_health_id(typed)

            assert found.health_id == registered.patient.health_id

    asyncio.run(scenario())


def test_lookup_rejects_a_malformed_health_id_before_touching_the_database() -> None:
    """ADR-012's check character is offline typo detection; running it first means a
    mistyped ID is reported as malformed rather than as a patient who does not exist."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            service = _service(session, FakeAuthProvider())

            for candidate in ("", "nonsense", "PHI-IND-2026-AAAAAAA", "PHI-IND-26-7K3M99X"):
                with pytest.raises(InvalidHealthIdError):
                    await service.lookup_by_health_id(candidate)

    asyncio.run(scenario())


def test_lookup_raises_not_found_for_a_well_formed_but_unissued_health_id() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            service = _service(session, FakeAuthProvider())
            unissued = generate_health_id()

            with pytest.raises(PatientNotFoundError):
                await service.lookup_by_health_id(unissued)

    asyncio.run(scenario())


def test_lookup_says_nothing_about_what_the_caller_may_do() -> None:
    """The service answers identity only. Authorization is the router's role gate and, for
    the upload that follows, the records module's own rules — this returns the same row to
    anyone who reaches it, which is why the role gate above it carries the weight."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            service = _service(session, FakeAuthProvider())
            registered = await service.register(
                IDENTITY, full_name="Asha Rao", date_of_birth=None, gender=None
            )

            found = await service.lookup_by_health_id(registered.patient.health_id)

            assert not hasattr(found, "permissions")
            assert found.health_id == registered.patient.health_id

    asyncio.run(scenario())


# -- profile editing --------------------------------------------------------------------


async def _registered(
    session: AsyncSession, provider: FakeAuthProvider
) -> tuple[PatientService, UUID]:
    """A registered patient, and the user id everything below is scoped by."""
    service = _service(session, provider)
    outcome = await service.register(
        IDENTITY, full_name="Asha Rao", date_of_birth=date(1990, 5, 4), gender=Gender.FEMALE
    )
    return service, outcome.patient.user_id


def test_an_omitted_field_is_left_alone() -> None:
    """Partial semantics: naming one field must not blank the others."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            service, user_id = await _registered(session, FakeAuthProvider())

            updated = await service.update_profile(user_id, full_name="Asha Sharma")

            assert updated.full_name == "Asha Sharma"
            assert updated.date_of_birth == date(1990, 5, 4)
            assert updated.gender is Gender.FEMALE

    asyncio.run(scenario())


def test_an_explicit_none_clears_a_nullable_field() -> None:
    """The distinction the sentinel exists for: ``None`` is an instruction, not an absence."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            service, user_id = await _registered(session, FakeAuthProvider())

            updated = await service.update_profile(user_id, date_of_birth=None, gender=None)

            assert updated.date_of_birth is None
            assert updated.gender is None
            assert updated.full_name == "Asha Rao"  # untouched

    asyncio.run(scenario())


def test_updating_nothing_changes_nothing() -> None:
    """All three sentinels: a service call that names no field is a no-op, not a wipe."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            service, user_id = await _registered(session, FakeAuthProvider())

            updated = await service.update_profile(user_id)

            assert updated.full_name == "Asha Rao"
            assert updated.date_of_birth == date(1990, 5, 4)
            assert updated.gender is Gender.FEMALE

    asyncio.run(scenario())


def test_the_identity_columns_are_never_touched_by_an_edit() -> None:
    """The Health ID, the owning user and the creation instant are not assignable through
    this path — there is no argument that reaches them."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            service, user_id = await _registered(session, FakeAuthProvider())
            before = await service.get_profile(user_id)
            assert before is not None
            health_id, patient_id, created_at = before.health_id, before.id, before.created_at

            updated = await service.update_profile(
                user_id, full_name="Renamed", date_of_birth=None, gender=Gender.OTHER
            )

            assert updated.health_id == health_id
            assert updated.id == patient_id
            assert updated.created_at == created_at
            assert updated.user_id == user_id

    asyncio.run(scenario())


def test_editing_an_absent_profile_is_refused() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            service = _service(session, FakeAuthProvider())
            with pytest.raises(PatientNotFoundError):
                await service.update_profile(uuid4(), full_name="Nobody")

    asyncio.run(scenario())


def test_one_patients_edit_cannot_reach_another() -> None:
    """Ownership is the signature: the row comes from the authenticated user id, and no
    argument names a patient."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            provider = FakeAuthProvider()
            service, first_user = await _registered(session, provider)
            second = await service.register(
                VerifiedToken(firebase_uid="fb-second", claims={"email": "b@example.test"}),
                full_name="Bharat Singh",
                date_of_birth=None,
                gender=None,
            )

            await service.update_profile(first_user, full_name="Only Mine")

            other = await service.get_profile(second.patient.user_id)
            assert other is not None
            assert other.full_name == "Bharat Singh"

    asyncio.run(scenario())
