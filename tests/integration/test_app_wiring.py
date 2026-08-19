"""What the application actually starts, and what it shuts down.

The reaper is the interesting one. It was written in v3 and left unwired, which
meant abandoned jobs were recoverable in principle and recovered by nobody. A
recovery mechanism that has to be started separately is one that eventually is
not started at all.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain.enums import JobStatus
from app.domain.models import Job, Sample
from app.main import create_app
from app.security.provisioning import create_api_key
from app.security.scopes import Scope

pytestmark = pytest.mark.integration


async def add_claimed_job_with_a_dead_lease(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> uuid.UUID:
    """A job held by a worker that will never report back."""
    from app.queue.database import DatabaseJobQueue

    async with sessionmaker() as session:
        digest = uuid.uuid4().hex * 2
        session.add(Sample(sha256=digest, sha1="b" * 40, md5="c" * 32, size_bytes=8))
        job = Job(id=uuid.uuid4(), original_filename="sample.bin", sample_sha256=digest)
        session.add(job)
        await session.commit()

    async with sessionmaker() as session:
        await DatabaseJobQueue(session).claim("worker-gone", lease_seconds=-1)

    return job.id


async def test_the_reaper_runs_alongside_the_api(app: FastAPI) -> None:
    assert app.state.reaper_task is not None
    assert not app.state.reaper_task.done()


async def test_a_running_reaper_recovers_abandoned_work(
    settings: Settings, clean_database: None
) -> None:
    """End to end: nothing but starting the application brings the job back."""
    from app.db.session import create_engine, create_sessionmaker

    fast = settings.model_copy(update={"reaper_interval_seconds": 0.05})
    application = create_app(fast)

    async with application.router.lifespan_context(application):
        sessionmaker = application.state.sessionmaker
        job_id = await add_claimed_job_with_a_dead_lease(sessionmaker)

        for _ in range(40):
            await asyncio.sleep(0.05)
            async with sessionmaker() as session:
                job = await session.get(Job, job_id)
                assert job is not None
                if job.status is JobStatus.QUEUED:
                    break
        else:  # pragma: no cover - only reached if the reaper never ran
            pytest.fail("the reaper did not requeue the abandoned job")

    engine = create_engine(fast)
    try:
        async with create_sessionmaker(engine)() as session:
            recovered = await session.get(Job, job_id)
    finally:
        await engine.dispose()

    assert recovered is not None
    assert recovered.status is JobStatus.QUEUED


async def test_the_reaper_can_be_turned_off(settings: Settings, clean_database: None) -> None:
    """A deployment running it elsewhere should be able to say so."""
    application = create_app(settings.model_copy(update={"run_reaper": False}))

    async with application.router.lifespan_context(application):
        assert application.state.reaper_task is None


async def test_shutdown_stops_the_reaper(settings: Settings, clean_database: None) -> None:
    """A task left running past shutdown can still hold a connection."""
    application = create_app(settings)

    async with application.router.lifespan_context(application):
        task = application.state.reaper_task

    assert task.done()


async def test_the_bootstrap_key_is_not_duplicated_on_restart(
    settings: Settings, clean_database: None
) -> None:
    """Restarting is normal; a key row per restart is not."""
    from sqlalchemy import func, select

    from app.domain.models import ApiKey

    for _ in range(3):
        application = create_app(settings)
        async with application.router.lifespan_context(application):
            pass

    application = create_app(settings)
    async with (
        application.router.lifespan_context(application),
        application.state.sessionmaker() as session,
    ):
        keys = await session.scalar(select(func.count()).select_from(ApiKey))

    assert keys == 1


async def test_a_created_key_authenticates(
    app: FastAPI, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """The path scripts/create-api-key.py takes, without the argument parsing."""
    from httpx import ASGITransport, AsyncClient

    async with sessionmaker() as session:
        token = await create_api_key(session, "ingest", [Scope.SUBMISSIONS_WRITE])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/v1/submissions",
            files={"file": ("sample.bin", b"MZ bytes", "application/octet-stream")},
            headers={"X-API-Key": token},
        )

    assert response.status_code == 202


async def test_a_created_key_is_returned_once_and_stored_hashed(
    session: AsyncSession,
) -> None:
    from sqlalchemy import select

    from app.domain.models import ApiKey

    token = await create_api_key(session, "ingest", [Scope.JOBS_READ])

    stored = await session.scalar(select(ApiKey).where(ApiKey.name == "ingest"))

    assert stored is not None
    assert stored.token_hash != token
    assert token not in stored.token_hash
