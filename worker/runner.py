"""The stub worker.

This is the first real caller of :mod:`app.queue`, and it exists mainly to prove
that the claim, start and lease machinery works end to end from outside the API.

**It does not analyse anything, and it does not pretend to.** It claims a job,
marks it running, and stops there. ``running`` is the handoff point: the job has
been picked up and is waiting for Stage 2 to say what happened.

There is one thing this worker very deliberately does *not* do: call
``complete``. Completing requires a :class:`~app.domain.enums.RunOutcome`, and
every one of the five is a statement about a run that has not taken place. A
stub that recorded ``completed`` - or, worse, ``no_activity_observed`` - would
be fabricating evidence, and it would do it in exactly the place the whole
project is arguing against.

What happens to a job left in ``running``, then? Its lease expires, the reaper
returns it to the queue, and after the configured number of attempts it is
cancelled with the reason recorded. That is the correct outcome for work that
was accepted and never done, and it falls out of the design rather than needing
a special case.
"""

from __future__ import annotations

import asyncio
import os
import socket
import uuid

from app.config import Settings, get_settings
from app.db.session import create_engine, create_sessionmaker
from app.logging import configure_logging, get_logger
from app.queue.base import JobQueue, Lease
from app.queue.database import DatabaseJobQueue

logger = get_logger(__name__)


def default_worker_id() -> str:
    """A worker identifier that says where it came from.

    Host and process id, so a stuck lease in the database points at a machine
    and a process rather than at an opaque token.
    """
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


class StubWorker:
    """Claim jobs and hand them to a Stage 2 that does not exist yet."""

    def __init__(
        self,
        queue: JobQueue,
        *,
        worker_id: str | None = None,
        lease_seconds: int = 300,
        poll_interval_seconds: float = 2.0,
    ) -> None:
        self.worker_id = worker_id or default_worker_id()
        self._queue = queue
        self._lease_seconds = lease_seconds
        self._poll_interval_seconds = poll_interval_seconds

    async def process_one(self) -> Lease | None:
        """Claim a job and mark it running, or return ``None`` if none is waiting.

        On any failure after the claim the job is handed straight back with
        :meth:`~app.queue.base.JobQueue.fail` rather than left to time out.
        Waiting for a lease to expire when the worker already knows it failed
        wastes the whole lease period for nothing.
        """
        lease = await self._queue.claim(self.worker_id, self._lease_seconds)
        if lease is None:
            return None

        try:
            await self._queue.start(lease.job_id, self.worker_id)
        except Exception as exc:
            await self._queue.fail(lease.job_id, self.worker_id, f"worker error: {exc}")
            raise

        logger.info(
            "job handed off for analysis",
            extra={
                "job_id": str(lease.job_id),
                "worker_id": self.worker_id,
                "attempt": lease.attempt,
            },
        )
        return lease

    async def run_forever(self) -> None:
        """Poll until cancelled.

        Polling rather than listening. ``LISTEN``/``NOTIFY`` would cut latency,
        but it is an optimisation with no measurement behind it yet, and it adds
        a second path by which a job can be noticed - and therefore a second
        path that can be wrong.
        """
        logger.info("worker started", extra={"worker_id": self.worker_id})
        try:
            while True:
                lease = await self.process_one()
                if lease is None:
                    await asyncio.sleep(self._poll_interval_seconds)
        except asyncio.CancelledError:
            logger.info("worker stopped", extra={"worker_id": self.worker_id})
            raise


async def main(settings: Settings | None = None) -> None:
    """Run one worker against the configured database until interrupted."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    engine = create_engine(settings)
    sessionmaker = create_sessionmaker(engine)
    try:
        async with sessionmaker() as session:
            worker = StubWorker(
                DatabaseJobQueue(session),
                lease_seconds=settings.job_lease_seconds,
                poll_interval_seconds=settings.worker_poll_seconds,
            )
            await worker.run_forever()
    finally:
        await engine.dispose()
