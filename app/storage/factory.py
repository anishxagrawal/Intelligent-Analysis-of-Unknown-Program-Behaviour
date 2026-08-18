"""Build the configured storage backend.

One place that turns settings into a :class:`SampleStorage`. Routes and services
receive the protocol and never learn which implementation they were given.
"""

from __future__ import annotations

import hashlib

from app.config import Settings
from app.logging import get_logger
from app.storage.base import SampleStorage
from app.storage.encryption import key_from_base64
from app.storage.local import LocalFileSystemStorage
from app.storage.memory import InMemoryStorage

logger = get_logger(__name__)

#: Derived from a constant in this file, so it is public knowledge by
#: definition. It exists only so development and tests do not need key
#: management. Settings refuses to start in production without a real key.
_DEVELOPMENT_KEY = hashlib.sha256(b"upa-development-key-not-for-production").digest()


def build_storage(settings: Settings) -> SampleStorage:
    """Return the storage backend described by ``settings``."""
    if settings.storage_backend == "memory":
        logger.warning("using in-memory sample storage; nothing will be persisted")
        return InMemoryStorage()

    if settings.sample_encryption_key:
        key = key_from_base64(settings.sample_encryption_key)
    else:
        logger.warning(
            "no sample encryption key configured; using the public development key",
            extra={"environment": settings.environment},
        )
        key = _DEVELOPMENT_KEY

    return LocalFileSystemStorage(
        root=settings.storage_root,
        keys={settings.sample_encryption_key_id: key},
        key_id=settings.sample_encryption_key_id,
    )
