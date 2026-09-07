"""FastAPI dependencies: the single place tokens are verified and roles are gated.

No endpoint verifies tokens manually — everything goes through
``require_authenticated_user`` (authn) / ``require_verified_identity`` (authn without
provisioning, for registration) and ``require_role`` (ADR-013 layer 1). This layer also
owns the domain-error → RFC 7807 translation; HTTP details are already generic, so no
provider internals can leak (docs/SECURITY.md).
"""

import logging
from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.core.ratelimit import RateLimiter, get_rate_limiter
from app.modules.auth.accounts import UserAccountService
from app.modules.auth.domain import AuthenticatedUser, Role
from app.modules.auth.errors import (
    AuthError,
    AuthProviderUnavailableError,
    ExpiredTokenError,
    InvalidTokenError,
    MalformedAuthorizationError,
    MissingCredentialsError,
    UnprovisionedAccountError,
)
from app.modules.auth.provider import AuthenticationProvider, VerifiedToken
from app.modules.auth.repository import UserRepository
from app.modules.auth.service import AuthService

logger = logging.getLogger(__name__)

# RFC 6750: 401 responses advertise the expected scheme.
_CHALLENGE = {"WWW-Authenticate": "Bearer"}
_CHALLENGE_INVALID = {"WWW-Authenticate": 'Bearer error="invalid_token"'}


def to_http_error(exc: AuthError) -> HTTPException:
    """Domain → RFC 7807 translation, shared by every auth-facing dependency/endpoint."""
    if isinstance(exc, MissingCredentialsError):
        return HTTPException(status_code=401, detail="Authentication required.", headers=_CHALLENGE)
    if isinstance(exc, MalformedAuthorizationError):
        return HTTPException(
            status_code=401,
            detail="Malformed Authorization header; expected 'Bearer <token>'.",
            headers=_CHALLENGE,
        )
    if isinstance(exc, ExpiredTokenError):
        return HTTPException(
            status_code=401,
            detail="Authentication token has expired.",
            headers=_CHALLENGE_INVALID,
        )
    if isinstance(exc, InvalidTokenError):
        return HTTPException(
            status_code=401, detail="Invalid authentication token.", headers=_CHALLENGE_INVALID
        )
    if isinstance(exc, UnprovisionedAccountError):
        return HTTPException(status_code=403, detail="Account is not provisioned for PulseOS.")
    if isinstance(exc, AuthProviderUnavailableError):
        return HTTPException(status_code=503, detail="Authentication service is unavailable.")
    # Any AuthError without a specific mapping is a server-side problem, never the caller's.
    return HTTPException(status_code=500, detail="Authentication failed unexpectedly.")


def get_auth_provider(request: Request) -> AuthenticationProvider:
    """The provider chosen at startup (lifespan); tests override this dependency."""
    provider: AuthenticationProvider = request.app.state.auth_provider
    return provider


def get_auth_service(
    provider: Annotated[AuthenticationProvider, Depends(get_auth_provider)],
) -> AuthService:
    return AuthService(provider)


def get_user_account_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    provider: Annotated[AuthenticationProvider, Depends(get_auth_provider)],
) -> UserAccountService:
    """How other modules reach identities — never via auth's table or the provider."""
    return UserAccountService(UserRepository(session), provider)


async def require_verified_identity(
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> VerifiedToken:
    """Authenticate the token WITHOUT requiring PulseOS claims — the registration state."""
    try:
        return await service.verify_credentials(request.headers.get("Authorization"))
    except AuthError as exc:
        raise to_http_error(exc) from exc


async def require_authenticated_user(
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthenticatedUser:
    """Authenticate the request or fail with an RFC 7807 response. Never logs the token."""
    try:
        return await service.authenticate(request.headers.get("Authorization"))
    except AuthError as exc:
        raise to_http_error(exc) from exc


CurrentUser = Annotated[AuthenticatedUser, Depends(require_authenticated_user)]
VerifiedIdentity = Annotated[VerifiedToken, Depends(require_verified_identity)]

RoleDependency = Callable[..., Coroutine[Any, Any, AuthenticatedUser]]


def require_role(*allowed: Role) -> RoleDependency:
    """Build a dependency enforcing ADR-013 layer 1: the caller's role must be allowed.

    Relationship (layer 2) and consent (layer 3) checks are separate, later dependencies —
    a passing role gate alone never grants access to medical content.
    """
    if not allowed:
        raise ValueError("require_role needs at least one role")

    async def role_gate(user: CurrentUser) -> AuthenticatedUser:
        if user.role not in allowed:
            raise HTTPException(status_code=403, detail="Insufficient role for this operation.")
        return user

    return role_gate


RequirePatient = require_role(Role.PATIENT)
RequireDoctor = require_role(Role.DOCTOR)
RequireHospitalAdmin = require_role(Role.HOSPITAL_ADMIN)
RequireSystemAdmin = require_role(Role.SYSTEM_ADMIN)


def rate_limited(bucket: str) -> RoleDependency:
    """Build a dependency that spends one unit of ``bucket`` for the calling user (ADR-024).

    Declared **after** the role gate on a route, so the order is authenticate → authorize →
    limit → service. Three consequences follow from that, all intended:

    * the subject is the caller's PulseOS ``user_id``, which only exists once the token has
      been verified — the reason this is a dependency and not middleware, since Starlette
      middleware runs before any of it;
    * a caller refused by the role gate never reaches the limiter and spends nothing;
    * the limiter runs before the service resolves any Health ID, so a 429 cannot depend on
      whether a patient exists. That property is structural rather than merely tested.

    Every outcome spends quota — a 404 or 422 costs the same as a hit. Counting successes
    alone would leave enumeration unthrottled, since probing an ID that matches nobody is
    precisely the request an attacker makes.

    Returns the caller so the dependency composes like the role gates it sits beside.
    """

    async def limit_gate(
        user: CurrentUser,
        limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    ) -> AuthenticatedUser:
        decision = await limiter.check(bucket, f"u:{user.user_id}")
        if not decision.allowed:
            logger.warning(
                "request rate limited",
                extra={"bucket": bucket, "user_id": str(user.user_id)},
            )
            # Detail and body are identical for every bucket and every caller: a 429 must
            # not become the side channel the limiter exists to close.
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Try again shortly.",
                headers={"Retry-After": str(decision.retry_after_seconds)},
            )
        return user

    return limit_gate
