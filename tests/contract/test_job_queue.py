"""The contract every JobQueue implementation must satisfy.

AC-22. Every test here runs twice: once against PostgreSQL and once against the
dictionary. That is the whole value of the file. A suite that only ever ran
against the database would prove the database backend works while quietly
allowing SQL-shaped assumptions to leak into callers; running the identical
assertions against an implementation with nothing in common but the interface is
what shows the interface is real.

Where the two backends differ - transactions, locking, durability - the
difference must be invisible from here. If a test needs to know which backend it
is talking to, the protocol has a hole in it.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.enums import JobStatus, RunOutcome
from app.domain.lifecycle import IllegalTransitionError
from app.domain.models import Job, Sample
from app.queue.base import JobQueue, LeaseLostError, UnknownJobError
from app.queue.database import DatabaseJobQueue
from app.queue.memory import InMemoryJobQueue

pytestmark = pytest.mark.contract

LEASE_SECONDS = 60


@dataclass
class Harness:
    """A queue plus the two things a test needs to do around it."""

    queue: JobQueue
    enqueue_new: Callable[[], Awaitable[uuid.UUID]]
    read_status: Callable[[uuid.UUID], Awaitable[JobStatus]]


@pytest_asyncio.fixture(params=["memory", "database"])
async def harness(
    request: pytest.FixtureRequest,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[Harness]:
    """One harness per backend, exercised by every test in this module."""
    if request.param == "memory":
        yield _memory_harness()
        return

    async with sessionmaker() as queue_session:
        yield _database_harness(sessionmaker, queue_session)


def _memory_harness() -> Harness:
    queue = InMemoryJobQueue()

    async def enqueue_new() -> uuid.UUID:
        job = Job(
            id=uuid.uuid4(),
            original_filename="sample.bin",
            sample_sha256=uuid.uuid4().hex * 2,
            attempts=0,
        )
        await queue.enqueue(job)
        return job.id

    async def read_status(job_id: uuid.UUID) -> JobStatus:
        # Reaching into the backend is acceptable in a test double; the point
        # is only to observe, and there is nowhere else to observe from.
        return queue._jobs[job_id].status

    return Harness(queue=queue, enqueue_new=enqueue_new, read_status=read_status)


def _database_harness(
    sessionmaker: async_sessionmaker[AsyncSession],
    queue_session: AsyncSession,
) -> Harness:
    queue = DatabaseJobQueue(queue_session)

    async def enqueue_new() -> uuid.UUID:
        # A separate session, because the queue commits its own and a shared
        # one would hide ordering mistakes behind a single transaction.
        async with sessionmaker() as writer:
            digest = uuid.uuid4().hex * 2
            writer.add(
                Sample(sha256=digest, sha1="b" * 40, md5="c" * 32, size_bytes=len(digest))
            )
            job = Job(original_filename="sample.bin", sample_sha256=digest)
            await DatabaseJobQueue(writer).enqueue(job)
            await writer.commit()
            return job.id

    async def read_status(job_id: uuid.UUID) -> JobStatus:
        async with sessionmaker() as reader:
            job = await reader.get(Job, job_id)
            assert job is not None
            return job.status

    return Harness(queue=queue, enqueue_new=enqueue_new, read_status=read_status)


# -- Claiming --------------------------------------------------------------


async def test_an_empty_queue_hands_out_nothing(harness: Harness) -> None:
    assert await harness.queue.claim("worker-1", LEASE_SECONDS) is None


async def test_a_new_job_is_queued(harness: Harness) -> None:
    """AC-13. Nothing has been decided about a job that has just arrived."""
    job_id = await harness.enqueue_new()

    assert await harness.read_status(job_id) is JobStatus.QUEUED


async def test_claiming_takes_ownership(harness: Harness) -> None:
    job_id = await harness.enqueue_new()

    lease = await harness.queue.claim("worker-1", LEASE_SECONDS)

    assert lease is not None
    assert lease.job_id == job_id
    assert lease.worker_id == "worker-1"
    assert lease.attempt == 1
    assert await harness.read_status(job_id) is JobStatus.CLAIMED


async def test_a_claimed_job_is_not_handed_out_again(harness: Harness) -> None:
    """The single most important property in the file."""
    await harness.enqueue_new()

    first = await harness.queue.claim("worker-1", LEASE_SECONDS)
    second = await harness.queue.claim("worker-2", LEASE_SECONDS)

    assert first is not None
    assert second is None


async def test_jobs_are_handed_out_oldest_first(harness: Harness) -> None:
    """Not a fairness nicety: without it a busy queue starves its oldest work."""
    first_id = await harness.enqueue_new()
    second_id = await harness.enqueue_new()

    first = await harness.queue.claim("worker-1", LEASE_SECONDS)
    second = await harness.queue.claim("worker-2", LEASE_SECONDS)

    assert first is not None
    assert second is not None
    assert [first.job_id, second.job_id] == [first_id, second_id]


# -- The run --------------------------------------------------------------


async def test_starting_moves_a_claimed_job_to_running(harness: Harness) -> None:
    job_id = await harness.enqueue_new()
    await harness.queue.claim("worker-1", LEASE_SECONDS)

    await harness.queue.start(job_id, "worker-1")

    assert await harness.read_status(job_id) is JobStatus.RUNNING


async def test_heartbeat_extends_the_lease(harness: Harness) -> None:
    job_id = await harness.enqueue_new()
    first = await harness.queue.claim("worker-1", LEASE_SECONDS)
    assert first is not None

    renewed = await harness.queue.heartbeat(job_id, "worker-1", LEASE_SECONDS * 2)

    assert renewed.expires_at > first.expires_at


async def test_completing_records_the_outcome(harness: Harness) -> None:
    job_id = await harness.enqueue_new()
    await harness.queue.claim("worker-1", LEASE_SECONDS)
    await harness.queue.start(job_id, "worker-1")

    await harness.queue.complete(job_id, "worker-1", RunOutcome.NO_ACTIVITY_OBSERVED)

    assert await harness.read_status(job_id) is JobStatus.FINISHED


async def test_a_job_cannot_finish_without_having_run(harness: Harness) -> None:
    """Claimed is not started, and finishing from there would be a lie."""
    job_id = await harness.enqueue_new()
    await harness.queue.claim("worker-1", LEASE_SECONDS)

    with pytest.raises(IllegalTransitionError):
        await harness.queue.complete(job_id, "worker-1", RunOutcome.COMPLETED)

    assert await harness.read_status(job_id) is JobStatus.CLAIMED


async def test_failing_returns_the_job_to_the_queue(harness: Harness) -> None:
    """The worker failed, not the sample. Somebody else should try."""
    job_id = await harness.enqueue_new()
    await harness.queue.claim("worker-1", LEASE_SECONDS)
    await harness.queue.start(job_id, "worker-1")

    await harness.queue.fail(job_id, "worker-1", "no analysis image available")

    assert await harness.read_status(job_id) is JobStatus.QUEUED
    reclaimed = await harness.queue.claim("worker-2", LEASE_SECONDS)
    assert reclaimed is not None
    assert reclaimed.attempt == 2


# -- Ownership ------------------------------------------------------------


async def test_a_stranger_cannot_complete_someone_elses_job(harness: Harness) -> None:
    """Two workers writing outcomes for one job is the failure to prevent."""
    job_id = await harness.enqueue_new()
    await harness.queue.claim("worker-1", LEASE_SECONDS)
    await harness.queue.start(job_id, "worker-1")

    with pytest.raises(LeaseLostError):
        await harness.queue.complete(job_id, "worker-2", RunOutcome.COMPLETED)

    assert await harness.read_status(job_id) is JobStatus.RUNNING


async def test_a_stranger_cannot_heartbeat(harness: Harness) -> None:
    job_id = await harness.enqueue_new()
    await harness.queue.claim("worker-1", LEASE_SECONDS)

    with pytest.raises(LeaseLostError):
        await harness.queue.heartbeat(job_id, "worker-2", LEASE_SECONDS)


async def test_operations_on_an_unknown_job_are_refused(harness: Harness) -> None:
    with pytest.raises(UnknownJobError):
        await harness.queue.start(uuid.uuid4(), "worker-1")


# -- Expiry ---------------------------------------------------------------


async def test_an_expired_lease_returns_the_job(harness: Harness) -> None:
    """AC-16. A worker that dies cannot report that it died."""
    job_id = await harness.enqueue_new()
    await harness.queue.claim("worker-1", lease_seconds=-1)

    result = await harness.queue.reap_expired(max_attempts=3)

    assert result.requeued == [job_id]
    assert await harness.read_status(job_id) is JobStatus.QUEUED


async def test_a_live_lease_is_left_alone(harness: Harness) -> None:
    await harness.enqueue_new()
    await harness.queue.claim("worker-1", LEASE_SECONDS)

    assert len(await harness.queue.reap_expired(max_attempts=3)) == 0


async def test_the_original_worker_loses_a_reclaimed_job(harness: Harness) -> None:
    """The point of ownership checks: a slow worker must not overwrite a fast one."""
    job_id = await harness.enqueue_new()
    await harness.queue.claim("worker-1", lease_seconds=-1)
    await harness.queue.reap_expired(max_attempts=3)
    await harness.queue.claim("worker-2", LEASE_SECONDS)

    with pytest.raises(LeaseLostError):
        await harness.queue.heartbeat(job_id, "worker-1", LEASE_SECONDS)


async def test_a_job_is_abandoned_once_attempts_run_out(harness: Harness) -> None:
    """Otherwise a job that kills every worker it touches is retried forever."""
    job_id = await harness.enqueue_new()

    for _ in range(2):
        await harness.queue.claim("worker-1", lease_seconds=-1)
        await harness.queue.reap_expired(max_attempts=2)

    assert await harness.read_status(job_id) is JobStatus.CANCELLED


async def test_an_abandoned_job_is_cancelled_rather_than_finished(harness: Harness) -> None:
    """Nothing is known about the sample - a worker died, which says nothing.

    Cancelled, not finished, because finishing would require a run outcome and
    there is no honest one to record.
    """
    job_id = await harness.enqueue_new()
    await harness.queue.claim("worker-1", lease_seconds=-1)

    result = await harness.queue.reap_expired(max_attempts=1)

    assert result.abandoned == [job_id]
    assert await harness.read_status(job_id) is JobStatus.CANCELLED
