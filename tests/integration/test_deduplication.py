"""AC-02 and AC-05: content addressing and deduplication.

The same bytes submitted twice must produce two jobs but one stored sample.
Malware arrives in waves of near-identical submissions; storing every copy is
wasteful, and losing the fact that it was seen before is worse.
"""

from __future__ import annotations

import pytest

from app.domain.hashing import hash_bytes

pytestmark = pytest.mark.integration


async def _submit(client, payload: bytes, filename: str = "a.bin"):  # type: ignore[no-untyped-def]
    return await client.post(
        "/api/v1/submissions",
        files={"file": (filename, payload, "application/octet-stream")},
    )


async def test_response_reports_the_content_hash(client, sample_bytes) -> None:  # type: ignore[no-untyped-def]
    response = await _submit(client, sample_bytes)

    assert response.json()["sha256"] == hash_bytes(sample_bytes).sha256


async def test_first_submission_is_not_a_duplicate(client, sample_bytes) -> None:  # type: ignore[no-untyped-def]
    assert (await _submit(client, sample_bytes)).json()["duplicate"] is False


async def test_second_submission_of_same_bytes_is_flagged(client, sample_bytes) -> None:  # type: ignore[no-untyped-def]
    await _submit(client, sample_bytes)

    assert (await _submit(client, sample_bytes)).json()["duplicate"] is True


async def test_duplicate_still_creates_a_new_job(client, sample_bytes) -> None:  # type: ignore[no-untyped-def]
    """A repeat submission is a new request for analysis, not a no-op."""
    first = await _submit(client, sample_bytes)
    second = await _submit(client, sample_bytes)

    assert first.json()["job_id"] != second.json()["job_id"]
    assert first.json()["sha256"] == second.json()["sha256"]


async def test_different_filenames_share_one_sample(client, sample_bytes) -> None:  # type: ignore[no-untyped-def]
    """Identity is the content. The name is metadata that travels on the job."""
    first = await _submit(client, sample_bytes, filename="invoice.exe")
    second = await _submit(client, sample_bytes, filename="totally-safe.exe")

    assert first.json()["sha256"] == second.json()["sha256"]

    first_job = (await client.get(f"/api/v1/jobs/{first.json()['job_id']}")).json()
    second_job = (await client.get(f"/api/v1/jobs/{second.json()['job_id']}")).json()

    assert first_job["original_filename"] == "invoice.exe"
    assert second_job["original_filename"] == "totally-safe.exe"


async def test_different_content_produces_different_samples(client) -> None:  # type: ignore[no-untyped-def]
    first = await _submit(client, b"one payload")
    second = await _submit(client, b"another payload")

    assert first.json()["sha256"] != second.json()["sha256"]
    assert second.json()["duplicate"] is False


async def test_only_one_object_is_stored_for_repeated_bytes(  # type: ignore[no-untyped-def]
    client, sample_bytes, settings
) -> None:
    await _submit(client, sample_bytes)
    await _submit(client, sample_bytes)
    await _submit(client, sample_bytes)

    stored = [p for p in settings.storage_root.rglob("*") if p.is_file()]
    assert len(stored) == 1


async def test_job_exposes_the_sample_digests(client, sample_bytes) -> None:  # type: ignore[no-untyped-def]
    expected = hash_bytes(sample_bytes)
    submitted = await _submit(client, sample_bytes)

    job = (await client.get(f"/api/v1/jobs/{submitted.json()['job_id']}")).json()

    assert job["sha256"] == expected.sha256
    assert job["sha1"] == expected.sha1
    assert job["md5"] == expected.md5
    assert job["size_bytes"] == expected.size_bytes


async def test_sample_can_be_fetched_by_hash(client, sample_bytes) -> None:  # type: ignore[no-untyped-def]
    expected = hash_bytes(sample_bytes)
    await _submit(client, sample_bytes)

    response = await client.get(f"/api/v1/samples/{expected.sha256}")

    assert response.status_code == 200
    body = response.json()
    assert body["sha256"] == expected.sha256
    assert body["size_bytes"] == expected.size_bytes
    assert body["submission_count"] == 1


async def test_submission_count_grows_with_each_submission(client, sample_bytes) -> None:  # type: ignore[no-untyped-def]
    expected = hash_bytes(sample_bytes)
    await _submit(client, sample_bytes)
    await _submit(client, sample_bytes)

    body = (await client.get(f"/api/v1/samples/{expected.sha256}")).json()

    assert body["submission_count"] == 2


async def test_unknown_sample_returns_404(client) -> None:  # type: ignore[no-untyped-def]
    response = await client.get(f"/api/v1/samples/{'0' * 64}")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
