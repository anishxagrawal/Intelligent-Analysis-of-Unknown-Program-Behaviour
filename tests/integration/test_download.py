"""Downloading sample bytes.

Handing back a file that may be live malware is the most dangerous thing this
API does. The headers are not decoration: each one closes a way for a browser to
treat the response as something to act on rather than something to save.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.models import AuditEvent
from app.security import audit as events
from app.security.scopes import Scope
from tests.integration.test_auth import issue_key

pytestmark = pytest.mark.integration


async def submit(client: AsyncClient, payload: bytes, name: str = "sample.bin") -> str:
    response = await client.post(
        "/api/v1/submissions",
        files={"file": (name, payload, "application/octet-stream")},
    )
    assert response.status_code == 202
    digest: str = response.json()["sha256"]
    return digest


async def test_the_stored_bytes_come_back_unchanged(
    client: AsyncClient, sample_bytes: bytes
) -> None:
    """Encryption at rest is invisible to the caller, which is the point."""
    digest = await submit(client, sample_bytes)

    response = await client.get(f"/api/v1/samples/{digest}/download")

    assert response.status_code == 200
    assert response.content == sample_bytes


async def test_the_response_is_octet_stream(client: AsyncClient, sample_bytes: bytes) -> None:
    """Never a type a browser will act on."""
    digest = await submit(client, sample_bytes)

    response = await client.get(f"/api/v1/samples/{digest}/download")

    assert response.headers["content-type"] == "application/octet-stream"


async def test_the_response_is_an_attachment(client: AsyncClient, sample_bytes: bytes) -> None:
    digest = await submit(client, sample_bytes)

    response = await client.get(f"/api/v1/samples/{digest}/download")

    assert response.headers["content-disposition"].startswith("attachment")
    assert "inline" not in response.headers["content-disposition"]


async def test_sniffing_is_refused(client: AsyncClient, sample_bytes: bytes) -> None:
    """So no browser gets to decide the bytes look like something runnable."""
    digest = await submit(client, sample_bytes)

    response = await client.get(f"/api/v1/samples/{digest}/download")

    assert response.headers["x-content-type-options"] == "nosniff"


async def test_the_filename_is_the_digest_not_the_submitted_name(
    client: AsyncClient, sample_bytes: bytes
) -> None:
    """The submitted name is attacker-controlled and could be chosen to mislead."""
    digest = await submit(client, sample_bytes, name="totally-safe-invoice.pdf")

    response = await client.get(f"/api/v1/samples/{digest}/download")

    disposition = response.headers["content-disposition"]
    assert digest in disposition
    assert "invoice" not in disposition


async def test_downloading_needs_its_own_scope(
    anonymous_client: AsyncClient,
    client: AsyncClient,
    sample_bytes: bytes,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """Reading that a job finished must not imply permission to pull the bytes."""
    digest = await submit(client, sample_bytes)
    reader = await issue_key(sessionmaker, Scope.JOBS_READ)

    metadata = await anonymous_client.get(
        f"/api/v1/samples/{digest}", headers={"X-API-Key": reader}
    )
    download = await anonymous_client.get(
        f"/api/v1/samples/{digest}/download", headers={"X-API-Key": reader}
    )

    assert metadata.status_code == 200
    assert download.status_code == 403


async def test_downloading_without_a_key_is_refused(anonymous_client: AsyncClient) -> None:
    response = await anonymous_client.get("/api/v1/samples/" + "a" * 64 + "/download")

    assert response.status_code == 401


async def test_an_unknown_digest_is_a_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/samples/" + "a" * 64 + "/download")

    assert response.status_code == 404


async def test_every_download_is_audited(
    client: AsyncClient, sample_bytes: bytes, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """Who pulled which sample, and when, is exactly what an incident asks."""
    digest = await submit(client, sample_bytes)

    await client.get(f"/api/v1/samples/{digest}/download")

    async with sessionmaker() as session:
        entry = await session.scalar(
            select(AuditEvent).where(AuditEvent.event == events.SAMPLE_DOWNLOADED)
        )

    assert entry is not None
    assert digest in (entry.detail or "")
    assert entry.api_key_id is not None


async def test_a_missing_stored_object_is_reported_as_our_failure(
    client: AsyncClient, sample_bytes: bytes, settings
) -> None:
    """Row and store disagreeing is an operational problem, not a client mistake."""
    digest = await submit(client, sample_bytes)
    for path in settings.storage_root.rglob("*"):
        if path.is_file():
            path.unlink()

    response = await client.get(f"/api/v1/samples/{digest}/download")

    assert response.status_code == 500
    assert response.json()["title"] == "Sample Bytes Missing"
