"""Keys, scopes and rate limiting, away from the database.

The parts tested here are the ones where a subtle mistake is invisible from the
outside: a hash that is not what is stored, a scope set that widens by accident,
a limiter that lets a burst through at a window boundary.
"""

from __future__ import annotations

import asyncio

import pytest

from app.security.keys import KEY_PREFIX, generate_key, hash_key, matches
from app.security.ratelimit import RateLimiter, TokenBucketRateLimiter
from app.security.scopes import ALL_SCOPES, Scope, parse_scopes

pytestmark = pytest.mark.unit


# -- Keys ------------------------------------------------------------------


def test_generated_keys_are_unique() -> None:
    assert generate_key().token != generate_key().token


def test_generated_keys_are_recognisable() -> None:
    """So a key pasted into the wrong field is spottable in a log or a ticket."""
    assert generate_key().token.startswith(KEY_PREFIX)


def test_the_stored_form_is_a_hash_not_the_key() -> None:
    issued = generate_key()

    assert issued.token_hash != issued.token
    assert issued.token not in issued.token_hash
    assert len(issued.token_hash) == 64


def test_hashing_is_deterministic() -> None:
    """Authentication is a lookup by this value, so it has to be stable."""
    assert hash_key("upa_example") == hash_key("upa_example")


def test_matching_accepts_the_right_key_and_rejects_the_rest() -> None:
    issued = generate_key()

    assert matches(issued.token, issued.token_hash)
    assert not matches(issued.token + "x", issued.token_hash)
    assert not matches("", issued.token_hash)


# -- Scopes ----------------------------------------------------------------


def test_the_three_scopes_are_the_ones_documented() -> None:
    assert {scope.value for scope in Scope} == {
        "submissions:write",
        "jobs:read",
        "samples:download",
    }


def test_downloading_is_its_own_scope() -> None:
    """Reading that a job finished is unremarkable; pulling the bytes is not."""
    assert Scope.SAMPLES_DOWNLOAD not in {Scope.JOBS_READ, Scope.SUBMISSIONS_WRITE}


def test_unknown_scopes_grant_nothing() -> None:
    """A key issued by another version must never widen into a new permission."""
    assert parse_scopes(["jobs:read", "everything", "admin"]) == {Scope.JOBS_READ}


def test_parsing_every_scope_round_trips() -> None:
    assert parse_scopes([scope.value for scope in Scope]) == ALL_SCOPES


# -- Rate limiting ---------------------------------------------------------


def test_a_limiter_needs_a_positive_rate() -> None:
    with pytest.raises(ValueError, match="positive"):
        TokenBucketRateLimiter(rate_per_minute=0)


def test_the_token_bucket_satisfies_the_protocol() -> None:
    """So Redis can replace it without touching a caller."""
    assert isinstance(TokenBucketRateLimiter(rate_per_minute=60), RateLimiter)


async def test_a_caller_may_spend_its_burst_then_stops() -> None:
    limiter = TokenBucketRateLimiter(rate_per_minute=60, burst=3)

    allowed = [await limiter.allow("key-1") for _ in range(4)]

    assert allowed == [True, True, True, False]


async def test_callers_are_limited_separately() -> None:
    """One noisy client must not throttle everybody else."""
    limiter = TokenBucketRateLimiter(rate_per_minute=60, burst=1)

    assert await limiter.allow("key-1") is True
    assert await limiter.allow("key-1") is False
    assert await limiter.allow("key-2") is True


async def test_the_bucket_refills_over_time() -> None:
    """Continuous refill is what removes the window boundary a fixed window has."""
    limiter = TokenBucketRateLimiter(rate_per_minute=6000, burst=1)

    assert await limiter.allow("key-1") is True
    assert await limiter.allow("key-1") is False

    await asyncio.sleep(0.05)

    assert await limiter.allow("key-1") is True


async def test_retry_after_is_zero_while_allowance_remains() -> None:
    limiter = TokenBucketRateLimiter(rate_per_minute=60, burst=2)

    assert await limiter.retry_after("key-1") == 0.0


async def test_retry_after_says_how_long_to_wait() -> None:
    """A caller told exactly how long to wait stops retrying blindly."""
    limiter = TokenBucketRateLimiter(rate_per_minute=60, burst=1)
    await limiter.allow("key-1")

    wait = await limiter.retry_after("key-1")

    assert 0.0 < wait <= 1.0


async def test_concurrent_callers_cannot_exceed_the_burst() -> None:
    """The bucket is shared state; without the lock, requests race past the cap."""
    limiter = TokenBucketRateLimiter(rate_per_minute=60, burst=5)

    results = await asyncio.gather(*(limiter.allow("key-1") for _ in range(20)))

    assert sum(results) == 5
