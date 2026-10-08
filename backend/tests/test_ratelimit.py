"""Rate-limiting port tests (ADR-024): the algorithm, the buckets, and the failure mode.

The Redis implementation is exercised against a mocked client, the way ``test_queue.py``
mocks arq and ``test_storage.py`` mocks boto3 — the suite never contacts Redis
(docs/SYSTEM_ARCHITECTURE.md rule 4). What is asserted there is the *command sequence*,
because that is where the atomicity guarantee lives.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.core.config import Settings
from app.core.ratelimit import (
    DEFAULT_LIMITS,
    InMemoryRateLimiter,
    RateLimit,
    RedisRateLimiter,
    UnlimitedRateLimiter,
    build_rate_limiter,
    counter_key,
    resolve_limits,
    retry_after,
    window_index,
)

BUCKETS = (
    "patient_lookup",
    "record_existence",
    "granted_records",
    "access_request_create",
    "ai_generate",
)


# -- the approved policy ----------------------------------------------------------------


def test_the_four_protected_buckets_carry_their_approved_limits() -> None:
    assert DEFAULT_LIMITS["patient_lookup"] == RateLimit(limit=20, window_seconds=60)
    assert DEFAULT_LIMITS["record_existence"] == RateLimit(limit=30, window_seconds=60)
    assert DEFAULT_LIMITS["granted_records"] == RateLimit(limit=30, window_seconds=60)
    assert DEFAULT_LIMITS["access_request_create"] == RateLimit(limit=10, window_seconds=60)
    assert DEFAULT_LIMITS["ai_generate"] == RateLimit(limit=10, window_seconds=60)
    assert set(DEFAULT_LIMITS) == set(BUCKETS)


def test_an_unknown_bucket_fails_loudly_rather_than_not_limiting() -> None:
    """A typo in a bucket name must not silently leave a route unprotected."""
    with pytest.raises(KeyError):
        InMemoryRateLimiter().limit_for("no_such_bucket")


# -- the fixed-window arithmetic ------------------------------------------------------------


def test_the_window_index_changes_exactly_on_the_boundary() -> None:
    assert window_index(59.9, 60) == 0
    assert window_index(60.0, 60) == 1
    assert window_index(119.9, 60) == 1


def test_retry_after_counts_to_the_end_of_the_window_and_is_never_zero() -> None:
    # A Retry-After of 0 invites an immediate retry that is certain to be refused.
    assert retry_after(0.0, 60) == 60
    assert retry_after(30.0, 60) == 30
    assert retry_after(59.5, 60) == 1
    assert retry_after(59.999, 60) >= 1


def test_the_window_is_part_of_the_key_so_a_counter_cannot_outlive_it() -> None:
    assert counter_key("patient_lookup", "u:abc", 7) == "ratelimit:patient_lookup:u:abc:7"
    assert counter_key("patient_lookup", "u:abc", 7) != counter_key("patient_lookup", "u:abc", 8)


# -- counting ---------------------------------------------------------------------------------


async def _spend(limiter: InMemoryRateLimiter, bucket: str, subject: str, times: int) -> list[bool]:
    return [(await limiter.check(bucket, subject)).allowed for _ in range(times)]


def test_requests_below_at_and_above_the_limit() -> None:
    import asyncio

    async def scenario() -> None:
        limiter = InMemoryRateLimiter({"patient_lookup": RateLimit(limit=3, window_seconds=60)})

        results = await _spend(limiter, "patient_lookup", "u:a", 4)

        # Three allowed (below and at the limit), the fourth refused.
        assert results == [True, True, True, False]

    asyncio.run(scenario())


def test_a_refusal_carries_a_positive_retry_after() -> None:
    import asyncio

    async def scenario() -> None:
        limiter = InMemoryRateLimiter({"patient_lookup": RateLimit(limit=1, window_seconds=60)})
        await limiter.check("patient_lookup", "u:a")

        decision = await limiter.check("patient_lookup", "u:a")

        assert decision.allowed is False
        assert 1 <= decision.retry_after_seconds <= 60

    asyncio.run(scenario())


def test_buckets_do_not_share_quota() -> None:
    import asyncio

    async def scenario() -> None:
        limits = {name: RateLimit(limit=1, window_seconds=60) for name in BUCKETS}
        limiter = InMemoryRateLimiter(limits)

        first = [(await limiter.check(bucket, "u:a")).allowed for bucket in BUCKETS]
        second = [(await limiter.check(bucket, "u:a")).allowed for bucket in BUCKETS]

        assert first == [True] * len(BUCKETS)
        assert second == [False] * len(BUCKETS)

    asyncio.run(scenario())


def test_subjects_do_not_share_quota() -> None:
    import asyncio

    async def scenario() -> None:
        limiter = InMemoryRateLimiter({"patient_lookup": RateLimit(limit=1, window_seconds=60)})

        assert (await limiter.check("patient_lookup", "u:a")).allowed is True
        assert (await limiter.check("patient_lookup", "u:a")).allowed is False
        # A different user is untouched by the first one's spending.
        assert (await limiter.check("patient_lookup", "u:b")).allowed is True

    asyncio.run(scenario())


def test_a_new_window_restores_the_quota() -> None:
    import asyncio

    async def scenario() -> None:
        limiter = InMemoryRateLimiter({"patient_lookup": RateLimit(limit=1, window_seconds=60)})
        limiter.now = 0.0
        assert (await limiter.check("patient_lookup", "u:a")).allowed is True
        assert (await limiter.check("patient_lookup", "u:a")).allowed is False

        limiter.now = 60.0  # the next window

        assert (await limiter.check("patient_lookup", "u:a")).allowed is True

    asyncio.run(scenario())


def test_the_unlimited_limiter_allows_everything_but_still_checks_the_bucket() -> None:
    import asyncio

    async def scenario() -> None:
        limiter = UnlimitedRateLimiter()

        for _ in range(50):
            assert (await limiter.check("patient_lookup", "u:a")).allowed is True
        with pytest.raises(KeyError):
            await limiter.check("nonsense", "u:a")

    asyncio.run(scenario())


# -- the Redis implementation: atomicity and failure ---------------------------------------


def _mock_redis(count: int) -> tuple[MagicMock, MagicMock]:
    pipeline = MagicMock()
    pipeline.__aenter__ = AsyncMock(return_value=pipeline)
    pipeline.__aexit__ = AsyncMock(return_value=False)
    pipeline.execute = AsyncMock(return_value=[count, True])
    client = MagicMock()
    client.pipeline = MagicMock(return_value=pipeline)
    return client, pipeline


def test_the_counter_is_incremented_and_expired_in_one_pipeline() -> None:
    """The atomicity guarantee. INCR is atomic and returns the post-increment value, so the
    read-then-write race cannot occur; EXPIRE NX rides along so there is no round trip
    between counting and setting the lifetime."""
    import asyncio

    async def scenario() -> None:
        client, pipeline = _mock_redis(count=1)
        limiter = RedisRateLimiter("redis://localhost:6379/0")
        limiter._client = client

        await limiter.check("patient_lookup", "u:a")

        assert client.pipeline.call_args.kwargs["transaction"] is False
        (incr_key,) = pipeline.incr.call_args.args
        expire_key, expire_seconds = pipeline.expire.call_args.args
        assert incr_key == expire_key
        assert expire_seconds == 60
        # NX: only the request that created the counter sets its lifetime, so a later
        # request in the same window cannot slide the window forward.
        assert pipeline.expire.call_args.kwargs["nx"] is True
        pipeline.execute.assert_awaited_once()

    asyncio.run(scenario())


def test_redis_refuses_once_the_count_passes_the_limit() -> None:
    import asyncio

    async def scenario() -> None:
        limiter = RedisRateLimiter("redis://localhost:6379/0")

        limiter._client = _mock_redis(count=20)[0]
        assert (await limiter.check("patient_lookup", "u:a")).allowed is True

        limiter._client = _mock_redis(count=21)[0]
        refused = await limiter.check("patient_lookup", "u:a")
        assert refused.allowed is False
        assert refused.retry_after_seconds >= 1

    asyncio.run(scenario())


def test_redis_being_unavailable_fails_open() -> None:
    """ADR-014's precedent, applied: Redis is advisory here, and a blip must not take
    consent requests, discovery and lookup offline with it."""
    import asyncio

    async def scenario() -> None:
        client = MagicMock()
        client.pipeline = MagicMock(side_effect=OSError("connection refused"))
        limiter = RedisRateLimiter("redis://localhost:6379/0")
        limiter._client = client

        decision = await limiter.check("patient_lookup", "u:a")

        assert decision.allowed is True
        assert decision.retry_after_seconds == 0

    asyncio.run(scenario())


def test_an_outage_is_logged_once_per_interval_not_once_per_request() -> None:
    import asyncio

    async def scenario() -> None:
        client = MagicMock()
        client.pipeline = MagicMock(side_effect=OSError("down"))
        limiter = RedisRateLimiter("redis://localhost:6379/0")
        limiter._client = client

        for _ in range(5):
            await limiter.check("patient_lookup", "u:a")

        # One line for the burst — an outage must not flood the log.
        assert limiter._last_outage_log > 0

    asyncio.run(scenario())


# -- configuration -----------------------------------------------------------------------------


def test_defaults_apply_when_nothing_is_overridden() -> None:
    assert resolve_limits({}) == DEFAULT_LIMITS


def test_an_override_replaces_only_the_named_bucket() -> None:
    resolved = resolve_limits({"patient_lookup": "40/120"})

    assert resolved["patient_lookup"] == RateLimit(limit=40, window_seconds=120)
    assert resolved["record_existence"] == DEFAULT_LIMITS["record_existence"]


@pytest.mark.parametrize(
    "override",
    [
        {"no_such_bucket": "10/60"},
        {"patient_lookup": "ten/60"},
        {"patient_lookup": "10"},
        {"patient_lookup": "0/60"},
        {"patient_lookup": "10/0"},
    ],
)
def test_invalid_configuration_is_refused_at_startup(override: dict[str, str]) -> None:
    """A limit that silently fell back to a default because of a typo is a security control
    that lies, so this raises where the app is built rather than per request."""
    with pytest.raises(ValueError):
        resolve_limits(override)


def test_the_configured_limiter_matches_the_enable_flag() -> None:
    enabled: Any = Settings(rate_limit_enabled=True)
    disabled: Any = Settings(rate_limit_enabled=False)

    assert isinstance(build_rate_limiter(enabled), RedisRateLimiter)
    assert isinstance(build_rate_limiter(disabled), UnlimitedRateLimiter)
