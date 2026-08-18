"""AC-01: a valid submission returns 202 with a job id.

The acceptance suite is the definition of a version being finished. Each test
here maps to exactly one numbered criterion in ACCEPTANCE.md.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.acceptance


async def test_ac01_valid_submission_returns_202_with_a_job_id(client, sample_bytes) -> None:  # type: ignore[no-untyped-def]
    response = await client.post(
        "/api/v1/submissions",
        files={"file": ("sample.bin", sample_bytes, "application/octet-stream")},
    )

    assert response.status_code == 202

    job_id = response.json()["job_id"]
    assert uuid.UUID(job_id), "job_id must be a valid UUID"
