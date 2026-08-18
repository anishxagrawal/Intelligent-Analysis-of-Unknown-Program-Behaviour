"""The size cap, enforced while streaming rather than afterwards.

Checking after the upload has been read would let a caller make the service
consume unbounded disk before the request is refused. VERSIONS.md names this as
v2's main risk, so it is tested here even though the formal criterion (AC-08)
belongs to v5.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def small_limit_settings(settings):  # type: ignore[no-untyped-def]
    """A deliberately tiny limit, so the test does not need a huge payload."""
    return settings.model_copy(update={"max_upload_bytes": 1024})


@pytest.fixture
async def small_limit_client(small_limit_settings):  # type: ignore[no-untyped-def]
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    application = create_app(small_limit_settings)
    async with application.router.lifespan_context(application):
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


async def test_upload_within_the_limit_is_accepted(small_limit_client) -> None:  # type: ignore[no-untyped-def]
    response = await small_limit_client.post(
        "/api/v1/submissions",
        files={"file": ("ok.bin", b"x" * 512, "application/octet-stream")},
    )

    assert response.status_code == 202


async def test_oversize_upload_is_rejected(small_limit_client) -> None:  # type: ignore[no-untyped-def]
    response = await small_limit_client.post(
        "/api/v1/submissions",
        files={"file": ("big.bin", b"x" * 4096, "application/octet-stream")},
    )

    assert response.status_code == 413
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["title"] == "Payload Too Large"


async def test_rejected_upload_stores_nothing(  # type: ignore[no-untyped-def]
    small_limit_client, small_limit_settings
) -> None:
    """Nothing persisted, and no staging file left behind."""
    await small_limit_client.post(
        "/api/v1/submissions",
        files={"file": ("big.bin", b"x" * 4096, "application/octet-stream")},
    )

    stored = [p for p in small_limit_settings.storage_root.rglob("*") if p.is_file()]
    assert stored == []


async def test_rejected_upload_creates_no_job_or_sample(small_limit_client) -> None:  # type: ignore[no-untyped-def]
    from app.domain.hashing import hash_bytes

    payload = b"x" * 4096
    await small_limit_client.post(
        "/api/v1/submissions",
        files={"file": ("big.bin", payload, "application/octet-stream")},
    )

    lookup = await small_limit_client.get(f"/api/v1/samples/{hash_bytes(payload).sha256}")
    assert lookup.status_code == 404


async def test_limit_is_enforced_before_the_whole_upload_is_buffered(  # type: ignore[no-untyped-def]
    small_limit_client, small_limit_settings
) -> None:
    """A payload far larger than the limit must still be refused, and must not
    leave the oversized bytes anywhere on disk."""
    response = await small_limit_client.post(
        "/api/v1/submissions",
        files={"file": ("huge.bin", b"x" * (1024 * 1024), "application/octet-stream")},
    )

    assert response.status_code == 413
    assert [p for p in small_limit_settings.storage_root.rglob("*") if p.is_file()] == []
