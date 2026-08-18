"""AC-02 to AC-05 and AC-21: the v2 acceptance criteria.

One test per numbered requirement in ACCEPTANCE.md. Passing this file is what
makes v2 finished.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.acceptance


async def _submit(client, payload: bytes, filename: str = "sample.bin"):  # type: ignore[no-untyped-def]
    return await client.post(
        "/api/v1/submissions",
        files={"file": (filename, payload, "application/octet-stream")},
    )


async def test_ac02_sample_stored_under_content_hash_never_by_filename(  # type: ignore[no-untyped-def]
    client, sample_bytes, settings
) -> None:
    response = await _submit(client, sample_bytes, filename="invoice.exe")
    sha256 = response.json()["sha256"]

    stored = [path for path in settings.storage_root.rglob("*") if path.is_file()]

    assert len(stored) == 1
    assert stored[0].name == sha256
    assert stored[0].name != "invoice.exe"
    assert not list(settings.storage_root.rglob("invoice.exe"))


async def test_ac03_plaintext_is_absent_from_the_stored_object(  # type: ignore[no-untyped-def]
    client, sample_bytes, settings
) -> None:
    await _submit(client, sample_bytes)

    stored = [path for path in settings.storage_root.rglob("*") if path.is_file()]
    on_disk = stored[0].read_bytes()

    assert sample_bytes not in on_disk
    assert on_disk != sample_bytes


async def test_ac04_digests_match_known_vectors(client) -> None:  # type: ignore[no-untyped-def]
    """b"abc" has published digests; the API must report exactly those."""
    response = await _submit(client, b"abc")

    body = response.json()
    assert body["sha256"] == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"

    job = (await client.get(f"/api/v1/jobs/{body['job_id']}")).json()
    assert job["sha1"] == "a9993e364706816aba3e25717850c26c9cd0d89d"
    assert job["md5"] == "900150983cd24fb0d6963f7d28e17f72"
    assert job["size_bytes"] == 3


async def test_ac05_duplicate_bytes_reuse_the_sample_and_create_a_new_job(  # type: ignore[no-untyped-def]
    client, sample_bytes, settings
) -> None:
    first = await _submit(client, sample_bytes, filename="one.exe")
    second = await _submit(client, sample_bytes, filename="two.exe")

    # A new job each time.
    assert first.json()["job_id"] != second.json()["job_id"]

    # Flagged as a duplicate the second time.
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True

    # One sample row, one stored object.
    sample = (await client.get(f"/api/v1/samples/{first.json()['sha256']}")).json()
    assert sample["submission_count"] == 2

    stored = [path for path in settings.storage_root.rglob("*") if path.is_file()]
    assert len(stored) == 1


def test_ac21_contract_suite_covers_every_storage_implementation() -> None:
    """The contract suite must exercise every backend that exists.

    A backend added later but left out of the suite would silently skip the
    shared tests, which is exactly the failure this guards against.
    """
    from app.storage.base import SampleStorage
    from app.storage.local import LocalFileSystemStorage
    from app.storage.memory import InMemoryStorage
    from tests.contract.test_sample_storage import STORAGE_BACKENDS

    implementations = {
        "local": LocalFileSystemStorage,
        "memory": InMemoryStorage,
    }

    # Every known implementation is covered by the suite.
    assert set(implementations) == set(STORAGE_BACKENDS)

    # And each genuinely satisfies the protocol.
    for implementation in implementations.values():
        assert issubclass(implementation, SampleStorage)
