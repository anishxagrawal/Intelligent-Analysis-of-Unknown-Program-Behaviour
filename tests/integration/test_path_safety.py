"""AC-V1e: a hostile filename cannot escape the storage root.

Cheap to defend against now, and genuinely dangerous if left. The submitted
filename is attacker-controlled text, so it is stored as data and never used to
build a path.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

HOSTILE_NAMES = [
    "../../../evil.txt",
    "..\\..\\..\\evil.txt",
    "/etc/passwd",
    "C:\\Windows\\System32\\evil.dll",
    "....//....//evil.txt",
]


@pytest.mark.parametrize("filename", HOSTILE_NAMES)
async def test_traversal_filename_writes_nothing_outside_storage_root(  # type: ignore[no-untyped-def]
    client, sample_bytes, settings, filename
) -> None:
    """The security property. This is the test AC-V1e refers to."""
    response = await client.post(
        "/api/v1/submissions",
        files={"file": (filename, sample_bytes, "application/octet-stream")},
    )

    assert response.status_code == 202
    job_id = response.json()["job_id"]

    root = settings.storage_root.resolve()
    written = [path for path in root.rglob("*") if path.is_file()]

    # Exactly one file, directly in the root, named by job id.
    assert len(written) == 1
    assert written[0].resolve().parent == root
    assert written[0].name == job_id


# The multipart parser normalises some names before the application sees them.
# Measured against python-multipart as installed: a Windows *absolute* path is
# reduced to its base name, while relative traversal sequences pass through
# untouched. That is third-party behaviour which could change between versions,
# so these expectations record what the stack actually does rather than
# asserting a guarantee this project does not make.
#
# The application itself never alters the name. It stores whatever it is handed,
# because the name is evidence: Stage 2 may care that a sample arrived calling
# itself "C:\\Windows\\System32\\evil.dll".
NAME_AS_STORED = [
    ("../../../evil.txt", "../../../evil.txt"),
    ("..\\..\\..\\evil.txt", "..\\..\\..\\evil.txt"),
    ("/etc/passwd", "/etc/passwd"),
    ("C:\\Windows\\System32\\evil.dll", "evil.dll"),  # normalised by the parser
    ("....//....//evil.txt", "....//....//evil.txt"),
]


@pytest.mark.parametrize(("sent", "stored"), NAME_AS_STORED)
async def test_hostile_filename_is_recorded_as_data(client, sample_bytes, sent, stored) -> None:  # type: ignore[no-untyped-def]
    """The name is kept as a database value, never used to build a path."""
    response = await client.post(
        "/api/v1/submissions",
        files={"file": (sent, sample_bytes, "application/octet-stream")},
    )
    job_id = response.json()["job_id"]

    job = (await client.get(f"/api/v1/jobs/{job_id}")).json()
    assert job["original_filename"] == stored
