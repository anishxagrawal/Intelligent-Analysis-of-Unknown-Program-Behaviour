"""Issuing and checking API keys.

Keys are stored hashed. The plaintext is shown once, when the key is created,
and never again - so a stolen database dump yields no working credentials, and
nobody can recover a key by asking an administrator to look it up.

**Why SHA-256 and not bcrypt or Argon2.** Password hashes are deliberately slow
because passwords are low-entropy and chosen by people, so an attacker with the
hash can guess. These keys are 256 bits from ``secrets.token_urlsafe``: there is
nothing to guess, and a work factor would buy no security while adding
measurable latency to every single request. The threat a slow hash defends
against does not exist here.

Comparison uses ``compare_digest``. The lookup is by hash rather than by a
scanned list, so timing leakage is already minimal, but constant-time comparison
costs nothing and removes the question.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

#: Marks a string as one of our keys. Purely for humans: a key pasted into the
#: wrong field is recognisable in a log or a ticket, and a leaked credential can
#: be scanned for.
KEY_PREFIX = "upa_"

#: 32 bytes of entropy, urlsafe-encoded.
KEY_BYTES = 32


@dataclass(frozen=True)
class IssuedKey:
    """A newly created key, in the only moment its plaintext exists."""

    token: str
    token_hash: str


def generate_key() -> IssuedKey:
    """Mint a new API key."""
    token = f"{KEY_PREFIX}{secrets.token_urlsafe(KEY_BYTES)}"
    return IssuedKey(token=token, token_hash=hash_key(token))


def hash_key(token: str) -> str:
    """Return the stored form of a key.

    Deterministic and unsalted, on purpose: the database is looked up *by* this
    value, so an authentication is one indexed read rather than a scan of every
    key with a per-row hash computation.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def matches(token: str, token_hash: str) -> bool:
    """Constant-time check that ``token`` hashes to ``token_hash``."""
    return secrets.compare_digest(hash_key(token), token_hash)
