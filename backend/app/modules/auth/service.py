"""Auth domain service: header parsing, token verification, claim → identity mapping.

Framework-free by architecture rule (docs/SYSTEM_ARCHITECTURE.md): no FastAPI imports
here. The service raises domain errors; the dependency layer owns HTTP translation.
"""

from uuid import UUID

from app.modules.auth.domain import AuthenticatedUser, Role
from app.modules.auth.errors import (
    MalformedAuthorizationError,
    MissingCredentialsError,
    UnprovisionedAccountError,
)
from app.modules.auth.provider import AuthenticationProvider, VerifiedToken

# PulseOS custom claims, set by the backend during onboarding (M0.3 Part 3, ADR-011:
# "custom claims carry the role"). Namespaced because Firebase reserves bare names such
# as ``user_id`` inside ID tokens.
ROLE_CLAIM = "pulseos_role"
USER_ID_CLAIM = "pulseos_user_id"

_BEARER_SCHEME = "bearer"


class AuthService:
    """Turns an Authorization header into an ``AuthenticatedUser`` or a domain error."""

    def __init__(self, provider: AuthenticationProvider) -> None:
        self._provider = provider

    async def verify_credentials(self, authorization: str | None) -> VerifiedToken:
        """Header parsing + token verification only — no PulseOS claims required.

        This is the pre-registration identity: authentic Firebase subject, possibly
        not yet provisioned (registration consumes exactly this state)."""
        token = _extract_bearer_token(authorization)
        return await self._provider.verify_id_token(token)

    async def authenticate(self, authorization: str | None) -> AuthenticatedUser:
        return _to_authenticated_user(await self.verify_credentials(authorization))


def _extract_bearer_token(authorization: str | None) -> str:
    if authorization is None or not authorization.strip():
        raise MissingCredentialsError()
    scheme, separator, token = authorization.strip().partition(" ")
    token = token.strip()
    if scheme.lower() != _BEARER_SCHEME or not separator or not token or " " in token:
        raise MalformedAuthorizationError()
    return token


def _to_authenticated_user(verified: VerifiedToken) -> AuthenticatedUser:
    role_claim = verified.claims.get(ROLE_CLAIM)
    user_id_claim = verified.claims.get(USER_ID_CLAIM)
    if not isinstance(role_claim, str) or not isinstance(user_id_claim, str):
        raise UnprovisionedAccountError()
    try:
        role = Role(role_claim)
        user_id = UUID(user_id_claim)
    except ValueError as exc:
        raise UnprovisionedAccountError() from exc
    return AuthenticatedUser(user_id=user_id, firebase_uid=verified.firebase_uid, role=role)
