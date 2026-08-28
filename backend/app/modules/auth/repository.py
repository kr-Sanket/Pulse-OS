"""Persistence for auth-owned tables. Pure persistence — no business rules here.

Repositories flush inside savepoints and translate ``IntegrityError`` into domain errors;
transaction commit/rollback belongs to the request scope (app/core/db.get_db_session).
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.errors import DuplicateUserError
from app.modules.auth.models import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_firebase_uid(self, firebase_uid: str) -> User | None:
        result = await self._session.execute(select(User).where(User.firebase_uid == firebase_uid))
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def add(self, user: User) -> User:
        """Flush a new user; raises ``DuplicateUserError`` on a firebase_uid collision."""
        try:
            async with self._session.begin_nested():
                self._session.add(user)
                await self._session.flush()
        except IntegrityError as exc:
            raise DuplicateUserError() from exc
        return user
