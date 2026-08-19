"""Two ways a submission can go wrong under pressure.

Both are cases that a single request, tested one at a time, will never reveal:
identical bytes arriving simultaneously, and a file too large to hold in memory.
"""

from __future__ import annotations

import asyncio
import tracemalloc

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.models import Job, Sample
from tests.conftest import TEST_API_KEY

pytestmark = pytest.mark.integration


def client_for(app: FastAPI) -> AsyncClient:
    """A fresh authenticated client. Each concurrent caller needs its own."""
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"X-API-Key": TEST_API_KEY},
    )


async def submit_once(app: FastAPI, payload: bytes) -> int:
    async with client_for(app) as client:
        response = await client.post(
            "/api/v1/submissions",
            files={"file": ("sample.bin", payload, "application/octet-stream")},
        )
        return response.status_code


# -- Concurrent identical submissions --------------------------------------


async def test_simultaneous_identical_submissions_all_succeed(
    app: FastAPI, sample_bytes: bytes
) -> None:
    """AC-25. Losing the primary-key race must not refuse a legitimate caller."""
    statuses = await asyncio.gather(*(submit_once(app, sample_bytes) for _ in range(6)))

    assert statuses == [202] * 6


async def test_simultaneous_identical_submissions_create_one_sample(
    app: FastAPI, sample_bytes: bytes, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """AC-25. One row for one set of bytes, however many callers arrive at once."""
    await asyncio.gather(*(submit_once(app, sample_bytes) for _ in range(6)))

    async with sessionmaker() as session:
        samples = await session.scalar(select(func.count()).select_from(Sample))

    assert samples == 1


async def test_simultaneous_identical_submissions_create_separate_jobs(
    app: FastAPI, sample_bytes: bytes, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """Deduplication is about storage. Each submission is still its own request."""
    await asyncio.gather(*(submit_once(app, sample_bytes) for _ in range(6)))

    async with sessionmaker() as session:
        jobs = await session.scalar(select(func.count()).select_from(Job))

    assert jobs == 6


async def test_only_one_object_is_stored(app: FastAPI, sample_bytes: bytes, settings) -> None:
    """Content addressing means the repeated writes land on the same key."""
    await asyncio.gather(*(submit_once(app, sample_bytes) for _ in range(6)))

    stored = [path for path in settings.storage_root.rglob("*") if path.is_file()]

    assert len(stored) == 1


# -- Memory ---------------------------------------------------------------


class GeneratedUpload:
    """An upload that produces its bytes rather than holding them.

    Measuring through the HTTP client would measure the client: httpx builds the
    whole multipart body in memory before sending it, so the test harness alone
    accounts for more than the payload. Driving the intake service directly is
    what isolates the claim being made - that *this system* does not scale
    memory with the size of the file.

    Only ``read`` and ``filename`` are used by IntakeService, which is the whole
    interface this stands in for.
    """

    def __init__(self, total_bytes: int, filename: str = "large.bin") -> None:
        self.filename = filename
        self._remaining = total_bytes

    async def read(self, size: int = -1) -> bytes:
        if self._remaining <= 0:
            return b""
        count = self._remaining if size < 0 else min(size, self._remaining)
        self._remaining -= count
        return b"\x7f" * count


async def test_memory_does_not_scale_with_upload_size(
    app: FastAPI, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """AC-24. Streaming, not buffering, from the socket to the sealed object.

    64 MB through a system whose upload cap is 100 MB. Peak allocation is
    expected to stay in the low megabytes - the copy buffer, the encryption
    chunk - rather than anywhere near the size of the file.

    The threshold is a generous fraction of the payload rather than a fixed
    number of bytes: what is being tested is that memory does not track the
    file, not that it hits any particular figure on any particular machine.
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


async def test_a_large_upload_still_round_trips(app: FastAPI) -> None:
    """Streaming is worth nothing if it mangles the file on the way through."""
    payload = bytes(range(256)) * 8192

    async with client_for(app) as client:
        submitted = await client.post(
            "/api/v1/submissions",
            files={"file": ("large.bin", payload, "application/octet-stream")},
        )
        digest = submitted.json()["sha256"]
        downloaded = await client.get(f"/api/v1/samples/{digest}/download")

    assert downloaded.content == payload
