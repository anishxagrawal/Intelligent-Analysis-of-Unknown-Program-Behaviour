"""The job queue boundary.

Like :mod:`app.storage.base`, this protocol was pulled out of working code once
two callers existed to shape it - the stub worker and the reaper - rather than
sketched in advance.

Every method takes the worker id, and every method verifies it. That repetition
is the point. Ownership is granted for a limited time, so any worker may
discover that the job it thought it held was reclaimed and handed to somebody
else while it was busy. A worker that reports a result for a job it no longer
owns must be refused, otherwise two workers can write conflicting outcomes for
the same job and the later one silently wins.

Deliberately absent: priorities, delays, retries with backoff, dead-letter
queues. None of them has a caller yet. What is here is the minimum that lets
work be handed out safely and taken back when a worker dies.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from app.domain.enums import RunOutcome

if TYPE_CHECKING:  # pragma: no cover - import cycle only matters to type checkers
    from app.domain.models import Job


class QueueError(Exception):
    """Base class for queue failures."""


class UnknownJobError(QueueError):
    """Raised when an operation names a job the queue has never seen."""


class LeaseLostError(QueueError):
    """Raised when a worker acts on a job it no longer owns.

    The usual cause is a lease that expired while the worker was working: the
    reaper returned the job to the queue, another worker took it, and the
    original worker has now come back with a result nobody asked for. Refusing
    it is what stops two workers from both writing an outcome.
    """


@dataclass(frozen=True)
class Lease:
    """Proof that one worker holds one job until a stated moment."""

    job_id: uuid.UUID
    worker_id: str
    expires_at: datetime
    attempt: int


@dataclass(frozen=True)
class ReapResult:
    """What one pass of the reaper did.

    ``requeued`` jobs are available again. ``abandoned`` jobs ran out of
    attempts and were cancelled, which is a decision worth surfacing rather
    than burying in a log line.
    """

    requeued: list[uuid.UUID] = field(default_factory=list)
    abandoned: list[uuid.UUID] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.requeued) + len(self.abandoned)


@runtime_checkable
class JobQueue(Protocol):
    """Somewhere jobs can wait, be claimed exactly once, and be given back."""

    async def enqueue(self, job: Job) -> None:
        """Make ``job`` available to workers.

        The job becomes claimable when the caller's transaction commits, not
        when this returns. That is required rather than incidental: a job which
        became visible before the sample row it points at would be handed to a
        worker that cannot read its own input.
        """
        ...

    async def claim(self, worker_id: str, lease_seconds: int) -> Lease | None:
        """Take ownership of one queued job, or return ``None`` if none is waiting.

        Must be atomic. Two workers calling this at the same instant must never
        receive the same job - not "rarely", not "usually not". A read followed
        by a write looks correct and fails under load.
        """
        ...

    async def start(self, job_id: uuid.UUID, worker_id: str) -> None:
        """Mark that the run has actually begun.

        Separate from :meth:`claim` because the gap between taking a job and
        starting it is real work - fetching the sample, preparing an
        environment - and a worker that dies in that gap should be
        distinguishable from one that died mid-run.
        """
        ...

    async def heartbeat(self, job_id: uuid.UUID, worker_id: str, lease_seconds: int) -> Lease:
        """Extend the lease, proving the worker is still alive.

        Raises :class:`LeaseLostError` if the job has already been reclaimed,
        which is how a worker learns to stop wasting effort on work that is no
        longer its own.
        """
        ...

    async def complete(self, job_id: uuid.UUID, worker_id: str, outcome: RunOutcome) -> None:
        """Finish the job with the outcome the run produced.

        The outcome is required. There is no way to finish a job without
        saying what happened, which is the whole reason the outcome vocabulary
        exists.
        """
        ...

    async def fail(self, job_id: uuid.UUID, worker_id: str, reason: str) -> None:
        """Give the job back after an infrastructure failure.

        Not the same as an unsuccessful run. ``timed_out`` and
        ``crashed_on_launch`` are things the *sample* did, and they are
        reported through :meth:`complete`. This method is for the worker
        failing: no image, no disk, no network. The job returns to the queue
        until its attempts are exhausted.
        """
        ...

    async def reap_expired(self, max_attempts: int) -> ReapResult:
        """Return jobs whose leases have lapsed, and give up on the hopeless.

        Lives on the queue rather than in the reaper because detecting expiry
        is storage-specific, while deciding how often to look and what to do
        about it is policy - see :mod:`app.queue.reaper`.
        """
        ...
