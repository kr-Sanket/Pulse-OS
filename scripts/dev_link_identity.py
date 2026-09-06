"""Attach a real Firebase UID to an EXISTING seeded PulseOS identity. Local development only.

This replaces the hand-written SQL that was previously needed to obtain a hospital-admin
token against seeded demo data (.claude/TODO.md §1). It walks around a deliberate guard —
``app/modules/auth/seed.py`` refuses ``synthetic:`` subjects precisely so that a real
account can never own a seeded row — so it is a script, not a module: **nothing in
``app/`` imports this, and nothing in ``app/`` ever should.**

What it does, and only this: rewrites ``users.firebase_uid`` on one already-seeded row
from its ``synthetic:`` subject to a real one, and (unless ``--skip-claims``) stamps the
PulseOS role claims onto that subject through the auth module's own port. It creates
nothing — no user, no hospital, no admin, no doctor, no patient — and it never chooses a
role: the role comes from the row that already exists.

Run from the repo root with the backend virtualenv's Python::

    backend/.venv/bin/python scripts/dev_link_identity.py --list
    backend/.venv/bin/python scripts/dev_link_identity.py \\
        --user-email admin.tmh@demo.pulseos.test \\
        --firebase-uid 3E6S9A89POfQmpXUTMsifUsLJcC2

There is deliberately no reverse operation in this slice. Be aware of what that means for
re-seeding: while a seeded row carries a real UID, ``scripts/seed.py`` can no longer find
it by its ``synthetic:`` subject, so it inserts a *second* user **and** a *second*
hospital-admin row for the same hospital (``hospital_admins.hospital_id`` carries no
unique constraint). Restoring the original subject by hand has the same hazard in reverse
— it is a destructive edit to a row a real account is signing in with — which is exactly
why an unlink command is not offered here rather than offered casually.
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

#: Seeded identities carry this prefix (app/modules/auth/seed.py). A row that still has it
#: is unclaimed demo data; a row that does not is somebody's real account.
SYNTHETIC_PREFIX: Final = "synthetic:"

#: The only environment this script will run in. ``Settings.environment`` is the project's
#: own signal (app/core/config.py), documented in .env.example as PULSEOS_ENVIRONMENT.
REQUIRED_ENVIRONMENT: Final = "local"

#: Database hosts that are unambiguously a developer's own machine. ``postgres`` is the
#: docker-compose service name (infra/docker-compose.yml), i.e. the same stack seen from
#: inside its network.
LOCAL_DB_HOSTS: Final = frozenset({"localhost", "127.0.0.1", "::1", "[::1]", "postgres", ""})


class DevToolError(Exception):
    """Anything that should stop the script with a message and a non-zero exit."""


class UnsafeEnvironmentError(DevToolError):
    """The environment is not provably a local development one. Never bypassable."""


@dataclass(frozen=True, slots=True)
class LinkOutcome:
    email: str
    role: str
    previous_uid: str
    new_uid: str
    changed: bool


# -- safety ---------------------------------------------------------------------------
#
# Two independent checks, both required, neither reachable by a flag. The second exists
# because the first fails *open*: `Settings.environment` defaults to "local", so a
# deployment that simply forgot to set PULSEOS_ENVIRONMENT would look like a laptop. The
# database it is pointed at cannot be faked by forgetting something.


def database_host(database_url: str) -> str:
    """The host a SQLAlchemy URL points at, lowercased ('' for a hostless URL)."""
    # Strip the driver so urlsplit sees a conventional scheme (postgresql+asyncpg://…).
    scheme, _, remainder = database_url.partition("://")
    base_scheme = scheme.split("+", 1)[0]
    return (urlsplit(f"{base_scheme}://{remainder}").hostname or "").lower()


def is_local_database(database_url: str) -> bool:
    """True only for a database on this machine (or this machine's compose network)."""
    return database_host(database_url) in LOCAL_DB_HOSTS


def ensure_local_environment(settings: "Settings") -> None:
    """Raise unless this is provably local development. There is no override.

    A ``--force``-style escape hatch is deliberately absent: the whole point of the script
    is that the dangerous operation becomes hard to perform anywhere it would be dangerous.
    """
    if settings.environment != REQUIRED_ENVIRONMENT:
        raise UnsafeEnvironmentError(
            f"PULSEOS_ENVIRONMENT is '{settings.environment}', not '{REQUIRED_ENVIRONMENT}'. "
            "This script only ever runs against local development data."
        )
    if not is_local_database(settings.database_url):
        raise UnsafeEnvironmentError(
            f"PULSEOS_DATABASE_URL points at host '{database_host(settings.database_url)}', "
            "which is not this machine. Refusing to rewrite an identity on a remote database."
        )


# -- the operation --------------------------------------------------------------------


async def find_seeded_identities(session: "AsyncSession") -> "list[User]":
    """Every identity still carrying a seeded subject, i.e. everything linkable."""
    from app.modules.auth.models import User
    from sqlalchemy import select

    result = await session.execute(
        select(User).where(User.firebase_uid.startswith(SYNTHETIC_PREFIX)).order_by(User.email)
    )
    return list(result.scalars())


async def resolve_target(session: "AsyncSession", email: str) -> "User":
    """The one identity this email names, or a refusal explaining why there isn't one.

    Matched on ``users.email``, which the seed pins per demo actor. The column carries no
    unique constraint, so an ambiguous match is refused rather than resolved by guessing.
    """
    from app.modules.auth.models import User
    from sqlalchemy import select

    result = await session.execute(select(User).where(User.email == email))
    matches = list(result.scalars())
    if not matches:
        raise DevToolError(
            f"No user has the email '{email}'. Run --list to see the seeded identities, "
            "or run scripts/seed.py if the database has not been seeded."
        )
    if len(matches) > 1:
        raise DevToolError(
            f"{len(matches)} users share the email '{email}'. Refusing to guess which one."
        )
    return matches[0]


def plan_link(target: "User", firebase_uid: str) -> LinkOutcome:
    """Decide what the link would do, and refuse anything that is not a dev link.

    Pure: it inspects the row and the argument and returns the intended outcome, so every
    rule below is testable without a database.
    """
    current = target.firebase_uid
    if not firebase_uid or firebase_uid.startswith(SYNTHETIC_PREFIX):
        raise DevToolError(
            "--firebase-uid must be a real Firebase UID. Refusing to write a "
            f"'{SYNTHETIC_PREFIX}' subject, which could never sign in."
        )
    if current == firebase_uid:
        # Already linked to this exact account: the script is repeatable, so this is a
        # reported no-op rather than an error.
        return LinkOutcome(
            email=target.email or "",
            role=str(target.role),
            previous_uid=current,
            new_uid=firebase_uid,
            changed=False,
        )
    if not current.startswith(SYNTHETIC_PREFIX):
        raise DevToolError(
            f"'{target.email}' is already linked to a different real account ({current}). "
            "Refusing to reassign a real identity."
        )
    return LinkOutcome(
        email=target.email or "",
        role=str(target.role),
        previous_uid=current,
        new_uid=firebase_uid,
        changed=True,
    )


async def apply_outcome(
    session: "AsyncSession", target: "User", outcome: LinkOutcome, *, provision_claims: bool
) -> None:
    """Write the new subject and, unless asked not to, stamp the PulseOS claims.

    Claims are provisioned **inside the same transaction** as the row change, mirroring the
    invariant registration already holds (app/modules/patients/service.py): a provider
    failure rolls the link back, so the script never leaves an account half-linked. Claims
    go through the auth module's own port rather than a second Firebase call written here.
    """
    if not outcome.changed:
        return
    target.firebase_uid = outcome.new_uid
    await session.flush()
    if not provision_claims:
        return

    from app.core.config import get_settings
    from app.modules.auth.accounts import UserAccountService
    from app.modules.auth.firebase import FirebaseAuthProvider
    from app.modules.auth.repository import UserRepository

    accounts = UserAccountService(UserRepository(session), FirebaseAuthProvider(get_settings()))
    await accounts.provision_claims(outcome.new_uid, role=target.role, user_id=target.id)


# -- CLI ------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dev_link_identity.py",
        description=(
            "Link a real Firebase UID to an existing seeded PulseOS identity. "
            "Local development only; creates nothing."
        ),
        epilog=(
            "Note: a seeded row carrying a real UID is invisible to scripts/seed.py, which "
            "would then insert a duplicate user and hospital-admin row. See the module "
            "docstring before re-seeding."
        ),
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="show every seeded identity that can be linked, and exit",
    )
    parser.add_argument(
        "--user-email",
        help="the seeded identity to link, by its email (e.g. admin.tmh@demo.pulseos.test)",
    )
    parser.add_argument("--firebase-uid", help="the real Firebase UID to attach")
    parser.add_argument(
        "--skip-claims",
        action="store_true",
        help="link the row only; do not stamp PulseOS claims (no Firebase credentials needed)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="skip the confirmation prompt (does NOT bypass the environment checks)",
    )
    return parser


def _print_banner(settings: "Settings") -> None:
    print("PulseOS dev identity linker — LOCAL DEVELOPMENT ONLY")
    print(f"  environment : {settings.environment}")
    print(f"  database    : {database_host(settings.database_url)}")


def _confirm(outcome: LinkOutcome, *, assume_yes: bool) -> bool:
    print("")
    print(f"  identity    : {outcome.email} ({outcome.role})")
    print(f"  subject now : {outcome.previous_uid}")
    print(f"  subject new : {outcome.new_uid}")
    if assume_yes:
        return True
    answer = input("\nRewrite this identity's subject? [y/N] ").strip().lower()
    return answer in {"y", "yes"}


async def run(argv: list[str]) -> int:
    from app.core.config import get_settings
    from app.core.db import create_db_engine, create_session_factory
    from sqlalchemy.exc import DatabaseError

    args = build_parser().parse_args(argv)
    settings = get_settings()

    try:
        # Before anything reads or writes: this must be a developer's own machine.
        ensure_local_environment(settings)
    except UnsafeEnvironmentError as exc:
        print(f"Refusing to run: {exc}", file=sys.stderr)
        return 2

    _print_banner(settings)

    engine = create_db_engine(settings)
    try:
        factory = create_session_factory(engine)
        async with factory() as session, session.begin():
            if args.list:
                identities = await find_seeded_identities(session)
                print(f"\nSeeded identities available to link ({len(identities)}):")
                for user in identities:
                    email = user.email or "(no email)"
                    print(f"  {email:<34} {user.role!s:<15} {user.firebase_uid}")
                if not identities:
                    print("  none — has scripts/seed.py been run?")
                return 0

            if not args.user_email:
                print("--user-email is required (or use --list).", file=sys.stderr)
                return 2

            if not args.firebase_uid:
                print("--firebase-uid is required (or use --list).", file=sys.stderr)
                return 2

            target = await resolve_target(session, args.user_email)
            outcome = plan_link(target, args.firebase_uid)

            if not outcome.changed:
                print(f"\n'{outcome.email}' already has subject {outcome.new_uid} — nothing to do.")
                return 0

            if not _confirm(outcome, assume_yes=args.yes):
                print("Aborted; nothing was changed.")
                # Nothing was flushed, but be explicit rather than relying on that.
                await session.rollback()
                return 1

            await apply_outcome(session, target, outcome, provision_claims=not args.skip_claims)
    except DevToolError as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 1
    except DatabaseError as exc:
        print(f"\nDatabase error: {exc.orig or exc}", file=sys.stderr)
        print(
            "Is the database up and migrated? Try: make up && cd backend && "
            ".venv/bin/alembic upgrade head",
            file=sys.stderr,
        )
        return 1
    finally:
        await engine.dispose()

    print(f"\nLinked. '{outcome.email}' now signs in as {outcome.new_uid}.")
    if args.skip_claims:
        print(
            "Claims were NOT provisioned (--skip-claims). Sign in, then complete the "
            "portal's registration step once to have them stamped."
        )
    else:
        print("PulseOS claims provisioned. Sign out and back in to pick them up.")
    return 0


def main() -> int:
    return asyncio.run(run(sys.argv[1:]))


if __name__ == "__main__":
    sys.exit(main())
