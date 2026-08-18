"""AC-21: every SampleStorage implementation behaves identically.

This suite is what makes the storage boundary real rather than aspirational.
Any future backend - S3, MinIO, a network share - has to pass exactly these
tests before it can be swapped in.

Every test here is expressed only in terms of the protocol. Nothing knows
whether bytes end up on disk, in a dictionary, or encrypted. Properties specific
to one backend belong in that backend's own test file.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from app.storage.base import SampleNotFoundError, SampleStorage
from app.storage.encryption import generate_key
from app.storage.local import LocalFileSystemStorage
from app.storage.memory import InMemoryStorage

pytestmark = pytest.mark.contract

#: Every implementation the contract covers. A new backend must be added
#: here, which is what AC-21 in the acceptance suite verifies.
STORAGE_BACKENDS = ("local", "memory")

PAYLOAD = b"MZ\x90\x00 sample content for the storage contract"
KEY = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


@pytest.fixture(params=STORAGE_BACKENDS)
def storage(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[SampleStorage]:
    """Yield each implementation in turn, so every test runs against all of them."""
    if request.param == "local":
        key = generate_key()
        yield LocalFileSystemStorage(root=tmp_path / "samples", keys={"test": key}, key_id="test")
    else:
        yield InMemoryStorage()


@pytest.fixture
def source_file(tmp_path: Path) -> Path:
    path = tmp_path / "incoming.bin"
    path.write_bytes(PAYLOAD)
    return path


async def test_stored_content_is_returned_unchanged(storage, source_file) -> None:  # type: ignore[no-untyped-def]
    await storage.put(KEY, source_file)

    assert await storage.get(KEY) == PAYLOAD


async def test_exists_is_false_before_and_true_after(storage, source_file) -> None:  # type: ignore[no-untyped-def]
    assert await storage.exists(KEY) is False

    await storage.put(KEY, source_file)

    assert await storage.exists(KEY) is True


async def test_getting_an_absent_key_raises(storage) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(SampleNotFoundError):
        await storage.get("0" * 64)


async def test_delete_removes_the_object(storage, source_file) -> None:  # type: ignore[no-untyped-def]
    await storage.put(KEY, source_file)

    await storage.delete(KEY)

    assert await storage.exists(KEY) is False


async def test_delete_is_idempotent(storage) -> None:  # type: ignore[no-untyped-def]
    """Deleting something already gone is not an error.

    Cleanup paths run when things have already gone wrong; they must not fail
    and mask the original problem.
    """
    await storage.delete("0" * 64)
    await storage.delete("0" * 64)


async def test_putting_the_same_key_twice_is_allowed(storage, source_file) -> None:  # type: ignore[no-untyped-def]
    """Content-addressed keys mean a repeat put is the same bytes.

    It happens whenever a duplicate submission races, so it must be harmless.
    """
    await storage.put(KEY, source_file)
    await storage.put(KEY, source_file)

    assert await storage.get(KEY) == PAYLOAD


async def test_distinct_keys_hold_distinct_content(storage, tmp_path) -> None:  # type: ignore[no-untyped-def]
    first = tmp_path / "one.bin"
    second = tmp_path / "two.bin"
    first.write_bytes(b"first content")
    second.write_bytes(b"second content")

    await storage.put("a" * 64, first)
    await storage.put("b" * 64, second)

    assert await storage.get("a" * 64) == b"first content"
    assert await storage.get("b" * 64) == b"second content"


async def test_empty_content_round_trips(storage, tmp_path) -> None:  # type: ignore[no-untyped-def]
    empty = tmp_path / "empty.bin"
    empty.write_bytes(b"")

    await storage.put(KEY, empty)

    assert await storage.get(KEY) == b""


async def test_large_content_round_trips(storage, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Comfortably larger than one read buffer, to catch chunking mistakes."""
    payload = bytes(range(256)) * 5000  # ~1.2 MB
    big = tmp_path / "big.bin"
    big.write_bytes(payload)

    await storage.put(KEY, big)

    assert await storage.get(KEY) == payload


async def test_size_of_reports_stored_length(storage, source_file) -> None:  # type: ignore[no-untyped-def]
    await storage.put(KEY, source_file)

    assert await storage.size_of(KEY) == len(PAYLOAD)
