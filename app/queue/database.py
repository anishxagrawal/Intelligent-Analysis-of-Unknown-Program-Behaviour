"""The PostgreSQL job queue.

The interesting method is :meth:`DatabaseJobQueue.claim`, and everything else is
bookkeeping around it.

Why the database and not a broker: the jobs already live here, and a separate
broker would mean two systems that can disagree about what is queued. A row is
claimed and its state recorded in one transaction, so there is no window in
which a job has been handed out but not recorded, or recorded but not handed
out. That is worth more at this scale than the throughput a broker would add.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, noload

from app.domain.enums import JobStatus, RunOutcome
from app.domain.models import Job
from app.logging import get_logger
from app.queue.base import Lease, LeaseLostError, ReapResult, UnknownJobError

logger = get_logger(__name__)


class DatabaseJobQueue:
    """A queue backed by the ``jobs`` table.

    One instance wraps one session, and therefore one transaction at a time.
    Workers each hold their own, which is what allows the claim below to be
    contended for real rather than serialised by accident.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue(self, job: Job) -> None:
        """Add the job to the caller's transaction.

        No commit. The caller decides when the job becomes visible, because the
        caller is the only one who knows whether the rest of its work - the
        sample row, the stored object - is in place yet.
        """
        job.status = JobStatus.QUEUED
        self._session.add(job)

    async def claim(self, worker_id: str, lease_seconds: int) -> Lease | None:
        """Claim the oldest queued job, atomically.

        The whole claim is one statement:

            UPDATE jobs SET ... WHERE id = (
                SELECT id FROM jobs WHERE status = 'queued'
                ORDER BY created_at LIMIT 1
                FOR UPDATE SKIP LOCKED
            ) RETURNING ...

        ``FOR UPDATE`` locks the candidate row; ``SKIP LOCKED`` makes a
        concurrent claimer step over rows already locked by someone else rather
        than block behind them. The two together give the property AC-15
        demands: N workers claiming at once take N different jobs, and nobody
        waits.

        The obvious alternative - select a queued job, then update it - has a
        gap between the two statements in which another worker reads the same
        row. It passes every single-threaded test and fails in production.
        """
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=lease_seconds)

        # An alias keeps the subquery from correlating to the UPDATE target,
        # which would silently turn it into a per-row lookup.
        candidate = aliased(Job, name="candidate")
        oldest_queued = (
            select(candidate.id)
            .where(candidate.status == JobStatus.QUEUED)
            .order_by(candidate.created_at)
            .limit(1)
            .with_for_update(skip_locked=True, of=candidate)
            .scalar_subquery()
        )

        statement = (
            update(Job)
            .where(Job.id == oldest_queued)
            .values(
                status=JobStatus.CLAIMED,
                claimed_by=worker_id,
                claimed_at=now,
                lease_expires_at=expires_at,
                attempts=Job.attempts + 1,
            )
            .returning(Job.id, Job.lease_expires_at, Job.attempts)
            .execution_options(synchronize_session=False)
        )

        result = await self._session.execute(statement)
        row = result.first()
        if row is None:
            await self._session.rollback()
            return None

        await self._session.commit()
        logger.info(
            "job claimed",
            extra={"job_id": str(row.id), "worker_id": worker_id, "attempt": row.attempts},
        )
        return Lease(
            job_id=row.id,
            worker_id=worker_id,
            expires_at=row.lease_expires_at,
            attempt=row.attempts,
        )

    async def start(self, job_id: uuid.UUID, worker_id: str) -> None:
        """Record that the run has begun."""
        job = await self._lock(job_id, worker_id)
        job.transition_to(JobStatus.RUNNING)
        await self._session.commit()

    async def heartbeat(self, job_id: uuid.UUID, worker_id: str, lease_seconds: int) -> Lease:
        """Push the lease out, proving this worker is still alive."""
        job = await self._lock(job_id, worker_id)
        job.grant_lease(worker_id, lease_seconds)
        await self._session.commit()

        assert job.lease_expires_at is not None  # just granted
        return Lease(
            job_id=job.id,
            worker_id=worker_id,
            expires_at=job.lease_expires_at,
            attempt=job.attempts,
        )

    async def complete(self, job_id: uuid.UUID, worker_id: str, outcome: RunOutcome) -> None:
        """Finish the job with the outcome the run produced."""
        job = await self._lock(job_id, worker_id)
        job.transition_to(JobStatus.FINISHED, run_outcome=outcome)
        await self._session.commit()
        logger.info(
            "job finished",
            extra={"job_id": str(job_id), "worker_id": worker_id, "outcome": outcome.value},
        )

    async def fail(self, job_id: uuid.UUID, worker_id: str, reason: str) -> None:
        """Hand the job back after the worker, not the sample, failed."""
        job = await self._lock(job_id, worker_id)
        job.transition_to(JobStatus.QUEUED, failure_reason=reason)
        await self._session.commit()
        logger.warning(
            "job returned to queue",
            extra={"job_id": str(job_id), "worker_id": worker_id, "reason": reason},
        )

    async def reap_expired(self, max_attempts: int) -> ReapResult:
        """Take back jobs whose owners stopped renewing their lease.

        Two statements, one transaction. Jobs with attempts remaining go back to
        the queue; jobs that have used them all are cancelled with the reason
        recorded, because a job retried forever is a queue that never drains.

        Note what cancellation does *not* do: it records no run outcome. Nothing
        is known about the sample - a worker died, which says nothing about the
        file - and inventing an outcome here would be exactly the false
        certainty this project exists to avoid.
        """
        now = datetime.now(UTC)
        held = (Job.status.in_((JobStatus.CLAIMED, JobStatus.RUNNING))) & (
            Job.lease_expires_at <= now
        )

        requeue = (
            update(Job)
            .where(held, Job.attempts < max_attempts)
            .values(
                status=JobStatus.QUEUED,
                claimed_by=None,
                claimed_at=None,
                lease_expires_at=None,
                started_at=None,
                failure_reason="lease expired before the worker reported a result",
            )
            .returning(Job.id)
            .execution_options(synchronize_session=False)
        )
        requeued = list((await self._session.execute(requeue)).scalars())

        abandon = (
            update(Job)
            .where(held, Job.attempts >= max_attempts)
            .values(
                status=JobStatus.CANCELLED,
                claimed_by=None,
                claimed_at=None,
                lease_expires_at=None,
                finished_at=now,
                failure_reason=(
                    f"abandoned after {max_attempts} attempts; no worker reported a result"
                ),
            )
            .returning(Job.id)
            .execution_options(synchronize_session=False)
        )
        abandoned = list((await self._session.execute(abandon)).scalars())

        await self._session.commit()

        if requeued or abandoned:
            logger.warning(
                "expired leases reclaimed",
                extra={"requeued": len(requeued), "abandoned": len(abandoned)},
            )
        return ReapResult(requeued=requeued, abandoned=abandoned)

    async def _lock(self, job_id: uuid.UUID, worker_id: str) -> Job:
        """Load the job for update and verify this worker still owns it.

        The row lock closes the window between checking ownership and acting on
        it. ``noload`` suppresses the eager join to ``samples``: locking is for
        this row alone, and dragging a second table into the lock would widen
        contention for nothing.
        """
        statement = (
            select(Job)
            .where(Job.id == job_id)
            .options(noload(Job.sample))
            .with_for_update(of=Job)
        )
        job = (await self._session.execute(statement)).scalar_one_or_none()

        if job is None:
            await self._session.rollback()
            raise UnknownJobError(f"No job with id {job_id}.")

        if job.claimed_by != worker_id:
            # Read the holder before rolling back. A rollback expires every
            # loaded attribute, and reading one afterwards would trigger a
            # refresh from inside the error path.
            holder = job.claimed_by
            await self._session.rollback()
            raise LeaseLostError(
                f"Job {job_id} is not held by {worker_id!r} (current holder: {holder!r})."
            )

        return job
