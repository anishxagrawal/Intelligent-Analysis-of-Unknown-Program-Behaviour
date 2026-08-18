"""In-memory sample storage.

A test double, and the second implementation that keeps the storage protocol
honest. Nothing here touches a disk, so a contract test passing against both
this and the filesystem backend is real evidence the interface holds rather than
leaking filesystem assumptions.

Not encrypted, deliberately: encryption protects data at rest, and nothing here
is at rest. Never use this outside tests - it grows without bound and vanishes
when the process exits.
"""

from __future__ import annotations

from pathlib import Path

from app.storage.base import SampleNotFoundError


class InMemoryStorage:
    """Keep sample bytes in a dictionary."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    async def put(self, key: str, source: Path) -> None:
        self._objects[key] = Path(source).read_bytes()

    async def get(self, key: str) -> bytes:
        try:
            return self._objects[key]
        except KeyError as exc:
            raise SampleNotFoundError(f"No stored sample for key {key!r}.") from exc

    async def exists(self, key: str) -> bool:
        return key in self._objects

    async def size_of(self, key: str) -> int:
        return len(await self.get(key))

    async def delete(self, key: str) -> None:
        self._objects.pop(key, None)
