"""AC-V1a to AC-V1e: the remaining v1 acceptance criteria."""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.acceptance


async def test_ac_v1a_job_is_retrievable_with_matching_fields(client, sample_bytes) -> None:  # type: ignore[no-untyped-def]
    submitted = await client.post(
        "/api/v1/submissions",
        files={"file": ("report.bin", sample_bytes, "application/octet-stream")},
    )
    job_id = submitted.json()["job_id"]

    job = (await client.get(f"/api/v1/jobs/{job_id}")).json()

    assert job["id"] == job_id
    assert job["original_filename"] == "report.bin"
    assert job["size_bytes"] == len(sample_bytes)
    assert job["status"] == "queued"


async def test_ac_v1b_unknown_job_returns_404_as_problem_json(client) -> None:  # type: ignore[no-untyped-def]
    response = await client.get(f"/api/v1/jobs/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_ac_v1c_healthz_returns_200(client) -> None:  # type: ignore[no-untyped-def]
    assert (await client.get("/healthz")).status_code == 200


async def test_ac_v1d_every_response_carries_a_request_id(client, sample_bytes) -> None:  # type: ignore[no-untyped-def]
    health = await client.get("/healthz")
    submission = await client.post(
        "/api/v1/submissions",
        files={"file": ("x.bin", sample_bytes, "application/octet-stream")},
    )
    missing = await client.get(f"/api/v1/jobs/{uuid.uuid4()}")

    for response in (health, submission, missing):
        assert response.headers.get("X-Request-ID")


async def test_ac_v1e_traversal_filename_stays_inside_storage_root(  # type: ignore[no-untyped-def]
    client, sample_bytes, settings
) -> None:
    await client.post(
        "/api/v1/submissions",
        files={"file": ("../../../escaped.txt", sample_bytes, "application/octet-stream")},
    )

    root = settings.storage_root.resolve()
    written = [path for path in root.rglob("*") if path.is_file()]

    assert len(written) == 1
    assert written[0].resolve().parent == root
    assert not (root.parent / "escaped.txt").exists()
