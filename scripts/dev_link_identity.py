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

It can also, in the same transaction, correct the PulseOS profile of the identity it has
linked: ``--full-name`` and ``--email`` on a **HOSPITAL_ADMIN** row. That exists because
linking deliberately changes only ``firebase_uid``, which leaves a real developer signing
in behind a seeded demo name ("Ravi Prasad (Demo Admin)"). It is **not** a profile editor,
and four rules keep it from becoming one:

* the flags require ``--firebase-uid``, so there is no way to name a row and edit it;
* the row must already be — or be becoming, in this same run — that UID's identity;
* only HOSPITAL_ADMIN is supported; a patient or doctor row is refused outright;
* two fixed fields, both supplied explicitly. There is no ``--set``, and no way to reach
  any other column.

The Firebase account itself is never written to: display name and email stay Firebase's,
and PulseOS profile data stays PulseOS's. Coupling the two is precisely the mistake this
tool must not make — it corrects local data, it does not synchronise an external identity.

Run from the repo root with the backend virtualenv's Python::

    backend/.venv/bin/python scripts/dev_link_identity.py --list
    backend/.venv/bin/python scripts/dev_link_identity.py \\
        --user-email admin.tmh@demo.pulseos.test \\
        --firebase-uid 3E6S9A89POfQmpXUTMsifUsLJcC2

    # already linked: resolve by the UID, and correct the seeded profile values
    backend/.venv/bin/python scripts/dev_link_identity.py \\
        --firebase-uid 3E6S9A89POfQmpXUTMsifUsLJcC2 \\
        --full-name "Sanket Kumar" --email sanket@example.com

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
    from uuid import UUID

    from app.core.config import Settings
    from app.modules.auth.models import User
    from app.modules.records.models import HospitalAdmin
    from sqlalchemy.ext.asyncio import AsyncSession

#: Seeded identities carry this prefix (app/modules/auth/seed.py). A row that still has it
#: is unclaimed demo data; a row that does not is somebody's real account.
SYNTHETIC_PREFIX: Final = "synthetic:"

#: The only environment this script will run in. ``Settings.environment`` is the project's
#: own signal (app/core/config.py), documented in .env.example as PULSEOS_ENVIRONMENT.
REQUIRED_ENVIRONMENT: Final = "local"

#: The API's own limits on the two profile columns this tool may write
#: (app/modules/records/models.py HospitalAdmin.full_name, app/modules/auth/models.py User.email).
MAX_FULL_NAME_LENGTH: Final = 120
MAX_EMAIL_LENGTH: Final = 255

#: Database hosts that are unambiguously a developer's own machine. ``postgres`` is the
#: docker-compose service name (infra/docker-compose.yml), i.e. the same stack seen from
#: inside its network.
LOCAL_DB_HOSTS: Final = frozenset({"localhost", "127.0.0.1", "::1", "[::1]", "postgres", ""})


class DevToolError(Exception):
    """Anything that should stop the script with a message and a non-zero exit."""


class UnsafeEnvironmentError(DevToolError):
    """The environment is not provably a local development one. Never bypassable."""


@dataclass(frozen=True, slots=True)
class ProfileChange:
    """A correction to the linked hospital admin's PulseOS profile.

    ``None`` on a field means "leave it alone" — the developer supplies only what they want
    corrected, and an omitted flag is never treated as an instruction to blank a column.
    """

    full_name: str | None
    email: str | None
    previous_full_name: str
    previous_email: str | None

    @property
    def changed(self) -> bool:
        return self.full_name is not None or self.email is not None


NO_PROFILE_CHANGE: Final = ProfileChange(
    full_name=None, email=None, previous_full_name="", previous_email=None
)


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


async def resolve_target(
    session: "AsyncSession", *, email: str | None, firebase_uid: str | None
) -> "User":
    """The one identity these arguments name, or a refusal explaining why there isn't one.

    Two keys, because the tool can mutate one of them. ``users.email`` is how a *seeded*
    identity is named — the seed pins one per demo actor — but once ``--email`` has
    corrected it, that key no longer finds the row. ``firebase_uid`` is unique and, for an
    already-linked identity, stable, so it is tried first and is the key that keeps working
    after a profile sync.

    A UID that matches nothing is not an error here: that is the ordinary not-yet-linked
    case, and the email carries the lookup. Supplying both and having them disagree *is* an
    error — that is two different rows, and guessing between them is exactly the kind of
    mistake this script exists to prevent.
    """
    from app.modules.auth.models import User
    from sqlalchemy import select

    by_uid: User | None = None
    if firebase_uid:
        result = await session.execute(select(User).where(User.firebase_uid == firebase_uid))
        by_uid = result.scalar_one_or_none()

    if email is None:
        if by_uid is None:
            raise DevToolError(
                f"No user has the Firebase UID '{firebase_uid}'. Pass --user-email to name "
                "the seeded identity you want to link."
            )
        return by_uid

    result = await session.execute(select(User).where(User.email == email))
    matches = list(result.scalars())
    if len(matches) > 1:
        # users.email carries no unique constraint, so ambiguity is possible and refused.
        raise DevToolError(
            f"{len(matches)} users share the email '{email}'. Refusing to guess which one."
        )
    by_email = matches[0] if matches else None

    if by_uid is not None and by_email is not None and by_uid.id != by_email.id:
        raise DevToolError(
            f"--firebase-uid names '{by_uid.email}' but --user-email names '{by_email.email}'. "
            "These are two different identities; refusing to guess which you meant."
        )
    target = by_uid or by_email
    if target is None:
        raise DevToolError(
            f"No user has the email '{email}'. Run --list to see the seeded identities, "
            "or run scripts/seed.py if the database has not been seeded."
        )
    return target


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


async def load_admin_profile(session: "AsyncSession", user_id: "UUID") -> "HospitalAdmin":
    """The hospital-admin profile row for this identity, or a refusal.

    Reaching into a ``records``-owned table from a script is a boundary this tool crosses
    knowingly and in exactly one place. ``records`` publishes no write seam for a profile
    name — correctly, because nothing in the product may rename an administrator — so there
    is no service to go through, and inventing one would put a capability into ``app/``
    that only a developer's laptop should ever have.
    """
    from app.modules.records.models import HospitalAdmin
    from sqlalchemy import select

    result = await session.execute(select(HospitalAdmin).where(HospitalAdmin.user_id == user_id))
    admin = result.scalar_one_or_none()
    if admin is None:
        raise DevToolError(
            "This identity has the HOSPITAL_ADMIN role but no hospital-admin profile row. "
            "Refusing to act on an inconsistent account."
        )
    return admin


async def email_belongs_to_another_user(
    session: "AsyncSession", email: str, *, exclude_user_id: "UUID"
) -> bool:
    """True when some *other* users row already holds this email.

    ``users.email`` has no unique constraint, so nothing at the database level stops two
    rows sharing one. Allowing it here would be self-defeating: ``resolve_target`` refuses
    an ambiguous email, so a collision this tool created would make the row it just wrote
    unreachable by the very key used to name it.
    """
    from app.modules.auth.models import User
    from sqlalchemy import select

    result = await session.execute(
        select(User.id).where(User.email == email, User.id != exclude_user_id)
    )
    return result.first() is not None


def profile_sync_requested(
    target: "User", *, full_name: str | None, email: str | None, firebase_uid: str | None
) -> bool:
    """Whether a profile correction was asked for — refusing the two ways it may not be.

    Separate from :func:`plan_profile_sync`, and checked *before* the admin row is loaded,
    so a doctor or patient is told the real reason ("HOSPITAL_ADMIN only") instead of the
    incidental one they would otherwise hit ("no hospital-admin profile row").
    """
    from app.modules.auth.domain import Role

    if full_name is None and email is None:
        return False
    if not firebase_uid:
        raise DevToolError(
            "--full-name and --email require --firebase-uid. This tool corrects the profile "
            "of an identity it has linked; it is not a profile editor."
        )
    if target.role is not Role.HOSPITAL_ADMIN:
        raise DevToolError(
            f"Profile correction is supported for HOSPITAL_ADMIN only; this identity is "
            f"{target.role}. Patient and doctor profiles are out of scope for this tool."
        )
    return True


def plan_profile_sync(
    target: "User",
    admin_full_name: str,
    *,
    full_name: str | None,
    email: str | None,
    firebase_uid: str | None,
) -> ProfileChange:
    """Decide what the profile correction would do, and refuse anything wider than one.

    Pure, so every rule is testable without a database. The role check lives here rather
    than at the CLI because it is a domain rule, not an argument-parsing one.
    """
    if not profile_sync_requested(
        target, full_name=full_name, email=email, firebase_uid=firebase_uid
    ):
        return NO_PROFILE_CHANGE

    corrected_name = _clean("--full-name", full_name, MAX_FULL_NAME_LENGTH)
    corrected_email = _clean("--email", email, MAX_EMAIL_LENGTH)

    # A value equal to what is already stored is not a change; reporting it as one would
    # make a repeated run look like it did something.
    return ProfileChange(
        full_name=None if corrected_name == admin_full_name else corrected_name,
        email=None if corrected_email == target.email else corrected_email,
        previous_full_name=admin_full_name,
        previous_email=target.email,
    )


def _clean(flag: str, value: str | None, max_length: int) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        raise DevToolError(f"{flag} must not be blank.")
    if len(cleaned) > max_length:
        raise DevToolError(f"{flag} must be {max_length} characters or fewer.")
    return cleaned


async def apply_profile_change(
    session: "AsyncSession", target: "User", admin: "HospitalAdmin", change: ProfileChange
) -> None:
    """Write the corrected profile values. Same session, so the same transaction as the link.

    Touches two columns and no others: the admin's display name (records) and the user's
    email (auth). Role, status, hospital, verification and firebase_uid are not written
    here, and no row is created or removed.
    """
    if not change.changed:
        return
    if change.full_name is not None:
        admin.full_name = change.full_name
    if change.email is not None:
        target.email = change.email
    await session.flush()


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
        help=(
            "the seeded identity, by its email (e.g. admin.tmh@demo.pulseos.test). Optional "
            "once linked: --firebase-uid alone resolves an identity this tool already linked"
        ),
    )
    parser.add_argument("--firebase-uid", help="the real Firebase UID to attach")
    parser.add_argument(
        "--full-name",
        help=(
            "correct the linked HOSPITAL_ADMIN's PulseOS display name (requires "
            "--firebase-uid; not a profile editor)"
        ),
    )
    parser.add_argument(
        "--email",
        help="correct the linked identity's PulseOS email (requires --firebase-uid)",
    )
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


def _confirm(outcome: LinkOutcome, change: ProfileChange, *, assume_yes: bool) -> bool:
    print("")
    print(f"  identity    : {outcome.email} ({outcome.role})")
    if outcome.changed:
        print(f"  subject now : {outcome.previous_uid}")
        print(f"  subject new : {outcome.new_uid}")
    else:
        print(f"  subject     : {outcome.new_uid} (already linked)")
    if change.full_name is not None:
        print(f"  name now    : {change.previous_full_name}")
        print(f"  name new    : {change.full_name}")
    if change.email is not None:
        print(f"  email now   : {change.previous_email}")
        print(f"  email new   : {change.email}")
    if assume_yes:
        return True
    answer = input("\nApply these changes? [y/N] ").strip().lower()
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

            # --firebase-uid is required for every mutating path: the link needs it, and
            # the profile flags are only permitted on the identity it names. --user-email
            # is optional once a row is linked, because the UID then resolves it.
            if not args.firebase_uid:
                print("--firebase-uid is required (or use --list).", file=sys.stderr)
                return 2

            target = await resolve_target(
                session, email=args.user_email, firebase_uid=args.firebase_uid
            )
            outcome = plan_link(target, args.firebase_uid)

            # Planned against the row as it stands, but only ever for the identity the
            # supplied UID owns — plan_link has already refused every case where the row
            # belongs to somebody else.
            change = NO_PROFILE_CHANGE
            admin: HospitalAdmin | None = None
            if profile_sync_requested(
                target, full_name=args.full_name, email=args.email, firebase_uid=args.firebase_uid
            ):
                admin = await load_admin_profile(session, target.id)
                change = plan_profile_sync(
                    target,
                    admin.full_name,
                    full_name=args.full_name,
                    email=args.email,
                    firebase_uid=args.firebase_uid,
                )
                if change.email is not None and await email_belongs_to_another_user(
                    session, change.email, exclude_user_id=target.id
                ):
                    raise DevToolError(
                        f"'{change.email}' already belongs to another user. Refusing to "
                        "create a duplicate email, which would make this identity "
                        "ambiguous to name."
                    )

            if not outcome.changed and not change.changed:
                print(f"\n'{outcome.email}' already matches what you asked for — nothing to do.")
                return 0

            if not _confirm(outcome, change, assume_yes=args.yes):
                print("Aborted; nothing was changed.")
                # Nothing was flushed, but be explicit rather than relying on that.
                await session.rollback()
                return 1

            await apply_outcome(session, target, outcome, provision_claims=not args.skip_claims)
            if admin is not None and change.changed:
                await apply_profile_change(session, target, admin, change)
            linked, corrected = outcome.changed, change.changed
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

    if corrected:
        print("\nPulseOS profile corrected. The Firebase account itself was not touched.")
    if not linked:
        return 0
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
