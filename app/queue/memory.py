"""In-memory job queue.

The second implementation, and the reason the protocol can be trusted. A
contract suite that only ever runs against PostgreSQL proves the queue works;
running the same suite against a dictionary proves the *interface* works, and
that no caller has quietly come to depend on SQL semantics.

Concurrency is handled by a single lock rather than by anything clever. The
correctness argument is different from the database backend's - one lock, one
claimer at a time - but the guarantee callers see is the same: a job is handed
out exactly once.

Never use this in production. It forgets everything when the process exits, and
a job in flight at that moment is simply gone.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from app.domain.enums import JobStatus, RunOutcome
from app.domain.models import Job
from app.queue.base import Lease, LeaseLostError, ReapResult, UnknownJobError


class InMemoryJobQueue:
    """Keep jobs in a dictionary, ordered by arrival."""

    def __init__(self) -> None:
        self._jobs: dict[uuid.UUID, Job] = {}
        self._order: list[uuid.UUID] = []
        self._lock = asyncio.Lock()

    async def enqueue(self, job: Job) -> None:
        # Column defaults are applied by the database at flush time. Nothing
        # flushes here, so anything the rest of this class reads has to be
        # filled in now.
        #
        # getattr rather than a direct comparison: the mapped types say these
        # are never None, which is true of a loaded row and not of one that has
        # only been constructed.
        if getattr(job, "id", None) is None:
            job.id = uuid.uuid4()
        if getattr(job, "attempts", None) is None:
            job.attempts = 0
        job.status = JobStatus.QUEUED

        async with self._lock:
            if job.id not in self._jobs:
                self._order.append(job.id)
            self._jobs[job.id] = job

    async def claim(self, worker_id: str, lease_seconds: int) -> Lease | None:
        async with self._lock:
            for job_id in self._order:
                job = self._jobs[job_id]
                if job.status is not JobStatus.QUEUED:
                    continue

                job.attempts += 1
                job.transition_to(JobStatus.CLAIMED)
                job.grant_lease(worker_id, lease_seconds)

                assert job.lease_expires_at is not None  # just granted
                return Lease(
                    job_id=job_id,
                    worker_id=worker_id,
                    expires_at=job.lease_expires_at,
                    attempt=job.attempts,
                )
        return None

    async def start(self, job_id: uuid.UUID, worker_id: str) -> None:
        async with self._lock:
            self._owned(job_id, worker_id).transition_to(JobStatus.RUNNING)

    async def heartbeat(self, job_id: uuid.UUID, worker_id: str, lease_seconds: int) -> Lease:
        async with self._lock:
            job = self._owned(job_id, worker_id)
            job.grant_lease(worker_id, lease_seconds)

            assert job.lease_expires_at is not None  # just granted
            return Lease(
                job_id=job_id,
                worker_id=worker_id,
                expires_at=job.lease_expires_at,
                attempt=job.attempts,
            )

    async def complete(self, job_id: uuid.UUID, worker_id: str, outcome: RunOutcome) -> None:
        async with self._lock:
            job = self._owned(job_id, worker_id)
            job.transition_to(JobStatus.FINISHED, run_outcome=outcome)

    async def fail(self, job_id: uuid.UUID, worker_id: str, reason: str) -> None:
        async with self._lock:
            job = self._owned(job_id, worker_id)
            job.transition_to(JobStatus.QUEUED, failure_reason=reason)

    async def reap_expired(self, max_attempts: int) -> ReapResult:
        result = ReapResult()
        now = datetime.now(UTC)

        async with self._lock:
            for job_id in self._order:
                job = self._jobs[job_id]
                if job.status not in (JobStatus.CLAIMED, JobStatus.RUNNING):
                    continue
                if job.lease_expires_at is None or job.lease_expires_at > now:
                    continue

                if job.attempts < max_attempts:
                    job.transition_to(
                        JobStatus.QUEUED,
                        failure_reason="lease expired before the worker reported a result",
                    )
                    result.requeued.append(job_id)
                else:
                    job.transition_to(
                        JobStatus.CANCELLED,
                        failure_reason=(
                            f"abandoned after {max_attempts} attempts; "
                            "no worker reported a result"
                        ),
                    )
                    result.abandoned.append(job_id)

        return result

    def _owned(self, job_id: uuid.UUID, worker_id: str) -> Job:
        """Return the job, or raise if it is missing or held by somebody else."""
        job = self._jobs.get(job_id)
        if job is None:
            raise UnknownJobError(f"No job with id {job_id}.")
        if job.claimed_by != worker_id:
            raise LeaseLostError(
                f"Job {job_id} is not held by {worker_id!r} "
                f"(current holder: {job.claimed_by!r})."
            )
        return job
