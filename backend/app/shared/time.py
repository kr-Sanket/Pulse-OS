"""The UTC clock the domain services read.

Lives here rather than in a module because three modules now need the same instant:
``consent`` stamps audit events and evaluates grant expiry with it, and ``records`` reads
it once per clinician listing and passes it down so the grant filter and the audit row
describe the same moment (ADR-020). A module-local copy would be a second clock, and two
clocks are how a listing and the enforcement check that follows it come to disagree.

Injected as a ``Callable[[], datetime]`` at every service constructor rather than called
directly in domain code — reading the clock is a decision, and a test must be able to fix
it.
"""

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)
