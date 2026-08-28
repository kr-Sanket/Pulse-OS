"""FirebaseAuthProvider tests with the SDK fully mocked — no call ever leaves the process.

Covers the SDK-error -> domain-error mapping (docs/SECURITY.md: Firebase errors must not
leak) and the config-failure path.
"""

import asyncio
from collections.abc import Callable

import pytest
from app.core.config import Settings
from app.modules.auth.errors import (
    AuthProviderUnavailableError,
    ExpiredTokenError,
    InvalidTokenError,
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
    def fake_verify(token: str, app: object = None) -> dict[str, object]:
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
