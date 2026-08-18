"""The reaper's policy, tested against the in-memory queue.

Expiry detection belongs to the backend and is covered by the contract suite.
What is tested here is the layer above it: sweeping, surviving failures, and
stopping when told to.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from app.domain.enums import JobStatus
from app.domain.models import Job
from app.queue.base import JobQueue, ReapResult
from app.queue.memory import InMemoryJobQueue
from app.queue.reaper import Reaper

pytestmark = pytest.mark.unit


async def _queue_with_one_job() -> tuple[InMemoryJobQueue, uuid.UUID]:
    queue = InMemoryJobQueue()
    job = Job(id=uuid.uuid4(), original_filename="sample.bin", sample_sha256="a" * 64)
    await queue.enqueue(job)
    return queue, job.id


class ExplodingQueue:
    """A queue whose sweep always fails, to prove the loop survives it."""

    def __init__(self) -> None:
        self.calls = 0

    async def reap_expired(self, max_attempts: int) -> ReapResult:
        self.calls += 1
        raise RuntimeError("database unreachable")


def test_a_reaper_needs_exactly_one_source_of_queues() -> None:
    """Both, or neither, is a wiring mistake worth failing loudly on."""
    with pytest.raises(ValueError, match="exactly one"):
        Reaper()

    with pytest.raises(ValueError, match="exactly one"):
        Reaper(queue_factory=_never_called, queue=InMemoryJobQueue())


async def test_a_sweep_requeues_expired_work() -> None:
    queue, job_id = await _queue_with_one_job()
    await queue.claim("worker-1", lease_seconds=-1)

    result = await Reaper(queue=queue, max_attempts=3).sweep_once()

    assert result.requeued == [job_id]


async def test_a_sweep_over_healthy_work_does_nothing() -> None:
    queue, _ = await _queue_with_one_job()
    await queue.claim("worker-1", lease_seconds=60)

    assert len(await Reaper(queue=queue, max_attempts=3).sweep_once()) == 0


async def test_a_factory_is_called_for_each_sweep() -> None:
    """A long-lived reaper wants a fresh session every pass, not one held open."""
    queue, _ = await _queue_with_one_job()
    calls = 0

    async def factory() -> JobQueue:
        nonlocal calls
        calls += 1
        return queue

    reaper = Reaper(factory, max_attempts=3)
    await reaper.sweep_once()
    await reaper.sweep_once()

    assert calls == 2


async def test_the_loop_survives_a_failing_sweep() -> None:
    """A database blip must not silently stop the only thing recovering lost jobs."""
    queue = ExplodingQueue()
    reaper = Reaper(queue=queue, max_attempts=3, interval_seconds=0.01)

    task = asyncio.create_task(reaper.run_forever())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert queue.calls > 1


async def test_the_loop_recovers_jobs_until_cancelled() -> None:
    queue, job_id = await _queue_with_one_job()
    await queue.claim("worker-1", lease_seconds=-1)

    reaper = Reaper(queue=queue, max_attempts=3, interval_seconds=0.01)
    task = asyncio.create_task(reaper.run_forever())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert queue._jobs[job_id].status is JobStatus.QUEUED


async def _never_called() -> JobQueue:  # pragma: no cover - argument checking only
    raise AssertionError("the factory should not be used")
