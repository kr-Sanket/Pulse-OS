"""In-memory authentication provider for tests and credential-free local development.

Fake implementations of external ports are first-class citizens
(docs/SYSTEM_ARCHITECTURE.md rule 4): tests must never contact Google.
"""

from collections.abc import Mapping
from uuid import UUID

from app.modules.auth.domain import Role
from app.modules.auth.errors import AuthError, InvalidTokenError
from app.modules.auth.provider import AuthenticationProvider, VerifiedToken
from app.modules.auth.service import ROLE_CLAIM, USER_ID_CLAIM


class FakeAuthProvider(AuthenticationProvider):
    """Maps opaque token strings to canned verification results or errors."""

    def __init__(self) -> None:
        self._tokens: dict[str, VerifiedToken] = {}
        self._errors: dict[str, AuthError] = {}
        #: Claims recorded by set_custom_claims, keyed by firebase_uid — assert on this.
        self.custom_claims: dict[str, dict[str, object]] = {}
        #: Set to make every set_custom_claims call raise (failure-path tests).
        self.set_claims_error: AuthError | None = None

    def register_user(self, token: str, *, user_id: UUID, firebase_uid: str, role: Role) -> None:
        """Register a fully provisioned user (role + user id claims present)."""
        self.register_token(
            token,
            firebase_uid=firebase_uid,
            claims={ROLE_CLAIM: role.value, USER_ID_CLAIM: str(user_id)},
        )

    def register_token(
        self, token: str, *, firebase_uid: str, claims: Mapping[str, object]
    ) -> None:
        """Register a token with arbitrary claims (e.g. an unprovisioned account)."""
        self._tokens[token] = VerifiedToken(firebase_uid=firebase_uid, claims=claims)

    def register_error(self, token: str, error: AuthError) -> None:
        """Make verification of ``token`` raise ``error`` (expired, unavailable, ...)."""
        self._errors[token] = error

    async def verify_id_token(self, token: str) -> VerifiedToken:
        if token in self._errors:
            raise self._errors[token]
        try:
            return self._tokens[token]
        except KeyError:
            raise InvalidTokenError() from None

    async def set_custom_claims(self, firebase_uid: str, claims: Mapping[str, object]) -> None:
        if self.set_claims_error is not None:
            raise self.set_claims_error
        self.custom_claims[firebase_uid] = dict(claims)
