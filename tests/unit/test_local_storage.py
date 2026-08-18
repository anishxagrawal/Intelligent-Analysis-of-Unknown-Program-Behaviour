"""AC-03 at the storage layer: what lands on disk is not the sample.

Behaviour shared with other backends lives in the contract suite. This file
covers only what is specific to the encrypted filesystem backend.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.storage.encryption import ENVELOPE_MAGIC, DecryptionError, generate_key
from app.storage.local import LocalFileSystemStorage

pytestmark = pytest.mark.unit

PLAINTEXT = b"MZ\x90\x00 this must never appear on disk in readable form"
KEY = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


@pytest.fixture
def storage(tmp_path: Path) -> LocalFileSystemStorage:
    return LocalFileSystemStorage(
        root=tmp_path / "samples", keys={"test": generate_key()}, key_id="test"
    )


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "incoming.bin"
    path.write_bytes(PLAINTEXT)
    return path


def _stored_files(storage: LocalFileSystemStorage) -> list[Path]:
    root = Path(storage._root)  # inspecting backend internals is the point of this file
    return [path for path in root.rglob("*") if path.is_file()]


async def test_bytes_on_disk_are_not_the_plaintext(storage, source) -> None:  # type: ignore[no-untyped-def]
    await storage.put(KEY, source)

    files = _stored_files(storage)
    assert len(files) == 1

    on_disk = files[0].read_bytes()
    assert PLAINTEXT not in on_disk
    assert b"must never appear" not in on_disk
    assert on_disk.startswith(ENVELOPE_MAGIC)


async def test_content_is_still_recoverable(storage, source) -> None:  # type: ignore[no-untyped-def]
    await storage.put(KEY, source)

    assert await storage.get(KEY) == PLAINTEXT


async def test_objects_are_fanned_out_into_subdirectories(storage, source) -> None:  # type: ignore[no-untyped-def]
    """One flat directory of a hundred thousand files is miserable to work with."""
    await storage.put(KEY, source)

    stored = _stored_files(storage)[0]
    assert stored.name == KEY
    assert stored.parent.name == KEY[2:4]
    assert stored.parent.parent.name == KEY[:2]


async def test_no_partial_files_remain_after_a_put(storage, source) -> None:  # type: ignore[no-untyped-def]
    """Writes stage to a neighbour and rename in, so a crash cannot leave a
    half-written object that later reads would treat as real."""
    await storage.put(KEY, source)

    assert not [path for path in _stored_files(storage) if path.name.endswith(".partial")]


async def test_a_key_missing_from_the_keyring_cannot_be_read(tmp_path, source) -> None:  # type: ignore[no-untyped-def]
    written = LocalFileSystemStorage(
        root=tmp_path / "samples", keys={"old": generate_key()}, key_id="old"
    )
    await written.put(KEY, source)

    # Same directory, different keyring: the operator rotated and dropped the
    # old key. The data must fail loudly rather than return nonsense.
    rotated = LocalFileSystemStorage(
        root=tmp_path / "samples", keys={"new": generate_key()}, key_id="new"
    )

    with pytest.raises(DecryptionError, match="Unknown key id"):
        await rotated.get(KEY)


def test_active_key_must_be_in_the_keyring(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Catch the misconfiguration at construction, not at the first write."""
    with pytest.raises(ValueError, match="not present in the keyring"):
        LocalFileSystemStorage(
            root=tmp_path / "samples", keys={"a": generate_key()}, key_id="b"
        )
