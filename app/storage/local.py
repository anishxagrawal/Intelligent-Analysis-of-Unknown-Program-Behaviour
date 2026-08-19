"""Encrypted local filesystem storage.

Objects are sealed with AES-256-GCM before they touch the disk, so the stored
file never contains the sample in usable form.

Files are fanned out into two levels of subdirectory taken from the key
(``ab/cd/abcd...``). A single directory holding a hundred thousand entries is
slow to list on most filesystems and unpleasant to work with by hand; this keeps
directories small at no cost.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Mapping
from pathlib import Path

from app.storage.base import SampleNotFoundError
from app.storage.encryption import seal_stream, unseal


class LocalFileSystemStorage:
    """Store encrypted samples under a root directory."""

    def __init__(self, root: Path, keys: Mapping[str, bytes], key_id: str) -> None:
        self._root = Path(root)
        self._keys = dict(keys)
        self._key_id = key_id

        if key_id not in self._keys:
            raise ValueError(f"Active key id {key_id!r} is not present in the keyring.")

        self._root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str) -> Path:
        # Two levels of fan-out. Short keys are tolerated so tests need not use
        # full digests.
        if len(key) >= 4:
            return self._root / key[:2] / key[2:4] / key
        return self._root / key

    async def put(self, key: str, source: Path) -> None:
        """Encrypt ``source`` and store it under ``key``."""
        await asyncio.to_thread(self._put_sync, key, Path(source))

    def _put_sync(self, key: str, source: Path) -> None:
        destination = self._path_for(key)
        destination.parent.mkdir(parents=True, exist_ok=True)

        # Write to a temporary neighbour and rename into place, so a crash
        # mid-write cannot leave a half-written object that later reads would
        # treat as real. Rename within a directory is atomic on both POSIX and
        # Windows filesystems we target.
        #
        # The staging name carries a random suffix as well as the process id.
        # Two callers submitting identical bytes at the same moment are storing
        # the same key, so a name derived only from the key and the pid would
        # have them writing to one file and renaming it out from under each
        # other.
        staging = destination.with_name(
            f"{destination.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.partial"
        )

        try:
            # Encrypted a chunk at a time, from one file to another. Reading the
            # sample into memory to seal it would hold two copies of a file that
            # may be 100 MB, at exactly the moment several may arrive at once.
            with source.open("rb") as plain, staging.open("wb") as sealed:
                seal_stream(
                    plain, sealed, key=self._keys[self._key_id], key_id=self._key_id
                )
            self._promote(staging, destination)
        except BaseException:
            staging.unlink(missing_ok=True)
            raise

    @staticmethod
    def _promote(staging: Path, destination: Path) -> None:
        """Move the finished object into place, tolerating a lost race.

        Windows refuses a rename onto a path another writer is replacing at the
        same instant, which happens whenever two callers submit identical bytes
        together - they are, by construction, writing the same key.

        Losing that race is harmless and needs no retry: content addressing
        means whoever won wrote exactly the same bytes. The only wrong response
        would be to report failure for an object that is present and correct.
        """
        try:
            os.replace(staging, destination)
        except OSError:
            if not destination.exists():
                raise
            staging.unlink(missing_ok=True)

    async def get(self, key: str) -> bytes:
        """Return the decrypted contents stored under ``key``."""
        return await asyncio.to_thread(self._get_sync, key)

    def _get_sync(self, key: str) -> bytes:
        path = self._path_for(key)
        if not path.exists():
            raise SampleNotFoundError(f"No stored sample for key {key!r}.")
        return unseal(path.read_bytes(), keys=self._keys)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path_for(key).exists)

    async def size_of(self, key: str) -> int:
        """Return the length of the *plaintext*.

        The file on disk is larger, because it carries the envelope header and
        authentication tag. Callers care about the sample, not the envelope, so
        the object is decrypted to answer.
        """
        return len(await self.get(key))

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._delete_sync, key)

    def _delete_sync(self, key: str) -> None:
        self._path_for(key).unlink(missing_ok=True)
