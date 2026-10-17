"""FirebaseAuthProvider tests with the SDK fully mocked — no call ever leaves the process.

Covers the SDK-error -> domain-error mapping (docs/SECURITY.md: Firebase errors must not
leak) and the config-failure path.
"""

import asyncio
from collections.abc import Callable

import firebase_admin
import pytest
from app.core.config import Settings
from app.modules.auth.errors import (
    AuthProviderUnavailableError,
    ExpiredTokenError,
    InvalidTokenError,
    RevokedTokenError,
    UserDisabledError,
)
from app.modules.auth.firebase import FirebaseAuthProvider
from app.modules.auth.provider import VerifiedToken
from firebase_admin import auth as firebase_auth


def _provider(monkeypatch: pytest.MonkeyPatch) -> FirebaseAuthProvider:
    provider = FirebaseAuthProvider(Settings())
    # Skip real SDK app initialization; verify_id_token is patched per test anyway.
    monkeypatch.setattr(provider, "_get_app", lambda: None)
    return provider


def _patch_verify(
    monkeypatch: pytest.MonkeyPatch, behavior: Callable[[], dict[str, object]]
) -> None:
    def fake_verify(
        token: str, app: object = None, check_revoked: bool = False
    ) -> dict[str, object]:
        return behavior()

    monkeypatch.setattr(firebase_auth, "verify_id_token", fake_verify)


def _verify(provider: FirebaseAuthProvider) -> VerifiedToken:
    return asyncio.run(provider.verify_id_token("some-token"))


def test_returns_uid_and_claims(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(monkeypatch)
    decoded: dict[str, object] = {"uid": "fb-1", "pulseos_role": "PATIENT"}
    _patch_verify(monkeypatch, lambda: decoded)

    verified = _verify(provider)

    assert verified.firebase_uid == "fb-1"
    assert verified.claims == decoded


def test_falls_back_to_sub_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(monkeypatch)
    _patch_verify(monkeypatch, lambda: {"sub": "fb-2"})

    assert _verify(provider).firebase_uid == "fb-2"


def test_missing_uid_is_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(monkeypatch)
    _patch_verify(monkeypatch, lambda: {})

    with pytest.raises(InvalidTokenError):
        _verify(provider)


def _raise(exc: Exception) -> Callable[[], dict[str, object]]:
    def behavior() -> dict[str, object]:
        raise exc

    return behavior


def test_expired_token(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(monkeypatch)
    _patch_verify(monkeypatch, _raise(firebase_auth.ExpiredIdTokenError("expired", None)))

    with pytest.raises(ExpiredTokenError):
        _verify(provider)


@pytest.mark.parametrize(
    "sdk_error",
    [
        firebase_auth.InvalidIdTokenError("bad token"),
        firebase_auth.RevokedIdTokenError("revoked"),
        firebase_auth.UserDisabledError("disabled"),
        ValueError("unparseable"),
    ],
)
def test_client_side_failures_map_to_invalid_token(
    monkeypatch: pytest.MonkeyPatch, sdk_error: Exception
) -> None:
    provider = _provider(monkeypatch)
    _patch_verify(monkeypatch, _raise(sdk_error))

    with pytest.raises(InvalidTokenError):
        _verify(provider)


def test_verify_passes_check_revoked(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(monkeypatch)
    captured: dict[str, object] = {}

    def fake_verify(
        token: str, app: object = None, check_revoked: bool = False
    ) -> dict[str, object]:
        captured["check_revoked"] = check_revoked
        return {"uid": "fb-1"}

    monkeypatch.setattr(firebase_auth, "verify_id_token", fake_verify)
    _verify(provider)
    assert captured.get("check_revoked") is True


def test_revoked_token_error_maps_to_revoked_token(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(monkeypatch)
    _patch_verify(monkeypatch, _raise(firebase_auth.RevokedIdTokenError("revoked")))

    with pytest.raises(RevokedTokenError):
        _verify(provider)


def test_user_disabled_error_maps_to_user_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(monkeypatch)
    _patch_verify(monkeypatch, _raise(firebase_auth.UserDisabledError("disabled")))

    with pytest.raises(UserDisabledError):
        _verify(provider)


def test_certificate_fetch_failure_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(monkeypatch)
    _patch_verify(monkeypatch, _raise(firebase_auth.CertificateFetchError("certs", None)))

    with pytest.raises(AuthProviderUnavailableError):
        _verify(provider)


def test_set_custom_claims_passes_claims_to_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(monkeypatch)
    recorded: dict[str, object] = {}

    def fake_set(uid: str, claims: dict[str, object], app: object = None) -> None:
        recorded["uid"] = uid
        recorded["claims"] = claims

    monkeypatch.setattr(firebase_auth, "set_custom_user_claims", fake_set)
    asyncio.run(provider.set_custom_claims("fb-1", {"pulseos_role": "PATIENT"}))

    assert recorded == {"uid": "fb-1", "claims": {"pulseos_role": "PATIENT"}}


def test_set_custom_claims_for_unknown_subject_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider(monkeypatch)

    def fake_set(uid: str, claims: dict[str, object], app: object = None) -> None:
        raise firebase_auth.UserNotFoundError("gone")

    monkeypatch.setattr(firebase_auth, "set_custom_user_claims", fake_set)
    with pytest.raises(InvalidTokenError):
        asyncio.run(provider.set_custom_claims("fb-1", {}))


def test_set_custom_claims_unexpected_failure_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider(monkeypatch)

    def fake_set(uid: str, claims: dict[str, object], app: object = None) -> None:
        raise ConnectionError("network down")

    monkeypatch.setattr(firebase_auth, "set_custom_user_claims", fake_set)
    with pytest.raises(AuthProviderUnavailableError):
        asyncio.run(provider.set_custom_claims("fb-1", {}))


def test_broken_credentials_config_is_unavailable(tmp_path_factory: pytest.TempPathFactory) -> None:
    # Real _get_app path: a nonexistent service-account file fails initialization
    # locally (no network) and surfaces as a server-side error, not a token error.
    missing = tmp_path_factory.mktemp("creds") / "nonexistent.json"
    provider = FirebaseAuthProvider(Settings(firebase_credentials_file=str(missing)))

    with pytest.raises(AuthProviderUnavailableError):
        _verify(provider)


class _AppWithoutProject:
    """An initialized SDK app that resolved no project — what ADC without
    GOOGLE_CLOUD_PROJECT produces."""

    project_id = None


def test_unresolved_project_is_unavailable_not_an_invalid_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A server with no Firebase project configured must not answer 401.

    The SDK signals it with a bare ValueError, which is also how it reports a malformed
    token, so without the guard in _get_app the caller is told their credentials are bad
    when it is the server that is unconfigured (app/core/config.py promises 503).
    """
    provider = FirebaseAuthProvider(Settings(firebase_credentials_file=None))
    monkeypatch.setattr(
        firebase_admin,
        "initialize_app",
        lambda credential=None, name=None: _AppWithoutProject(),
    )

    with pytest.raises(AuthProviderUnavailableError):
        _verify(provider)
