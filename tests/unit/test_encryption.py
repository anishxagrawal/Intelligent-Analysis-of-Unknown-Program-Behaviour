"""AC-03 groundwork: the encryption envelope.

Samples are live malware. Encrypting at rest means a stray backup, a misplaced
disk image or an over-broad file share does not hand someone a working payload.
"""

from __future__ import annotations

import os

import pytest

from app.storage.encryption import (
    ENVELOPE_MAGIC,
    DecryptionError,
    generate_key,
    key_from_base64,
    key_id_of,
    seal,
    unseal,
)

pytestmark = pytest.mark.unit

PLAINTEXT = b"MZ\x90\x00 pretend this is a malicious executable"


@pytest.fixture
def key() -> bytes:
    return generate_key()


def test_round_trip_recovers_the_original(key: bytes) -> None:
    blob = seal(PLAINTEXT, key=key, key_id="k1")

    assert unseal(blob, keys={"k1": key}) == PLAINTEXT


def test_plaintext_is_absent_from_the_envelope(key: bytes) -> None:
    """The property AC-03 ultimately rests on."""
    blob = seal(PLAINTEXT, key=key, key_id="k1")

    assert PLAINTEXT not in blob
    assert b"pretend this is a malicious executable" not in blob


def test_same_plaintext_encrypts_differently_each_time(key: bytes) -> None:
    """A fresh nonce per object. Without it, identical files would be visibly
    identical on disk, leaking which samples match."""
    first = seal(PLAINTEXT, key=key, key_id="k1")
    second = seal(PLAINTEXT, key=key, key_id="k1")

    assert first != second
    assert unseal(first, keys={"k1": key}) == unseal(second, keys={"k1": key})


def test_envelope_records_the_key_id_for_rotation(key: bytes) -> None:
    blob = seal(PLAINTEXT, key=key, key_id="2026-q3")

    assert key_id_of(blob) == "2026-q3"


def test_old_objects_stay_readable_after_a_new_key_is_introduced() -> None:
    """Rotation must not orphan existing data."""
    old, new = generate_key(), generate_key()
    archived = seal(PLAINTEXT, key=old, key_id="old")
    fresh = seal(PLAINTEXT, key=new, key_id="new")

    keyring = {"old": old, "new": new}

    assert unseal(archived, keys=keyring) == PLAINTEXT
    assert unseal(fresh, keys=keyring) == PLAINTEXT


def test_wrong_key_is_rejected(key: bytes) -> None:
    blob = seal(PLAINTEXT, key=key, key_id="k1")

    with pytest.raises(DecryptionError):
        unseal(blob, keys={"k1": generate_key()})


def test_unknown_key_id_is_rejected(key: bytes) -> None:
    blob = seal(PLAINTEXT, key=key, key_id="missing")

    with pytest.raises(DecryptionError, match="Unknown key id"):
        unseal(blob, keys={"k1": key})


def test_tampering_is_detected(key: bytes) -> None:
    """AES-GCM authenticates. A flipped bit must fail loudly, not decrypt to
    something subtly wrong."""
    blob = bytearray(seal(PLAINTEXT, key=key, key_id="k1"))
    blob[-1] ^= 0x01

    with pytest.raises(DecryptionError):
        unseal(bytes(blob), keys={"k1": key})


def test_foreign_data_is_rejected(key: bytes) -> None:
    with pytest.raises(DecryptionError, match="not a sealed envelope"):
        unseal(b"just some bytes that are not an envelope", keys={"k1": key})


def test_envelope_starts_with_its_magic(key: bytes) -> None:
    assert seal(PLAINTEXT, key=key, key_id="k1").startswith(ENVELOPE_MAGIC)


def test_empty_payload_round_trips(key: bytes) -> None:
    assert unseal(seal(b"", key=key, key_id="k1"), keys={"k1": key}) == b""


def test_key_from_base64_round_trips() -> None:
    import base64

    raw = generate_key()
    assert key_from_base64(base64.b64encode(raw).decode()) == raw


def test_key_from_base64_rejects_wrong_length() -> None:
    import base64

    with pytest.raises(ValueError, match="32 bytes"):
        key_from_base64(base64.b64encode(os.urandom(16)).decode())


# -- Streaming ------------------------------------------------------------


def test_streamed_and_buffered_envelopes_are_interchangeable(key: bytes) -> None:
    """The streaming path is an optimisation, not a second format.

    Objects written before it existed must stay readable, and objects written
    by it must be readable by anything that could read the old ones.
    """
    from io import BytesIO

    from app.storage.encryption import seal_stream

    sink = BytesIO()
    seal_stream(BytesIO(PLAINTEXT), sink, key=key, key_id="k1")

    assert unseal(sink.getvalue(), keys={"k1": key}) == PLAINTEXT


def test_a_streamed_envelope_has_the_same_shape(key: bytes) -> None:
    from io import BytesIO

    from app.storage.encryption import seal_stream

    sink = BytesIO()
    seal_stream(BytesIO(PLAINTEXT), sink, key=key, key_id="k1")

    assert sink.getvalue().startswith(ENVELOPE_MAGIC)
    assert len(sink.getvalue()) == len(seal(PLAINTEXT, key=key, key_id="k1"))


def test_streaming_crosses_chunk_boundaries_correctly(key: bytes) -> None:
    """A payload spanning several chunks is where an off-by-one would show."""
    from io import BytesIO

    from app.storage.encryption import seal_stream

    payload = bytes(range(256)) * 400
    sink = BytesIO()
    seal_stream(BytesIO(payload), sink, key=key, key_id="k1", chunk_size=1024)

    assert unseal(sink.getvalue(), keys={"k1": key}) == payload


def test_streaming_an_empty_payload_round_trips(key: bytes) -> None:
    from io import BytesIO

    from app.storage.encryption import seal_stream

    sink = BytesIO()
    seal_stream(BytesIO(b""), sink, key=key, key_id="k1")

    assert unseal(sink.getvalue(), keys={"k1": key}) == b""


def test_streaming_detects_tampering(key: bytes) -> None:
    """Authentication is the reason for GCM; streaming must not weaken it."""
    from io import BytesIO

    from app.storage.encryption import DecryptionError, seal_stream

    sink = BytesIO()
    seal_stream(BytesIO(PLAINTEXT), sink, key=key, key_id="k1")
    blob = bytearray(sink.getvalue())
    blob[-20] ^= 0xFF

    with pytest.raises(DecryptionError):
        unseal(bytes(blob), keys={"k1": key})
