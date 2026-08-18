"""AC-04: hashes match known test vectors.

Known-answer tests, not round-trip tests. A round trip would pass even if the
implementation hashed the wrong thing consistently; published vectors catch that.
"""

from __future__ import annotations

import pytest

from app.domain.hashing import ContentHashes, StreamHasher, hash_bytes

pytestmark = pytest.mark.unit

# Published vectors for the empty input and for b"abc".
EMPTY = ContentHashes(
    sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    sha1="da39a3ee5e6b4b0d3255bfef95601890afd80709",
    md5="d41d8cd98f00b204e9800998ecf8427e",
    size_bytes=0,
)
ABC = ContentHashes(
    sha256="ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    sha1="a9993e364706816aba3e25717850c26c9cd0d89d",
    md5="900150983cd24fb0d6963f7d28e17f72",
    size_bytes=3,
)


def test_empty_input_matches_published_vectors() -> None:
    assert hash_bytes(b"") == EMPTY


def test_abc_matches_published_vectors() -> None:
    assert hash_bytes(b"abc") == ABC


def test_streaming_matches_single_shot() -> None:
    """Chunk boundaries must not affect the result."""
    hasher = StreamHasher()
    for chunk in (b"a", b"b", b"c"):
        hasher.update(chunk)

    assert hasher.result() == ABC


def test_chunk_size_does_not_change_the_hash() -> None:
    payload = bytes(range(256)) * 40

    one_shot = hash_bytes(payload)

    hasher = StreamHasher()
    for start in range(0, len(payload), 7):  # deliberately awkward chunk size
        hasher.update(payload[start : start + 7])

    assert hasher.result() == one_shot


def test_size_is_counted_while_streaming() -> None:
    hasher = StreamHasher()
    hasher.update(b"0123456789")
    hasher.update(b"0123456789")

    assert hasher.bytes_seen == 20
    assert hasher.result().size_bytes == 20


def test_hashes_are_lowercase_hex() -> None:
    result = hash_bytes(b"anything")

    for digest in (result.sha256, result.sha1, result.md5):
        assert digest == digest.lower()
        assert all(character in "0123456789abcdef" for character in digest)


def test_digest_lengths_are_correct() -> None:
    result = hash_bytes(b"anything")

    assert len(result.sha256) == 64
    assert len(result.sha1) == 40
    assert len(result.md5) == 32
