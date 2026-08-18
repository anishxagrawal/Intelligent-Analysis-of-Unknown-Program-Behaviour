"""Authenticated encryption for stored samples.

Stored samples are live malware. Encrypting at rest means a stray backup, a
misplaced disk image or an over-broad file share does not hand someone a
working payload.

AES-256-GCM is used because it authenticates as well as encrypts: a modified
object fails to decrypt rather than yielding subtly wrong bytes. For malware
analysis that matters more than usual, since every conclusion downstream rests
on the sample being exactly what was submitted.

Envelope layout::

    magic (4)  key_id_len (1)  key_id (n)  nonce (12)  ciphertext + tag

The key id travels with the object so keys can be rotated without rewriting
everything already stored. Old objects stay readable as long as their key stays
in the keyring.
"""

from __future__ import annotations

import base64
import os
from collections.abc import Mapping

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

#: Identifies our envelope format and version. A different first four bytes
#: means the object was not written by this system.
ENVELOPE_MAGIC = b"UPA1"

KEY_SIZE = 32  # AES-256
NONCE_SIZE = 12  # the size GCM is specified for
MAX_KEY_ID_LENGTH = 255


class DecryptionError(Exception):
    """Raised when an object cannot be decrypted or fails authentication."""


def generate_key() -> bytes:
    """Generate a fresh 256-bit key from the operating system's CSPRNG."""
    return os.urandom(KEY_SIZE)


def key_from_base64(encoded: str) -> bytes:
    """Decode a base64 key from configuration, rejecting anything wrong-sized."""
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception as exc:  # any decode failure means the same thing here
        raise ValueError("Encryption key must be valid base64.") from exc

    if len(raw) != KEY_SIZE:
        raise ValueError(f"Encryption key must decode to exactly {KEY_SIZE} bytes.")
    return raw


def seal(plaintext: bytes, *, key: bytes, key_id: str) -> bytes:
    """Encrypt a payload into a self-describing envelope."""
    if len(key) != KEY_SIZE:
        raise ValueError(f"Key must be {KEY_SIZE} bytes.")

    key_id_bytes = key_id.encode("utf-8")
    if not key_id_bytes or len(key_id_bytes) > MAX_KEY_ID_LENGTH:
        raise ValueError(f"Key id must be 1 to {MAX_KEY_ID_LENGTH} bytes when encoded.")

    # A fresh nonce per object. Reusing a nonce with the same key breaks GCM
    # badly, and identical objects would otherwise be visibly identical on disk.
    nonce = os.urandom(NONCE_SIZE)

    # The header is authenticated but not encrypted, so a tampered key id is
    # detected rather than silently followed.
    header = ENVELOPE_MAGIC + bytes([len(key_id_bytes)]) + key_id_bytes
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, header)

    return header + nonce + ciphertext


def key_id_of(blob: bytes) -> str:
    """Read the key id from an envelope without decrypting it."""
    _, key_id, _, _ = _split(blob)
    return key_id


def unseal(blob: bytes, *, keys: Mapping[str, bytes]) -> bytes:
    """Decrypt an envelope using whichever key it names."""
    header, key_id, nonce, ciphertext = _split(blob)

    key = keys.get(key_id)
    if key is None:
        raise DecryptionError(f"Unknown key id {key_id!r}; cannot decrypt this object.")

    try:
        return AESGCM(key).decrypt(nonce, ciphertext, header)
    except InvalidTag as exc:
        raise DecryptionError(
            "Object failed authentication: wrong key, or the data was modified."
        ) from exc


def _split(blob: bytes) -> tuple[bytes, str, bytes, bytes]:
    """Parse an envelope into header, key id, nonce and ciphertext."""
    if len(blob) < len(ENVELOPE_MAGIC) + 1 or not blob.startswith(ENVELOPE_MAGIC):
        raise DecryptionError("Object is not a sealed envelope.")

    key_id_length = blob[len(ENVELOPE_MAGIC)]
    key_id_start = len(ENVELOPE_MAGIC) + 1
    nonce_start = key_id_start + key_id_length
    ciphertext_start = nonce_start + NONCE_SIZE

    if len(blob) < ciphertext_start:
        raise DecryptionError("Object is not a sealed envelope: truncated header.")

    header = blob[:nonce_start]
    try:
        key_id = blob[key_id_start:nonce_start].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DecryptionError("Object is not a sealed envelope: malformed key id.") from exc

    return header, key_id, blob[nonce_start:ciphertext_start], blob[ciphertext_start:]
