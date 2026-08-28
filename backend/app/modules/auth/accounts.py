"""User-account service — the auth module's interface for other modules.

Module isolation (docs/SYSTEM_ARCHITECTURE.md rule 1): the ``users`` table is auth's;
other modules provision and look up identities through this service, never by touching
the table or the provider. Claim names stay confined to the auth module.
"""

from uuid import UUID

from app.modules.auth.domain import Role
from app.modules.auth.models import User
from app.modules.auth.provider import AuthenticationProvider
from app.modules.auth.repository import UserRepository
from app.modules.auth.service import ROLE_CLAIM, USER_ID_CLAIM


class UserAccountService:
    def __init__(self, users: UserRepository, provider: AuthenticationProvider) -> None:
        self._users = users
        self._provider = provider

    async def get_by_firebase_uid(self, firebase_uid: str) -> User | None:
        return await self._users.get_by_firebase_uid(firebase_uid)

    async def create_user(
        self, *, firebase_uid: str, role: Role, phone: str | None = None, email: str | None = None
    ) -> User:
        """Flush a new identity row; raises ``DuplicateUserError`` if the subject exists."""
        return await self._users.add(
            User(firebase_uid=firebase_uid, role=role, phone=phone, email=email)
        )

    async def provision_claims(self, firebase_uid: str, *, role: Role, user_id: UUID) -> None:
        """Stamp the PulseOS claims onto the provider subject (ADR-011: claims carry the
        role). Clients receive them on their next token refresh. Idempotent — safe to
        re-run on repeated registration attempts."""
        await self._provider.set_custom_claims(
            firebase_uid, {ROLE_CLAIM: role.value, USER_ID_CLAIM: str(user_id)}
        )
