"""The stub worker against a real database.

Two things are being checked. The obvious one is that claim and start work from
outside the API. The less obvious one - and the reason several of these tests
exist - is that the worker refuses to invent a result. A stub that quietly
recorded ``completed`` would make every test downstream of it green and every
one of them meaningless.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.enums import JobStatus
from app.domain.models import Job, Sample
from app.queue.database import DatabaseJobQueue
from app.queue.reaper import Reaper
from worker.runner import StubWorker, default_worker_id

pytestmark = pytest.mark.integration


async def _add_job(sessionmaker: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with sessionmaker() as session:
        digest = uuid.uuid4().hex * 2
        session.add(Sample(sha256=digest, sha1="b" * 40, md5="c" * 32, size_bytes=8))
        job = Job(id=uuid.uuid4(), original_filename="sample.bin", sample_sha256=digest)
        session.add(job)
        await session.commit()
        return job.id


async def _read(sessionmaker: async_sessionmaker[AsyncSession], job_id: uuid.UUID) -> Job:
    async with sessionmaker() as session:
        job = await session.get(Job, job_id)
        assert job is not None
        return job


def test_worker_ids_identify_a_process() -> None:
    """A stuck lease should point at a machine, not at an opaque token."""
    first, second = default_worker_id(), default_worker_id()

    assert first != second
    assert str(os.getpid()) in first


async def test_an_empty_queue_yields_nothing(
    session: AsyncSession,
) -> None:
    worker = StubWorker(DatabaseJobQueue(session))

    assert await worker.process_one() is None


async def test_the_worker_claims_and_starts(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    job_id = await _add_job(sessionmaker)
    worker = StubWorker(DatabaseJobQueue(session), worker_id="worker-1")

    lease = await worker.process_one()

    assert lease is not None
    assert lease.job_id == job_id

    job = await _read(sessionmaker, job_id)
    assert job.status is JobStatus.RUNNING
    assert job.claimed_by == "worker-1"
    assert job.started_at is not None


async def test_the_worker_records_no_outcome(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """Nothing was run, so there is nothing honest to record. Stage 2's job."""
    job_id = await _add_job(sessionmaker)
    await StubWorker(DatabaseJobQueue(session), worker_id="worker-1").process_one()

    job = await _read(sessionmaker, job_id)

    assert job.run_outcome is None
    assert job.finished_at is None


async def test_work_nobody_finishes_comes_back(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """The handoff is safe because it is leased, not given away.

    The worker leaves the job running and waits for a Stage 2 that does not
    exist. The lease lapses, the reaper takes the job back, and nothing is lost
    - which is the correct treatment of work that was accepted and never done.
    """
    job_id = await _add_job(sessionmaker)
    worker = StubWorker(DatabaseJobQueue(session), worker_id="worker-1", lease_seconds=-1)
    await worker.process_one()

    result = await Reaper(queue=DatabaseJobQueue(session), max_attempts=3).sweep_once()

    assert result.requeued == [job_id]
    assert (await _read(sessionmaker, job_id)).status is JobStatus.QUEUED


async def test_a_job_that_exhausts_its_attempts_is_cancelled(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """And is cancelled, not finished, because no run outcome would be true."""
    job_id = await _add_job(sessionmaker)
    queue = DatabaseJobQueue(session)
    worker = StubWorker(queue, worker_id="worker-1", lease_seconds=-1)
    reaper = Reaper(queue=queue, max_attempts=2)

    for _ in range(2):
        await worker.process_one()
        await reaper.sweep_once()

    job = await _read(sessionmaker, job_id)
    assert job.status is JobStatus.CANCELLED
    assert job.run_outcome is None
    assert "abandoned" in (job.failure_reason or "")
