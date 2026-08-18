"""Rate limiting, behind an interface.

The interface exists because the implementation is wrong for more than one
process. An in-memory bucket limits each worker separately, so four workers
enforce four times the configured rate. That is an acceptable trade for a single
process today and unacceptable the moment this runs behind a load balancer,
which is exactly why callers depend on :class:`RateLimiter` rather than on the
dictionary underneath it - swapping in Redis then touches this file and nothing
else.

A token bucket rather than a fixed window. A fixed window lets a caller spend
its entire allowance in the last second of one window and again in the first
second of the next, producing a burst of twice the limit at the boundary. A
bucket refills continuously and has no boundary to exploit, while still
permitting a genuine burst up to its capacity, which is what a submission
pipeline flushing a backlog actually looks like.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@runtime_checkable
class RateLimiter(Protocol):
    """Decides whether one more request from a caller is allowed."""

    async def allow(self, key: str) -> bool:
        """Consume one unit of allowance, reporting whether there was any.

        The key identifies the caller - an API key id here, never an IP
        address, because the callers are known systems rather than anonymous
        browsers.
        """
        ...

    async def retry_after(self, key: str) -> float:
        """Seconds until the caller would be allowed again.

        Returned to the client, so a well-behaved caller can wait exactly long
        enough instead of retrying blindly and making the problem worse.
        """
        ...


@dataclass
class _Bucket:
    tokens: float
    updated_at: float = field(default_factory=time.monotonic)


class TokenBucketRateLimiter:
    """An in-process token bucket per caller.

    ``time.monotonic`` rather than wall-clock time: a clock adjustment must not
    hand out free allowance or lock a caller out.
    """

    def __init__(self, rate_per_minute: int, burst: int | None = None) -> None:
        if rate_per_minute <= 0:
            raise ValueError("rate_per_minute must be positive.")

        self._capacity = float(burst if burst is not None else rate_per_minute)
        self._refill_per_second = rate_per_minute / 60.0
        self._buckets: dict[str, _Bucket] = {}
        self._lock = asyncio.Lock()

    async def allow(self, key: str) -> bool:
        async with self._lock:
            bucket = self._refill(key)
            if bucket.tokens < 1.0:
                return False
            bucket.tokens -= 1.0
            return True

    async def retry_after(self, key: str) -> float:
        async with self._lock:
            bucket = self._refill(key)
            if bucket.tokens >= 1.0:
                return 0.0
            return (1.0 - bucket.tokens) / self._refill_per_second

    def _refill(self, key: str) -> _Bucket:
        """Top the bucket up for the time that has passed since it was last read.

        Refilling lazily, on access, rather than on a timer: a caller that has
        gone quiet costs nothing, and there is no background task to supervise.
        """
        now = time.monotonic()
        bucket = self._buckets.get(key)

        if bucket is None:
            bucket = _Bucket(tokens=self._capacity, updated_at=now)
            self._buckets[key] = bucket
            return bucket

        elapsed = max(0.0, now - bucket.updated_at)
        bucket.tokens = min(self._capacity, bucket.tokens + elapsed * self._refill_per_second)
        bucket.updated_at = now
        return bucket
