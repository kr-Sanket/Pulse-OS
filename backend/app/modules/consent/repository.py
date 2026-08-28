"""Persistence for consent-owned tables. Pure persistence — no business rules here.

Flushes run inside savepoints; ``IntegrityError`` becomes a domain error.
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.consent.errors import ConsentError
from app.modules.consent.models import (
    AccessRequest,
    AccessRequestCategory,
    ConsentDecision,
    ConsentGrant,
    RequestStatus,
)


class ConsentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_access_request(
        self, request: AccessRequest, category_ids: Sequence[UUID]
    ) -> AccessRequest:
        try:
            async with self._session.begin_nested():
                self._session.add(request)
                await self._session.flush()
                for cat_id in category_ids:
                    assoc = AccessRequestCategory(request_id=request.id, category_id=cat_id)
                    self._session.add(assoc)
                await self._session.flush()
        except IntegrityError as exc:
            raise ConsentError("Failed to persist access request.") from exc
        return request

    async def get_access_request(self, id: UUID) -> AccessRequest | None:
        return await self._session.get(AccessRequest, id)

    async def get_request_category_ids(self, request_id: UUID) -> Sequence[UUID]:
        result = await self._session.execute(
            select(AccessRequestCategory.category_id).where(
                AccessRequestCategory.request_id == request_id
            )
        )
        return result.scalars().all()

    async def list_requests_for_patient(
        self, patient_id: UUID, status: RequestStatus | None = None
    ) -> Sequence[AccessRequest]:
        query = select(AccessRequest).where(AccessRequest.patient_id == patient_id)
        if status is not None:
            query = query.where(AccessRequest.status == status)
        query = query.order_by(AccessRequest.created_at.desc())
        result = await self._session.execute(query)
        return result.scalars().all()

    async def list_requests_for_doctor(
        self, doctor_id: UUID, status: RequestStatus | None = None
    ) -> Sequence[AccessRequest]:
        query = select(AccessRequest).where(AccessRequest.doctor_id == doctor_id)
        if status is not None:
            query = query.where(AccessRequest.status == status)
        query = query.order_by(AccessRequest.created_at.desc())
        result = await self._session.execute(query)
        return result.scalars().all()

    async def update_request_status(self, id: UUID, status: RequestStatus) -> AccessRequest | None:
        request = await self.get_access_request(id)
        if request is None:
            return None
        request.status = status
        await self._session.flush()
        return request

    async def add_decisions(
        self, decisions: Sequence[ConsentDecision]
    ) -> Sequence[ConsentDecision]:
        try:
            async with self._session.begin_nested():
                for decision in decisions:
                    self._session.add(decision)
                await self._session.flush()
        except IntegrityError as exc:
            raise ConsentError("Failed to persist consent decisions.") from exc
        return decisions

    async def list_decisions_for_patient(self, patient_id: UUID) -> Sequence[ConsentDecision]:
        query = (
            select(ConsentDecision)
            .where(ConsentDecision.patient_id == patient_id)
            .order_by(ConsentDecision.decided_at.desc())
        )
        result = await self._session.execute(query)
        return result.scalars().all()

    async def list_decisions_for_request(self, request_id: UUID) -> Sequence[ConsentDecision]:
        query = (
            select(ConsentDecision)
            .where(ConsentDecision.request_id == request_id)
            .order_by(ConsentDecision.decided_at.asc())
        )
        result = await self._session.execute(query)
        return result.scalars().all()

    async def add_grant(self, grant: ConsentGrant) -> ConsentGrant:
        try:
            async with self._session.begin_nested():
                self._session.add(grant)
                await self._session.flush()
        except IntegrityError as exc:
            raise ConsentError("Failed to persist consent grant.") from exc
        return grant

    async def get_active_grant(
        self,
        patient_id: UUID,
        doctor_id: UUID,
        category_id: UUID,
        as_of: datetime,
    ) -> ConsentGrant | None:
        """Fetch active grant (revoked_at is null and expires_at > as_of) via composite index."""
        query = select(ConsentGrant).where(
            ConsentGrant.patient_id == patient_id,
            ConsentGrant.doctor_id == doctor_id,
            ConsentGrant.category_id == category_id,
            ConsentGrant.revoked_at.is_(None),
            ConsentGrant.expires_at > as_of,
        )
        result = await self._session.execute(query)
        return result.scalars().first()

    async def list_active_grants_for_patient(
        self, patient_id: UUID, as_of: datetime
    ) -> Sequence[ConsentGrant]:
        query = (
            select(ConsentGrant)
            .where(
                ConsentGrant.patient_id == patient_id,
                ConsentGrant.revoked_at.is_(None),
                ConsentGrant.expires_at > as_of,
            )
            .order_by(ConsentGrant.granted_at.desc())
        )
        result = await self._session.execute(query)
        return result.scalars().all()

    async def list_active_grants_for_doctor(
        self, doctor_id: UUID, as_of: datetime
    ) -> Sequence[ConsentGrant]:
        query = (
            select(ConsentGrant)
            .where(
                ConsentGrant.doctor_id == doctor_id,
                ConsentGrant.revoked_at.is_(None),
                ConsentGrant.expires_at > as_of,
            )
            .order_by(ConsentGrant.granted_at.desc())
        )
        result = await self._session.execute(query)
        return result.scalars().all()

    async def deactivate_existing_active_grants(
        self,
        patient_id: UUID,
        doctor_id: UUID,
        category_id: UUID,
        superseded_at: datetime,
    ) -> None:
        """Deactivate prior active grants when a fresh grant is issued for the same scope."""
        await self._session.execute(
            update(ConsentGrant)
            .where(
                ConsentGrant.patient_id == patient_id,
                ConsentGrant.doctor_id == doctor_id,
                ConsentGrant.category_id == category_id,
                ConsentGrant.revoked_at.is_(None),
            )
            .values(revoked_at=superseded_at)
        )
        await self._session.flush()

    async def revoke_grant(
        self,
        patient_id: UUID,
        doctor_id: UUID,
        category_id: UUID,
        revoked_at: datetime,
    ) -> ConsentGrant | None:
        active = await self.get_active_grant(patient_id, doctor_id, category_id, as_of=revoked_at)
        if active is None:
            return None
        active.revoked_at = revoked_at
        await self._session.flush()
        return active
