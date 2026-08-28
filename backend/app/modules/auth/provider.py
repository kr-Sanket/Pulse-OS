"""Authentication provider port (ADR-011).

Every external identity provider is hidden behind ``AuthenticationProvider``. The rest of
the application sees only ``VerifiedToken`` and the domain errors — never provider SDK
types. Swapping Firebase for Keycloak later is a new implementation of this interface.
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VerifiedToken:
    """The provider-agnostic result of a successful token verification."""

    firebase_uid: str
    claims: Mapping[str, object]

    def string_claim(self, key: str, *, max_length: int) -> str | None:
        """A verified string claim (e.g. ``email``, ``phone_number``), or None.

        Registration flows copy verified contact points from the token
        (docs/DOMAIN_MODEL.md: User carries them); anything unexpected — wrong type,
        empty, oversized — is dropped rather than trusted.
        """
        value = self.claims.get(key)
        if isinstance(value, str) and 0 < len(value) <= max_length:
            return value
        return None


class AuthenticationProvider(ABC):
    """Port for verifying bearer tokens issued by the identity provider."""

    @abstractmethod
    async def verify_id_token(self, token: str) -> VerifiedToken:
        """Verify signature, expiry, and audience; return the decoded identity.

        Raises ``InvalidTokenError`` / ``ExpiredTokenError`` for client-side problems and
        ``AuthProviderUnavailableError`` for server-side ones. Never raises SDK exceptions.
        """

    @abstractmethod
    async def set_custom_claims(self, firebase_uid: str, claims: Mapping[str, object]) -> None:
        """Replace the subject's custom claims (they appear in tokens after refresh).

        Raises ``InvalidTokenError`` if the subject no longer exists and
        ``AuthProviderUnavailableError`` for server-side failures.
        """
