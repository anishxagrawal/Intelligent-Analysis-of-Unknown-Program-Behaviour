"""Concurrency: two workers must never receive the same job.

AC-15, and the reason v3 is the hardest version in Stage 1.

This is deliberately not a happy-path assertion. A read-then-write claim - fetch
a queued job, then update it - passes every single-threaded test ever written
and duplicates work the first time two workers ask at once. The only way to have
any confidence is to make them ask at once.

Each worker gets its own session, and therefore its own connection and its own
transaction. Sharing one session would serialise the requests through a single
connection and the test would pass without proving anything at all.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.enums import JobStatus
from app.domain.models import Job, Sample
from app.queue.base import Lease
from app.queue.database import DatabaseJobQueue

pytestmark = pytest.mark.integration

LEASE_SECONDS = 60


async def _add_jobs(sessionmaker: async_sessionmaker[AsyncSession], count: int) -> list[uuid.UUID]:
    """Put ``count`` queued jobs in the database, each with its own sample."""
    job_ids: list[uuid.UUID] = []
    async with sessionmaker() as session:
        for _ in range(count):
            digest = uuid.uuid4().hex * 2
            session.add(Sample(sha256=digest, sha1="b" * 40, md5="c" * 32, size_bytes=8))
            # The id is assigned here rather than left to the column default,
            # which is only applied at flush time.
            job = Job(id=uuid.uuid4(), original_filename="sample.bin", sample_sha256=digest)
            session.add(job)
            job_ids.append(job.id)
        await session.commit()
    return job_ids


async def _claim_once(
    sessionmaker: async_sessionmaker[AsyncSession], worker_id: str
) -> Lease | None:
    async with sessionmaker() as session:
        return await DatabaseJobQueue(session).claim(worker_id, LEASE_SECONDS)


async def test_two_workers_racing_for_one_job(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """AC-15, in its smallest form. One job, two simultaneous claims, one winner."""
    (job_id,) = await _add_jobs(sessionmaker, 1)

    first, second = await asyncio.gather(
        _claim_once(sessionmaker, "worker-1"),
        _claim_once(sessionmaker, "worker-2"),
    )

    claimed = [lease for lease in (first, second) if lease is not None]
    assert len(claimed) == 1
    assert claimed[0].job_id == job_id


async def test_many_workers_never_overlap(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """More workers than jobs, all claiming at once.

    Two assertions, and both matter. Every job is handed out exactly once, and
    the surplus workers get nothing rather than a duplicate.
    """
    job_count, worker_count = 5, 12
    job_ids = await _add_jobs(sessionmaker, job_count)

    leases = await asyncio.gather(
        *(_claim_once(sessionmaker, f"worker-{n}") for n in range(worker_count))
    )

    claimed = [lease.job_id for lease in leases if lease is not None]

    assert len(claimed) == job_count
    assert len(set(claimed)) == job_count, "a job was handed to more than one worker"
    assert set(claimed) == set(job_ids)


async def test_no_job_is_left_in_a_half_claimed_state(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """Every claimed row carries an owner and a lease, or it is not claimed.

    A row marked claimed with no owner is unreachable: no worker can act on it,
    and the reaper skips it because there is no lease to expire.
    """
    await _add_jobs(sessionmaker, 4)

    await asyncio.gather(*(_claim_once(sessionmaker, f"worker-{n}") for n in range(8)))

    async with sessionmaker() as session:
        broken = await session.scalar(
            select(func.count())
            .select_from(Job)
            .where(
                Job.status == JobStatus.CLAIMED,
                (Job.claimed_by.is_(None)) | (Job.lease_expires_at.is_(None)),
            )
        )

    assert broken == 0


async def test_a_second_wave_of_workers_finds_an_empty_queue(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """Claimed work stays claimed; nothing is quietly handed out twice."""
    await _add_jobs(sessionmaker, 3)

    await asyncio.gather(*(_claim_once(sessionmaker, f"first-{n}") for n in range(3)))
    second_wave = await asyncio.gather(
        *(_claim_once(sessionmaker, f"second-{n}") for n in range(3))
    )

    assert all(lease is None for lease in second_wave)
