"""Firebase implementation of the authentication port (ADR-011).

This is the ONLY file in the codebase that may import ``firebase_admin``. It maps every
SDK outcome onto the domain errors in ``errors.py`` so no Firebase detail leaks upward
(docs/SECURITY.md: never expose provider errors; tokens are never logged).

Initialization is lazy and happens off the event loop: the API must boot and serve
/health without Firebase credentials — a missing/broken credential surfaces as
``AuthProviderUnavailableError`` on auth attempts only.
"""

import asyncio
import logging
import threading
from collections.abc import Mapping
from pathlib import Path

import firebase_admin
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials as firebase_credentials

from app.core.config import Settings
from app.modules.auth.errors import (
    AuthProviderUnavailableError,
    ExpiredTokenError,
    InvalidTokenError,
)
from app.modules.auth.provider import AuthenticationProvider, VerifiedToken

logger = logging.getLogger("pulseos.auth")

# Named app so we never collide with a default firebase_admin app owned by other tooling.
_FIREBASE_APP_NAME = "pulseos"


def _resolve_credentials_file(path_str: str | None) -> str | None:
    if not path_str:
        return None
    candidate = Path(path_str)
    if candidate.is_file():
        return str(candidate.resolve())
    backend_dir = Path(__file__).resolve().parents[3]
    if (backend_dir / path_str).is_file():
        return str((backend_dir / path_str).resolve())
    repo_root = backend_dir.parent
    if (repo_root / path_str).is_file():
        return str((repo_root / path_str).resolve())
    return path_str


class FirebaseAuthProvider(AuthenticationProvider):
    """Verifies Firebase ID tokens via the Admin SDK (service account or ADC)."""

    def __init__(self, settings: Settings) -> None:
        self._credentials_file = _resolve_credentials_file(settings.firebase_credentials_file)
        self._app: firebase_admin.App | None = None
        self._init_lock = threading.Lock()

    async def verify_id_token(self, token: str) -> VerifiedToken:
        # The SDK verify is blocking (may fetch Google signing certs on cold cache),
        # so it runs in a worker thread instead of on the event loop.
        try:
            claims = await asyncio.to_thread(self._verify_sync, token)
        except AuthProviderUnavailableError:
            raise
        except firebase_auth.ExpiredIdTokenError as exc:
            raise ExpiredTokenError() from exc
        except firebase_auth.InvalidIdTokenError as exc:  # includes RevokedIdTokenError
            raise InvalidTokenError() from exc
        except firebase_auth.UserDisabledError as exc:
            raise InvalidTokenError() from exc
        except ValueError as exc:  # SDK raises this for structurally unparseable tokens
            raise InvalidTokenError() from exc
        except Exception as exc:
            # Port boundary: anything unexpected (cert fetch, network, ADC resolution)
            # is a server-side failure, never blamed on the caller's token.
            logger.exception("firebase token verification failed unexpectedly")
            raise AuthProviderUnavailableError() from exc

        firebase_uid = claims.get("uid") or claims.get("sub")
        if not isinstance(firebase_uid, str) or not firebase_uid:
            raise InvalidTokenError()
        return VerifiedToken(firebase_uid=firebase_uid, claims=claims)

    async def set_custom_claims(self, firebase_uid: str, claims: Mapping[str, object]) -> None:
        try:
            await asyncio.to_thread(self._set_claims_sync, firebase_uid, dict(claims))
        except AuthProviderUnavailableError:
            raise
        except firebase_auth.UserNotFoundError as exc:
            raise InvalidTokenError() from exc
        except ValueError as exc:  # SDK rejects malformed uid/claims client-side
            raise InvalidTokenError() from exc
        except Exception as exc:
            logger.exception("firebase set_custom_claims failed unexpectedly")
            raise AuthProviderUnavailableError() from exc

    def _set_claims_sync(self, firebase_uid: str, claims: dict[str, object]) -> None:
        app = self._get_app()
        firebase_auth.set_custom_user_claims(firebase_uid, claims, app=app)

    def _verify_sync(self, token: str) -> dict[str, object]:
        app = self._get_app()
        decoded: dict[str, object] = firebase_auth.verify_id_token(token, app=app)
        return decoded

    def _get_app(self) -> firebase_admin.App:
        with self._init_lock:
            if self._app is None:
                try:
                    # No credentials file configured -> Application Default Credentials.
                    credential = (
                        firebase_credentials.Certificate(self._credentials_file)
                        if self._credentials_file
                        else None
                    )
                    self._app = firebase_admin.initialize_app(
                        credential=credential, name=_FIREBASE_APP_NAME
                    )
                except Exception as exc:
                    logger.exception("firebase initialization failed")
                    raise AuthProviderUnavailableError() from exc
            # The SDK resolves the project from the credential, an app option, or
            # GOOGLE_CLOUD_PROJECT. With none of them it raises a bare ``ValueError`` on
            # first use — the same type it raises for a structurally invalid token — so an
            # unconfigured server would answer 401 "invalid token" and blame the caller for
            # its own missing credentials. Checking here keeps that a 503, which is what
            # app/core/config.py promises. Cheap to repeat: the SDK memoizes the lookup.
            if not self._app.project_id:
                logger.error(
                    "firebase project id could not be resolved; set "
                    "PULSEOS_FIREBASE_CREDENTIALS_FILE or GOOGLE_CLOUD_PROJECT"
                )
                raise AuthProviderUnavailableError()
            return self._app
