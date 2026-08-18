"""The sample storage boundary.

This protocol was extracted from the working local writer in v1 rather than
designed in advance. Every method exists because a caller needed it: the
submission route puts and deletes, deduplication checks existence, and the
download endpoint in v5 will get.

Deliberately absent: any notion of paths, directories, encryption or buckets.
Callers address content by key and nothing else, which is what allows object
storage to replace the filesystem later without touching a single caller.

The key is always a sample's SHA-256 digest. Content addressing gives three
properties worth naming, because the rest of the design leans on them:

  * storing the same bytes twice is harmless, so races are not a correctness
    problem
  * an interrupted store can simply be retried
  * a stored object left behind by a failed transaction is inert, and the next
    submission of those bytes adopts it rather than duplicating it
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


class StorageError(Exception):
    """Base class for storage failures."""


class SampleNotFoundError(StorageError):
    """Raised when a key has no stored object."""


@runtime_checkable
class SampleStorage(Protocol):
    """Somewhere sample bytes can be kept and retrieved by content hash."""

    async def put(self, key: str, source: Path) -> None:
        """Store the contents of ``source`` under ``key``.

        Storing an existing key again must be harmless, because content
        addressing means the bytes are identical by definition.
        """
        ...

    async def get(self, key: str) -> bytes:
        """Return the stored bytes, or raise :class:`SampleNotFoundError`."""
        ...

    async def exists(self, key: str) -> bool:
        """Report whether anything is stored under ``key``."""
        ...

    async def size_of(self, key: str) -> int:
        """Return the length of the stored content in bytes."""
        ...

    async def delete(self, key: str) -> None:
        """Remove the object. Deleting an absent key is not an error.

        Cleanup runs when something has already gone wrong, so it must not fail
        and mask the original problem.
        """
        ...
