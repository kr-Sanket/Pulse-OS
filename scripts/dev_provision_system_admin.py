"""Provision a real Firebase UID as a SYSTEM_ADMIN. Local development only.

This script provisions a dedicated SYSTEM_ADMIN identity for local development and testing.
It lives in ``scripts/`` and is imported by nothing in ``app/``: **nothing in ``app/``
imports this, and nothing in ``app/`` ever should.**

Safety rules enforced:
* Provably local environment: refuses unless PULSEOS_ENVIRONMENT=local and database host is local.
* No --force escape hatch exists.
* Requires an explicit real --firebase-uid; synthetic subjects and empty UIDs are refused.
* Never promotes or overwrites an existing user with another role (e.g. HOSPITAL_ADMIN, DOCTOR, PATIENT).
* Stamps the PulseOS SYSTEM_ADMIN custom claims on the Firebase user through the auth module's port.

Run from the repo root with the backend virtualenv's Python::

    backend/.venv/bin/python scripts/dev_provision_system_admin.py \\
        --firebase-uid <FIREBASE_UID> \\
        --email sysadmin@example.test
"""

import argparse
import asyncio
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final
from urllib.parse import urlsplit

if TYPE_CHECKING:  # pragma: no cover - import-time typing only
    from app.core.config import Settings
    from app.modules.auth.models import User
    from sqlalchemy.ext.asyncio import AsyncSession

SYNTHETIC_PREFIX: Final = "synthetic:"
REQUIRED_ENVIRONMENT: Final = "local"
MAX_EMAIL_LENGTH: Final = 255
LOCAL_DB_HOSTS: Final = frozenset(
    {"localhost", "127.0.0.1", "::1", "[::1]", "postgres", ""}
)


class DevToolError(Exception):
    """Anything that should stop the script with a message and a non-zero exit."""


class UnsafeEnvironmentError(DevToolError):
    """The environment is not provably a local development one. Never bypassable."""


@dataclass(frozen=True, slots=True)
class ProvisionOutcome:
    firebase_uid: str
    role: str
    email: str | None
    created: bool
    changed: bool


def database_host(database_url: str) -> str:
    """The host a SQLAlchemy URL points at, lowercased ('' for a hostless URL)."""
    scheme, _, remainder = database_url.partition("://")
    base_scheme = scheme.split("+", 1)[0]
    return (urlsplit(f"{base_scheme}://{remainder}").hostname or "").lower()


def is_local_database(database_url: str) -> bool:
    """True only for a database on this machine (or this machine's compose network)."""
    return database_host(database_url) in LOCAL_DB_HOSTS


def ensure_local_environment(settings: "Settings") -> None:
    """Raise unless this is provably local development. There is no override."""
    if settings.environment != REQUIRED_ENVIRONMENT:
        raise UnsafeEnvironmentError(
            f"PULSEOS_ENVIRONMENT is '{settings.environment}', not '{REQUIRED_ENVIRONMENT}'. "
            "This script only ever runs against local development data."
        )
    if not is_local_database(settings.database_url):
        raise UnsafeEnvironmentError(
            f"PULSEOS_DATABASE_URL points at host '{database_host(settings.database_url)}', "
            "which is not this machine. Refusing to run on a remote database."
        )


def clean_uid(firebase_uid: str | None) -> str:
    if not firebase_uid or not firebase_uid.strip():
        raise DevToolError("--firebase-uid is required and must not be blank.")
    cleaned = firebase_uid.strip()
    if cleaned.startswith(SYNTHETIC_PREFIX):
        raise DevToolError(
            f"--firebase-uid must be a real Firebase UID, not a '{SYNTHETIC_PREFIX}' subject."
        )
    return cleaned


def clean_email(email: str | None) -> str | None:
    if email is None:
        return None
    cleaned = email.strip()
    if not cleaned:
        raise DevToolError("--email must not be blank if supplied.")
    if len(cleaned) > MAX_EMAIL_LENGTH:
        raise DevToolError(f"--email must be {MAX_EMAIL_LENGTH} characters or fewer.")
    return cleaned


def plan_provision(
    existing: "User | None", *, firebase_uid: str, email: str | None
) -> ProvisionOutcome:
    """Decide what provisioning would do, and enforce domain invariants. Pure."""
    from app.modules.auth.domain import Role

    valid_uid = clean_uid(firebase_uid)
    valid_email = clean_email(email)

    if existing is None:
        return ProvisionOutcome(
            firebase_uid=valid_uid,
            role=Role.SYSTEM_ADMIN.value,
            email=valid_email,
            created=True,
            changed=True,
        )

    if existing.role is not Role.SYSTEM_ADMIN:
        raise DevToolError(
            f"User '{existing.firebase_uid}' is already registered with role {existing.role}. "
            f"Refusing to promote or overwrite an existing {existing.role} account to SYSTEM_ADMIN."
        )

    # Already SYSTEM_ADMIN
    email_changed = valid_email is not None and valid_email != existing.email
    return ProvisionOutcome(
        firebase_uid=valid_uid,
        role=Role.SYSTEM_ADMIN.value,
        email=valid_email or existing.email,
        created=False,
        changed=email_changed,
    )


async def apply_provision(
    session: "AsyncSession",
    outcome: ProvisionOutcome,
    existing: "User | None",
    *,
    provision_claims: bool,
) -> "User":
    """Persist the SYSTEM_ADMIN identity and optionally stamp custom claims."""
    from uuid import uuid4

    from app.core.config import get_settings
    from app.modules.auth.accounts import UserAccountService
    from app.modules.auth.domain import Role
    from app.modules.auth.firebase import FirebaseAuthProvider
    from app.modules.auth.models import User, UserStatus
    from app.modules.auth.repository import UserRepository

    if outcome.created:
        user = User(
            id=uuid4(),
            firebase_uid=outcome.firebase_uid,
            role=Role.SYSTEM_ADMIN,
            email=outcome.email,
            status=UserStatus.ACTIVE,
        )
        session.add(user)
        await session.flush()
    else:
        assert existing is not None
        user = existing
        if outcome.changed and outcome.email:
            user.email = outcome.email
            await session.flush()

    if provision_claims:
        settings = get_settings()
        accounts = UserAccountService(
            UserRepository(session), FirebaseAuthProvider(settings)
        )
        await accounts.provision_claims(
            outcome.firebase_uid, role=Role.SYSTEM_ADMIN, user_id=user.id
        )

    return user


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dev_provision_system_admin.py",
        description="Provision a real Firebase user as SYSTEM_ADMIN for local development.",
    )
    parser.add_argument(
        "--firebase-uid",
        required=True,
        help="the real Firebase UID of the account to provision as SYSTEM_ADMIN",
    )
    parser.add_argument(
        "--email",
        help="optional email address to attach to the PulseOS user row",
    )
    parser.add_argument(
        "--skip-claims",
        action="store_true",
        help="provision the database row only; do not stamp Firebase custom claims",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="skip the confirmation prompt (does NOT bypass the environment checks)",
    )
    return parser


def _print_banner(settings: "Settings") -> None:
    print("PulseOS dev System Admin provisioner — LOCAL DEVELOPMENT ONLY")
    print(f"  environment : {settings.environment}")
    print(f"  database    : {database_host(settings.database_url)}")


def _confirm(outcome: ProvisionOutcome, *, assume_yes: bool) -> bool:
    print("")
    print(f"  target UID  : {outcome.firebase_uid}")
    print(f"  role        : {outcome.role}")
    print(f"  email       : {outcome.email or '(none)'}")
    print(
        f"  action      : {'CREATE new user' if outcome.created else 'UPDATE existing system admin'}"
    )
    if assume_yes:
        return True
    answer = input("\nApply these changes? [y/N] ").strip().lower()
    return answer in {"y", "yes"}


async def run(argv: list[str]) -> int:
    from app.core.config import get_settings
    from app.core.db import create_db_engine, create_session_factory
    from app.modules.auth.errors import AuthError
    from app.modules.auth.repository import UserRepository
    from sqlalchemy.exc import DatabaseError

    args = build_parser().parse_args(argv)
    settings = get_settings()

    try:
        ensure_local_environment(settings)
    except UnsafeEnvironmentError as exc:
        print(f"Refusing to run: {exc}", file=sys.stderr)
        return 2

    _print_banner(settings)

    engine = create_db_engine(settings)
    try:
        factory = create_session_factory(engine)
        async with factory() as session, session.begin():
            repo = UserRepository(session)
            existing = await repo.get_by_firebase_uid(args.firebase_uid)
            outcome = plan_provision(
                existing, firebase_uid=args.firebase_uid, email=args.email
            )

            if not _confirm(outcome, assume_yes=args.yes):
                print("Aborted; nothing was changed.")
                await session.rollback()
                return 1

            await apply_provision(
                session, outcome, existing, provision_claims=not args.skip_claims
            )
    except DevToolError as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 1
    except AuthError as exc:
        print(f"\nAuthentication provider error: {exc}", file=sys.stderr)
        print(
            "Firebase Admin credentials are not configured or project ID could not be resolved.\n"
            "Set PULSEOS_FIREBASE_CREDENTIALS_FILE in .env (or run with --skip-claims to "
            "provision the database user row only).",
            file=sys.stderr,
        )
        return 1
    except DatabaseError as exc:
        print(f"\nDatabase error: {exc.orig or exc}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()

    print(
        f"\nSuccess: account '{outcome.firebase_uid}' is provisioned as SYSTEM_ADMIN."
    )
    if args.skip_claims:
        print("Claims were NOT provisioned (--skip-claims).")
    else:
        print(
            "PulseOS claims provisioned. Sign out and back in to pick them up in the portal."
        )
    return 0


def main() -> int:
    return asyncio.run(run(sys.argv[1:]))


if __name__ == "__main__":
    sys.exit(main())
