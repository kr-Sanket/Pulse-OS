"""Unit tests for AuthService: header parsing and claim -> identity mapping."""

import asyncio
from uuid import uuid4

import pytest
from app.modules.auth.domain import AuthenticatedUser, Role
from app.modules.auth.errors import (
    ExpiredTokenError,
    InvalidTokenError,
    MalformedAuthorizationError,
    MissingCredentialsError,
    UnprovisionedAccountError,
)
from app.modules.auth.fake import FakeAuthProvider
from app.modules.auth.service import ROLE_CLAIM, USER_ID_CLAIM, AuthService


def _authenticate(provider: FakeAuthProvider, authorization: str | None) -> AuthenticatedUser:
    return asyncio.run(AuthService(provider).authenticate(authorization))


@pytest.mark.parametrize("header", [None, "", "   "])
def test_missing_authorization_header(header: str | None) -> None:
    with pytest.raises(MissingCredentialsError):
        _authenticate(FakeAuthProvider(), header)


@pytest.mark.parametrize(
    "header",
    [
        "Token abc",  # wrong scheme
        "Bearer",  # no token
        "Bearer   ",  # blank token
        "Bearer a b",  # token must not contain spaces
        "abc",  # no scheme at all
    ],
)
def test_malformed_authorization_header(header: str) -> None:
    with pytest.raises(MalformedAuthorizationError):
        _authenticate(FakeAuthProvider(), header)


def test_authenticates_provisioned_user() -> None:
    provider = FakeAuthProvider()
    user_id = uuid4()
    provider.register_user("tok", user_id=user_id, firebase_uid="fb-1", role=Role.PATIENT)

    user = _authenticate(provider, "Bearer tok")

    assert user == AuthenticatedUser(user_id=user_id, firebase_uid="fb-1", role=Role.PATIENT)


def test_bearer_scheme_is_case_insensitive() -> None:
    provider = FakeAuthProvider()
    provider.register_user("tok", user_id=uuid4(), firebase_uid="fb-1", role=Role.DOCTOR)

    assert _authenticate(provider, "bearer tok").role is Role.DOCTOR


def test_unknown_token_is_invalid() -> None:
    with pytest.raises(InvalidTokenError):
        _authenticate(FakeAuthProvider(), "Bearer unknown")


def test_provider_errors_propagate() -> None:
    provider = FakeAuthProvider()
    provider.register_error("tok", ExpiredTokenError())
    with pytest.raises(ExpiredTokenError):
        _authenticate(provider, "Bearer tok")


@pytest.mark.parametrize(
    "claims",
    [
        {},  # nothing provisioned
        {ROLE_CLAIM: "PATIENT"},  # user id missing
        {USER_ID_CLAIM: "8d51a4b2-2cf4-4f5c-9a3a-0d05a2f5e111"},  # role missing
        {ROLE_CLAIM: "SUPERUSER", USER_ID_CLAIM: "8d51a4b2-2cf4-4f5c-9a3a-0d05a2f5e111"},
        {ROLE_CLAIM: "PATIENT", USER_ID_CLAIM: "not-a-uuid"},
        {ROLE_CLAIM: 7, USER_ID_CLAIM: 12},  # non-string claim values
    ],
)
def test_unprovisioned_claims_are_rejected(claims: dict[str, object]) -> None:
    provider = FakeAuthProvider()
    provider.register_token("tok", firebase_uid="fb-1", claims=claims)
    with pytest.raises(UnprovisionedAccountError):
        _authenticate(provider, "Bearer tok")
