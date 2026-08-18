"""Content hashing.

Three digests are computed in a single pass over the bytes:

  SHA-256  the identity of a sample throughout this system
  SHA-1    still the lingua franca of many threat intelligence feeds
  MD5      obsolete for security, but the key most malware corpora are indexed by

MD5 and SHA-1 are recorded for lookup compatibility only. Nothing here trusts
them to establish that two files are the same; SHA-256 does that. Both are
broken against deliberate collisions, and an attacker who controls the file
contents can produce two different samples sharing an MD5.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class ContentHashes:
    """The digests and length of one piece of content."""

    sha256: str
    sha1: str
    md5: str
    size_bytes: int


class StreamHasher:
    """Compute all three digests incrementally while bytes stream past.

    Used so an upload is hashed during the single pass that writes it, rather
    than by reading the file again afterwards. Memory use stays constant
    regardless of input size.
    """

    def __init__(self) -> None:
        self._sha256 = hashlib.sha256()
        self._sha1 = hashlib.sha1()
        self._md5 = hashlib.md5()
        self.bytes_seen = 0

    def update(self, chunk: bytes) -> None:
        """Fold one chunk into every digest."""
        self._sha256.update(chunk)
        self._sha1.update(chunk)
        self._md5.update(chunk)
        self.bytes_seen += len(chunk)

    def result(self) -> ContentHashes:
        """Return the digests computed so far."""
        return ContentHashes(
            sha256=self._sha256.hexdigest(),
            sha1=self._sha1.hexdigest(),
            md5=self._md5.hexdigest(),
            size_bytes=self.bytes_seen,
        )


def hash_bytes(data: bytes) -> ContentHashes:
    """Hash a complete in-memory payload. Convenient for tests and small inputs."""
    hasher = StreamHasher()
    hasher.update(data)
    return hasher.result()
