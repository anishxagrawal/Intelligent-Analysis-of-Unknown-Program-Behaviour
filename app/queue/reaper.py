"""The reaper: policy for taking work back.

Detecting an expired lease belongs to the queue, because it is a storage
question. Deciding how often to look, and what to do when the answer is "yes,
several", is policy, and it lives here.

The reaper exists because a crashed worker cannot report that it crashed. Every
other failure mode announces itself; this one is silent by construction, and
without something sweeping for it a job handed to a process that dies is lost
with no error anywhere.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.logging import get_logger
from app.queue.base import JobQueue, ReapResult

logger = get_logger(__name__)


class Reaper:
    """Periodically return abandoned jobs to the queue."""

    def __init__(
        self,
        queue_factory: Callable[[], Awaitable[JobQueue]] | None = None,
        *,
        queue: JobQueue | None = None,
        max_attempts: int = 3,
        interval_seconds: float = 30.0,
    ) -> None:
        """Take either a queue or a factory that produces one.

        A long-running reaper wants a fresh session each pass, so it takes a
        factory. Tests want to watch a single queue, so they pass one directly.
        """
        if (queue is None) == (queue_factory is None):
            raise ValueError("Provide exactly one of queue or queue_factory.")

        self._queue = queue
        self._queue_factory = queue_factory
        self._max_attempts = max_attempts
        self._interval_seconds = interval_seconds

    async def sweep_once(self) -> ReapResult:
        """Run a single pass and report what it found."""
        queue = self._queue if self._queue is not None else await self._require_factory()()
        return await queue.reap_expired(self._max_attempts)

    async def run_forever(self) -> None:
        """Sweep on a fixed interval until cancelled.

        A failed sweep is logged and the loop continues. The reaper going quiet
        because one database blip raised would reintroduce exactly the silent
        loss it exists to prevent.
        """
        logger.info("reaper started", extra={"interval_seconds": self._interval_seconds})
        try:
            while True:
                try:
                    await self.sweep_once()
                except Exception:  # deliberately never fatal
                    logger.exception("reaper sweep failed")
                await asyncio.sleep(self._interval_seconds)
        except asyncio.CancelledError:
            logger.info("reaper stopped")
            raise

    def _require_factory(self) -> Callable[[], Awaitable[JobQueue]]:
        assert self._queue_factory is not None  # guaranteed by __init__
        return self._queue_factory
