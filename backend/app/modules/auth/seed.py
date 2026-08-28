"""Synthetic-identity helper for the seed system (auth owns the ``users`` table).

Synthetic users carry clearly-fake provider subjects (``synthetic:`` prefix) that no real
Firebase account can ever present, so they can never authenticate — they exist purely as
demo data rows (CLAUDE.md hard rule: demo/seed data must be clearly synthetic). No claims
are provisioned (there is no provider subject to stamp them on).
"""

from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.domain import Role
from app.modules.auth.models import User
from app.modules.auth.repository import UserRepository

SYNTHETIC_UID_PREFIX: Final = "synthetic:"


async def get_or_create_synthetic_user(
    session: AsyncSession, *, firebase_uid: str, role: Role, email: str | None = None
) -> tuple[User, bool]:
    """Insert-if-absent keyed on ``firebase_uid``; existing rows are never touched.

    Returns ``(user, created)``. Refuses non-synthetic subjects — this helper must never
    be usable to plant a login-capable identity.
    """
    if not firebase_uid.startswith(SYNTHETIC_UID_PREFIX):
        raise ValueError(f"synthetic users must have a '{SYNTHETIC_UID_PREFIX}' firebase_uid")
    users = UserRepository(session)
    existing = await users.get_by_firebase_uid(firebase_uid)
    if existing is not None:
        return existing, False
    user = await users.add(User(firebase_uid=firebase_uid, role=role, email=email))
    return user, True
