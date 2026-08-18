"""AC-13 to AC-16 and AC-22: the v3 acceptance criteria.

One test per numbered requirement in ACCEPTANCE.md. Passing this file is what
makes v3 finished.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.enums import JobStatus, RunOutcome
from app.domain.lifecycle import IllegalTransitionError
from app.domain.models import Job, Sample
from app.queue.base import JobQueue
from app.queue.database import DatabaseJobQueue
from app.queue.memory import InMemoryJobQueue

pytestmark = pytest.mark.acceptance


async def _add_job(sessionmaker: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with sessionmaker() as session:
        digest = uuid.uuid4().hex * 2
        session.add(Sample(sha256=digest, sha1="b" * 40, md5="c" * 32, size_bytes=8))
        job = Job(id=uuid.uuid4(), original_filename="sample.bin", sample_sha256=digest)
        session.add(job)
        await session.commit()
        return job.id


async def test_ac13_a_new_job_is_queued_and_every_outcome_exists(
    client: AsyncClient, sample_bytes: bytes
) -> None:
    """AC-13. New job is queued; all five run outcomes exist in enum and schema."""
    response = await client.post(
        "/api/v1/submissions",
        files={"file": ("sample.bin", sample_bytes, "application/octet-stream")},
    )
    job = (await client.get(f"/api/v1/jobs/{response.json()['job_id']}")).json()

    assert response.json()["status"] == "queued"
    assert job["status"] == "queued"
    assert job["run_outcome"] is None
    assert job["attempts"] == 0

    # The vocabulary the rest of the project depends on, defined in full before
    # anything can produce it.
    assert [outcome.value for outcome in RunOutcome] == [
        "completed",
        "timed_out",
        "crashed_on_launch",
        "no_activity_observed",
        "evasion_suspected",
    ]

    # And exposed to clients, so a consumer can handle all five from the schema
    # rather than by discovering them one incident at a time.
    schema = (await client.get("/openapi.json")).json()
    assert set(schema["components"]["schemas"]["RunOutcome"]["enum"]) == {
        outcome.value for outcome in RunOutcome
    }


async def test_ac14_an_illegal_transition_raises_and_does_not_persist(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """AC-14. Illegal state transition raises and does not persist."""
    job_id = await _add_job(sessionmaker)
    queue = DatabaseJobQueue(session)
    await queue.claim("worker-1", lease_seconds=60)

    # Claimed is not started. Finishing from here would record a result for a
    # run that never began.
    with pytest.raises(IllegalTransitionError):
        await queue.complete(job_id, "worker-1", RunOutcome.COMPLETED)

    async with sessionmaker() as reader:
        stored = await reader.get(Job, job_id)

    assert stored is not None
    assert stored.status is JobStatus.CLAIMED
    assert stored.run_outcome is None
    assert stored.finished_at is None


async def test_ac15_two_concurrent_workers_cannot_claim_the_same_job(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """AC-15. Two concurrent workers cannot claim the same job.

    Each worker gets its own session, so the two claims genuinely contend. A
    shared session would serialise them and the test would prove nothing.
    """
    job_id = await _add_job(sessionmaker)

    async def claim(worker_id: str) -> uuid.UUID | None:
        async with sessionmaker() as session:
            lease = await DatabaseJobQueue(session).claim(worker_id, lease_seconds=60)
            return lease.job_id if lease else None

    results = await asyncio.gather(claim("worker-1"), claim("worker-2"))

    assert sorted(results, key=lambda value: value is None) == [job_id, None]


async def test_ac16_an_expired_lease_returns_the_job_to_the_queue(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """AC-16. An expired lease returns the job to the queue."""
    job_id = await _add_job(sessionmaker)
    queue = DatabaseJobQueue(session)
    await queue.claim("worker-1", lease_seconds=-1)

    result = await queue.reap_expired(max_attempts=3)

    assert result.requeued == [job_id]

    # Available again, and to somebody else.
    lease = await queue.claim("worker-2", lease_seconds=60)
    assert lease is not None
    assert lease.job_id == job_id
    assert lease.attempt == 2


async def test_ac22_both_backends_satisfy_the_queue_protocol(
    session: AsyncSession,
) -> None:
    """AC-22. Queue contract suite passes against database and in-memory backends.

    The suite itself is tests/contract/test_job_queue.py, which runs every
    assertion against both. What is checked here is that both are actually
    recognised as implementations, so neither can drift out of the suite by
    quietly failing to satisfy the protocol.
    """
    backends = [DatabaseJobQueue(session), InMemoryJobQueue()]

    for backend in backends:
        assert isinstance(backend, JobQueue)

    required = {"enqueue", "claim", "start", "heartbeat", "complete", "fail", "reap_expired"}
    for backend in backends:
        assert required <= set(dir(backend))
