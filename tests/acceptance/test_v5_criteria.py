"""AC-08, AC-09, AC-17, AC-18, AC-20, AC-23, AC-24 and AC-25: the v5 criteria.

One test per numbered requirement in ACCEPTANCE.md. Passing this file, together
with every earlier acceptance file, is what makes Stage 1 finished.
"""

from __future__ import annotations

import asyncio
import tracemalloc

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.hashing import hash_bytes
from app.domain.models import Job, Sample
from app.version import APP_VERSION, CONFIG_VERSION, SCHEMA_VERSION
from tests.conftest import TEST_API_KEY
from tests.integration.test_submission_races import GeneratedUpload

pytestmark = pytest.mark.acceptance


async def submit(client: AsyncClient, payload: bytes, name: str = "sample.bin"):  # type: ignore[no-untyped-def]
    return await client.post(
        "/api/v1/submissions",
        files={"file": (name, payload, "application/octet-stream")},
    )


async def test_ac08_an_oversize_upload_is_rejected_and_nothing_is_persisted(
    settings, clean_database: None
) -> None:
    """AC-08. Refused with 413, with no sample, no job and nothing on disk."""
    from app.main import create_app

    capped = settings.model_copy(update={"max_upload_bytes": 1024})
    application = create_app(capped)

    async with application.router.lifespan_context(application):
        transport = ASGITransport(app=application)
        async with AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers={"X-API-Key": TEST_API_KEY},
        ) as client:
            response = await submit(client, b"x" * 8192, "big.bin")

        async with application.state.sessionmaker() as session:
            samples = await session.scalar(select(func.count()).select_from(Sample))
            jobs = await session.scalar(select(func.count()).select_from(Job))

    assert response.status_code == 413
    assert (samples, jobs) == (0, 0)
    assert [p for p in capped.storage_root.rglob("*") if p.is_file()] == []


async def test_ac09_an_empty_file_is_rejected(
    client: AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """AC-09. 422: the request is well-formed, its content is not."""
    response = await submit(client, b"", "empty.bin")

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")

    async with sessionmaker() as session:
        assert await session.scalar(select(func.count()).select_from(Sample)) == 0


async def test_ac17_a_job_response_carries_state_and_provenance(
    client: AsyncClient, sample_bytes: bytes
) -> None:
    """AC-17."""
    job_id = (await submit(client, sample_bytes)).json()["job_id"]

    body = (await client.get(f"/api/v1/jobs/{job_id}")).json()

    assert body["status"] == "queued"
    assert body["run_outcome"] is None
    assert set(body["provenance"]) == {"app_version", "schema_version", "config_version"}


async def test_ac18_provenance_records_app_schema_and_config_versions(
    client: AsyncClient, sample_bytes: bytes
) -> None:
    """AC-18. The versions in force at submission, not the ones running now."""
    job_id = (await submit(client, sample_bytes)).json()["job_id"]

    provenance = (await client.get(f"/api/v1/jobs/{job_id}")).json()["provenance"]

    assert provenance == {
        "app_version": APP_VERSION,
        "schema_version": SCHEMA_VERSION,
        "config_version": CONFIG_VERSION,
    }


async def test_ac20_download_is_attachment_only_octet_stream_and_scope_gated(
    client: AsyncClient, anonymous_client: AsyncClient, sample_bytes: bytes
) -> None:
    """AC-20. Four fences: scope, content type, disposition, and nosniff."""
    digest = (await submit(client, sample_bytes)).json()["sha256"]
    path = f"/api/v1/samples/{digest}/download"

    unauthenticated = await anonymous_client.get(path)
    response = await client.get(path)

    assert unauthenticated.status_code == 401
    assert response.status_code == 200
    assert response.content == sample_bytes
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-disposition"].startswith("attachment")
    assert "inline" not in response.headers["content-disposition"]
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_ac23_health_and_readiness_behave_with_the_database_up_and_down(
    app: FastAPI, anonymous_client: AsyncClient
) -> None:
    """AC-23. Liveness must stay green while readiness fails, not both together."""
    from tests.integration.test_health_readiness import BrokenSessionmaker

    assert (await anonymous_client.get("/healthz")).status_code == 200
    assert (await anonymous_client.get("/readyz")).status_code == 200

    app.state.sessionmaker = BrokenSessionmaker()

    assert (await anonymous_client.get("/healthz")).status_code == 200

    unready = await anonymous_client.get("/readyz")
    assert unready.status_code == 503
    assert unready.json()["database"] == "unavailable"


async def test_ac24_a_large_upload_does_not_scale_memory_with_file_size(
    app: FastAPI, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """AC-24. 64 MB through the intake path, measured away from the HTTP client.

    The client is excluded deliberately: httpx builds an entire multipart body
    in memory, so measuring through it would measure the test harness rather
    than the system under test.
    """
    from app.queue.database import DatabaseJobQueue
    from app.services.intake import IntakeService

    total = 64 * 1024 * 1024

    async with sessionmaker() as session:
        service = IntakeService(
            session=session,
            storage=app.state.storage,
            queue=DatabaseJobQueue(session),
            max_upload_bytes=app.state.settings.max_upload_bytes,
        )

        tracemalloc.start()
        try:
            await service.submit(GeneratedUpload(total))  # type: ignore[arg-type]
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

    assert peak < total // 8, f"peak {peak} bytes for a {total} byte upload"


async def test_ac25_concurrent_identical_submissions_create_one_sample(
    app: FastAPI, sample_bytes: bytes, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """AC-25. Six callers, identical bytes, one row - and nobody refused."""

    async def submit_once() -> int:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"X-API-Key": TEST_API_KEY},
        ) as client:
            return (await submit(client, sample_bytes)).status_code

    statuses = await asyncio.gather(*(submit_once() for _ in range(6)))

    async with sessionmaker() as session:
        samples = await session.scalar(
            select(func.count())
            .select_from(Sample)
            .where(Sample.sha256 == hash_bytes(sample_bytes).sha256)
        )
        jobs = await session.scalar(select(func.count()).select_from(Job))

    assert statuses == [202] * 6
    assert samples == 1
    assert jobs == 6
