"""AC-01 and AC-V1a: a file goes in, a job comes back, and it can be read again.

This is the whole point of the walking skeleton: one request crossing every
layer of the system.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.integration


async def test_submission_is_accepted(client, sample_bytes) -> None:  # type: ignore[no-untyped-def]
    response = await client.post(
        "/api/v1/submissions",
        files={"file": ("suspicious.exe", sample_bytes, "application/octet-stream")},
    )

    assert response.status_code == 202
    body = response.json()
    assert uuid.UUID(body["job_id"])
    assert body["status"] == "queued"


async def test_response_points_at_the_created_job(client, sample_bytes) -> None:  # type: ignore[no-untyped-def]
    response = await client.post(
        "/api/v1/submissions",
        files={"file": ("suspicious.exe", sample_bytes, "application/octet-stream")},
    )

    job_id = response.json()["job_id"]
    assert response.headers["Location"] == f"/api/v1/jobs/{job_id}"


async def test_job_is_retrievable_and_fields_match(client, sample_bytes) -> None:  # type: ignore[no-untyped-def]
    submitted = await client.post(
        "/api/v1/submissions",
        files={"file": ("suspicious.exe", sample_bytes, "application/octet-stream")},
    )
    job_id = submitted.json()["job_id"]

    response = await client.get(f"/api/v1/jobs/{job_id}")

    assert response.status_code == 200
    job = response.json()
    assert job["id"] == job_id
    assert job["original_filename"] == "suspicious.exe"
    assert job["size_bytes"] == len(sample_bytes)
    assert job["status"] == "queued"
    assert job["created_at"]


async def test_bytes_are_stored_under_the_content_hash(client, sample_bytes, settings) -> None:  # type: ignore[no-untyped-def]
    """The submitted filename must never become a path on disk.

    Since v2 the object is named by its SHA-256 rather than by the job id, and
    it is encrypted, so the plaintext must not be readable from the file.
    """
    response = await client.post(
        "/api/v1/submissions",
        files={"file": ("suspicious.exe", sample_bytes, "application/octet-stream")},
    )
    sha256 = response.json()["sha256"]

    stored = [path for path in settings.storage_root.rglob("*") if path.is_file()]
    assert len(stored) == 1
    assert stored[0].name == sha256

    assert stored[0].read_bytes() != sample_bytes
    assert sample_bytes not in stored[0].read_bytes()

    assert not (settings.storage_root / "suspicious.exe").exists()


async def test_unknown_job_returns_404(client) -> None:  # type: ignore[no-untyped-def]
    response = await client.get(f"/api/v1/jobs/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["title"] == "Job Not Found"


async def test_each_submission_creates_a_distinct_job(client, sample_bytes) -> None:  # type: ignore[no-untyped-def]
    """Identical bytes still produce separate jobs in v1.

    Deduplication by content hash is v2's problem, and needs the Sample table.
    """
    first = await client.post(
        "/api/v1/submissions", files={"file": ("a.exe", sample_bytes, "application/octet-stream")}
    )
    second = await client.post(
        "/api/v1/submissions", files={"file": ("a.exe", sample_bytes, "application/octet-stream")}
    )

    assert first.json()["job_id"] != second.json()["job_id"]
