"""Rate-limiting port (ADR-024): fixed-window counters over Redis.

Like the other external providers, the limiter sits behind an interface with an in-memory
fake, so tests and credential-free dev never touch Redis (docs/SYSTEM_ARCHITECTURE.md
rule 4). The real implementation mirrors ``core/queue.py``: lazy connection, closed on
lifespan shutdown, every failure contained inside the adapter.

**This module is deliberately identity-agnostic.** It counts requests against an opaque
subject string and knows nothing about users, roles or Health IDs — the request guard that
supplies the subject lives in ``auth/dependencies.py``, beside the role gates, because
``core`` imports no module and must keep it that way.

The algorithm is a fixed window, chosen because it is the simplest thing Redis can do
atomically and the threat it answers is enumeration measured in hundreds of requests. A
fixed window permits up to twice the limit across a boundary; for this purpose that is
irrelevant, and a sliding window or token bucket would be sophistication without a reason.
"""

import logging
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from typing import Final

import redis.asyncio as aioredis
from fastapi import Request

from app.core.config import Settings

logger = logging.getLogger(__name__)

#: Connection timeouts, matching the readiness probe: a limiter that hangs is worse than a
#: limiter that fails open.
_CONNECT_TIMEOUT_SECONDS: Final = 2.0

#: How often one process will report Redis being unreachable. An outage must not turn the
#: access log into a flood, and the readiness probe already reports Redis independently.
_OUTAGE_LOG_INTERVAL_SECONDS: Final = 30.0


@dataclass(frozen=True, slots=True)
class RateLimit:
    """How many requests a bucket allows, and over how long."""

    limit: int
    window_seconds: int


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """The verdict, and how long to wait when it is a refusal.

    ``retry_after_seconds`` is whole seconds to the end of the current window, computed
    arithmetically rather than read back from Redis — a fixed window makes it a property of
    the clock, so a refusal costs no extra round trip.
    """

    allowed: bool
    retry_after_seconds: int


#: The buckets and their approved limits (ADR-024). Policy lives in code so that changing a
#: security control is a reviewed edit; a deployment may still override the whole table
#: through ``PULSEOS_RATE_LIMITS`` without a release.
DEFAULT_LIMITS: Final[dict[str, RateLimit]] = {
    # Returns a patient's *name* — the tightest of the read paths (ADR-021).
    "patient_lookup": RateLimit(limit=20, window_seconds=60),
    "record_existence": RateLimit(limit=30, window_seconds=60),
    "granted_records": RateLimit(limit=30, window_seconds=60),
    # A write, and a deliberate act: ten a minute is already beyond human.
    "access_request_create": RateLimit(limit=10, window_seconds=60),
    "ai_generate": RateLimit(limit=10, window_seconds=60),
    # Returns record text without generation, so it is cheaper than ai_generate but is a
    # content read: bounded like the granted-records listing it mirrors.
    "ai_search": RateLimit(limit=30, window_seconds=60),
    # Recomputes a whole sealed batch (up to 256 leaves) per call. No PHI, but it is the
    # one audit read open to every role, so it is bounded like the other content reads.
    "audit_batch_verify": RateLimit(limit=30, window_seconds=60),
}


def window_index(now: float, window_seconds: int) -> int:
    """Which fixed window ``now`` falls in. Part of the key, so a stale counter can never
    outlive its window even if its expiry were somehow lost."""
    return int(now // window_seconds)


def retry_after(now: float, window_seconds: int) -> int:
    """Whole seconds until the current window ends — at least one, because ``Retry-After: 0``
    invites an immediate retry that is certain to be refused."""
    remaining = window_seconds - (now % window_seconds)
    return max(1, int(remaining) if remaining == int(remaining) else int(remaining) + 1)


def counter_key(bucket: str, subject: str, index: int) -> str:
    """``ratelimit:{bucket}:{subject}:{window}`` — the window in the name is what makes
    expiry a cleanup detail rather than a correctness one."""
    return f"ratelimit:{bucket}:{subject}:{index}"


class RateLimiter(ABC):
    """Counts one request against a bucket for a subject."""

    def __init__(self, limits: dict[str, RateLimit] | None = None) -> None:
        self._limits = dict(DEFAULT_LIMITS if limits is None else limits)

    def limit_for(self, bucket: str) -> RateLimit:
        """The bucket's policy. An unknown bucket is a programming error, not a request
        problem — failing loudly here beats silently not limiting a protected route."""
        try:
            return self._limits[bucket]
        except KeyError:
            raise KeyError(f"unknown rate-limit bucket {bucket!r}") from None

    @abstractmethod
    async def check(self, bucket: str, subject: str) -> RateLimitDecision:
        """Count this request and say whether it may proceed. Never raises for
        infrastructure failure — see the fail-open note on the Redis implementation."""

    async def aclose(self) -> None:  # noqa: B027 — optional hook; fakes need no teardown
        """Release connections (lifespan shutdown)."""


class RedisRateLimiter(RateLimiter):
    """Fixed-window counters in Redis.

    **Atomic by construction.** ``INCR`` is atomic and returns the post-increment value, so
    the read-then-write race that lets concurrent requests share one slot cannot occur.
    ``EXPIRE ... NX`` rides in the same pipeline, so there is no round trip between counting
    and setting the lifetime.

    **Fail-open**, following the precedent ADR-014 set for the job queue: Redis is advisory
    infrastructure here, and a blip must not take consent requests, discovery and lookup
    offline with it. A failure is logged (throttled) and the request proceeds.
    """

    def __init__(self, redis_url: str, limits: dict[str, RateLimit] | None = None) -> None:
        super().__init__(limits)
        self._redis_url = redis_url
        self._client: aioredis.Redis | None = None
        self._last_outage_log = 0.0

    async def check(self, bucket: str, subject: str) -> RateLimitDecision:
        policy = self.limit_for(bucket)
        now = time.time()
        key = counter_key(bucket, subject, window_index(now, policy.window_seconds))
        try:
            client = self._connect()
            async with client.pipeline(transaction=False) as pipe:
                pipe.incr(key)
                # NX: only the request that created the counter sets its lifetime, so a
                # later request in the same window cannot extend it.
                pipe.expire(key, policy.window_seconds, nx=True)
                count, _ = await pipe.execute()
        except Exception:
            self._log_outage()
            return RateLimitDecision(allowed=True, retry_after_seconds=0)

        if int(count) > policy.limit:
            return RateLimitDecision(
                allowed=False, retry_after_seconds=retry_after(now, policy.window_seconds)
            )
        return RateLimitDecision(allowed=True, retry_after_seconds=0)

    def _connect(self) -> aioredis.Redis:
        if self._client is None:
            self._client = aioredis.Redis.from_url(
                self._redis_url,
                socket_connect_timeout=_CONNECT_TIMEOUT_SECONDS,
                socket_timeout=_CONNECT_TIMEOUT_SECONDS,
            )
        return self._client

    def _log_outage(self) -> None:
        """One line per interval, never per request: an outage lasts as long as it lasts."""
        now = time.monotonic()
        if now - self._last_outage_log < _OUTAGE_LOG_INTERVAL_SECONDS:
            return
        self._last_outage_log = now
        logger.warning("rate limiter unavailable; requests are not being limited", exc_info=True)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


class InMemoryRateLimiter(RateLimiter):
    """Process-local counters for tests and credential-free dev.

    Same window arithmetic as the Redis implementation so a test exercises the real
    boundary behaviour — but it is **not** a production limiter: counters are per process,
    so several API workers would each grant a full quota.
    """

    def __init__(self, limits: dict[str, RateLimit] | None = None) -> None:
        super().__init__(limits)
        #: key -> count, for assertions.
        self.counters: defaultdict[str, int] = defaultdict(int)
        #: Set to make every check fail, exercising the fail-open path.
        self.failure: Exception | None = None
        #: Overridable so tests can walk a window boundary without sleeping.
        self.now: float | None = None

    async def check(self, bucket: str, subject: str) -> RateLimitDecision:
        policy = self.limit_for(bucket)
        if self.failure is not None:
            return RateLimitDecision(allowed=True, retry_after_seconds=0)
        now = time.time() if self.now is None else self.now
        key = counter_key(bucket, subject, window_index(now, policy.window_seconds))
        self.counters[key] += 1
        if self.counters[key] > policy.limit:
            return RateLimitDecision(
                allowed=False, retry_after_seconds=retry_after(now, policy.window_seconds)
            )
        return RateLimitDecision(allowed=True, retry_after_seconds=0)


class UnlimitedRateLimiter(RateLimiter):
    """Allows everything. What ``PULSEOS_RATE_LIMIT_ENABLED=false`` installs, and the
    default in tests so that no existing suite acquires a hidden quota."""

    async def check(self, bucket: str, subject: str) -> RateLimitDecision:
        self.limit_for(bucket)  # still validates the bucket name
        return RateLimitDecision(allowed=True, retry_after_seconds=0)


def get_rate_limiter(request: Request) -> RateLimiter:
    """The limiter installed by the lifespan. Overridable in tests, like every other port."""
    limiter: RateLimiter = request.app.state.rate_limiter
    return limiter


def resolve_limits(overrides: dict[str, str]) -> dict[str, RateLimit]:
    """``DEFAULT_LIMITS`` with any configured buckets replaced.

    An override names an existing bucket and reads ``"limit/window-seconds"``. Anything
    malformed raises here, at startup, rather than per request: a rate limit that silently
    fell back to a default because of a typo is a security control that lies.
    """
    resolved = dict(DEFAULT_LIMITS)
    for bucket, spec in overrides.items():
        if bucket not in resolved:
            raise ValueError(f"unknown rate-limit bucket {bucket!r}")
        limit, _, window = spec.partition("/")
        try:
            parsed = RateLimit(limit=int(limit), window_seconds=int(window))
        except ValueError:
            raise ValueError(
                f"rate limit for {bucket!r} must read 'limit/window-seconds', got {spec!r}"
            ) from None
        if parsed.limit < 1 or parsed.window_seconds < 1:
            raise ValueError(f"rate limit for {bucket!r} must be positive, got {spec!r}")
        resolved[bucket] = parsed
    return resolved


def build_rate_limiter(settings: Settings) -> RateLimiter:
    """The limiter this deployment runs: Redis when enabled, otherwise a permissive one."""
    limits = resolve_limits(settings.rate_limits)
    if not settings.rate_limit_enabled:
        logger.warning("rate limiting is disabled by configuration")
        return UnlimitedRateLimiter(limits)
    return RedisRateLimiter(settings.redis_url, limits)
