"""Auth domain exceptions.

Services and providers raise these; only the FastAPI dependency layer translates them
into RFC 7807 responses (docs/API_GUIDELINES.md: services never construct HTTP responses).
Messages are intentionally generic — provider internals must never reach a client
(docs/SECURITY.md).
"""


class AuthError(Exception):
    """Base class for all authentication/authorization domain errors."""


class MissingCredentialsError(AuthError):
    """No Authorization header was supplied."""


class MalformedAuthorizationError(AuthError):
    """The Authorization header is not a well-formed ``Bearer <token>`` value."""


class InvalidTokenError(AuthError):
    """The token failed verification (bad signature, revoked, disabled, unparseable)."""


class ExpiredTokenError(InvalidTokenError):
    """The token was valid once but has expired — clients should refresh and retry."""


class RevokedTokenError(InvalidTokenError):
    """The token failed verification because it was revoked."""


class UserDisabledError(InvalidTokenError):
    """The account has been disabled in the identity provider."""


class UnprovisionedAccountError(AuthError):
    """The token is authentic but carries no PulseOS role/user claims yet.

    This is the state between Firebase sign-up and PulseOS registration (M0.3 Part 3
    sets the claims during onboarding). Authentication succeeded; authorization fails.
    """


class AccountSuspendedError(AuthError):
    """The PulseOS user account is suspended."""

    code = "account_suspended"


class AccountUnavailableError(AuthError):
    """The PulseOS user record is missing or unavailable."""

    code = "account_unavailable"


class AuthProviderUnavailableError(AuthError):
    """The provider could not be reached or is misconfigured — a server-side problem."""


class DuplicateUserError(AuthError):
    """A user row for this provider subject already exists (unique firebase_uid)."""
