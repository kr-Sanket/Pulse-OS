"""Persistence for audit-owned tables. Pure persistence — append-only design.

Audit events are immutable: no generic update or delete operations exist.
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.errors import AuditError
from app.modules.audit.models import AnchorStatus, AuditEvent


class AuditEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, event: AuditEvent) -> AuditEvent:
        """Persist a new append-only audit event."""
        try:
            async with self._session.begin_nested():
                self._session.add(event)
                await self._session.flush()
        except IntegrityError as exc:
            raise AuditError("Failed to persist audit event.") from exc
        return event

    async def get_by_id(self, id: UUID) -> AuditEvent | None:
        return await self._session.get(AuditEvent, id)

    async def list_by_patient_id(
        self, patient_id: UUID, *, limit: int = 100, offset: int = 0
    ) -> Sequence[AuditEvent]:
        query = (
            select(AuditEvent)
            .where(AuditEvent.patient_id == patient_id)
            .order_by(AuditEvent.timestamp.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(query)
        return result.scalars().all()

    async def list_by_actor_id(
        self, actor_id: UUID, *, limit: int = 100, offset: int = 0
    ) -> Sequence[AuditEvent]:
        query = (
            select(AuditEvent)
            .where(AuditEvent.actor_id == actor_id)
            .order_by(AuditEvent.timestamp.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(query)
        return result.scalars().all()

    async def count_by_patient_id(self, patient_id: UUID) -> int:
        query = select(func.count(AuditEvent.id)).where(AuditEvent.patient_id == patient_id)
        result = await self._session.execute(query)
        return result.scalar_one()

    async def update_anchor_status(
        self,
        id: UUID,
        status: AnchorStatus,
        tx_hash: str | None = None,
        anchored_at: datetime | None = None,
    ) -> AuditEvent | None:
        """Update asynchronous anchor status and transaction receipt."""
        event = await self.get_by_id(id)
        if event is None:
            return None
        event.anchor_status = status
        event.anchor_tx_hash = tx_hash
        event.anchored_at = anchored_at
        await self._session.flush()
        return event
