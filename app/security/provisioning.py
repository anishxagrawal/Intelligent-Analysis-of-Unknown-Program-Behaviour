"""Creating API keys.

A new deployment has no keys, and no way to call the endpoint that would create
one - which is the usual bootstrap problem. Two answers, for two situations:

  * development and tests set ``UPA_BOOTSTRAP_API_KEY`` and get a known key with
    every scope, created at startup
  * anywhere else runs ``scripts/create-api-key.py``, which mints a random key,
    prints it once, and stores only its hash

Settings refuse the first in production. A credential passed through an
environment variable is visible in process listings and orchestrator manifests,
and it is the same value on every instance.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.models import ApiKey
from app.logging import get_logger
from app.security.keys import generate_key, hash_key
from app.security.scopes import Scope

logger = get_logger(__name__)

BOOTSTRAP_KEY_NAME = "bootstrap"


async def ensure_bootstrap_key(
    sessionmaker: async_sessionmaker[AsyncSession],
    token: str,
    *,
    name: str = BOOTSTRAP_KEY_NAME,
) -> None:
    """Make sure the development key exists, without duplicating it on restart."""
    token_hash = hash_key(token)

    async with sessionmaker() as session:
        existing = await session.scalar(select(ApiKey).where(ApiKey.token_hash == token_hash))
        if existing is not None:
            return

        session.add(
            ApiKey(
                name=name,
                token_hash=token_hash,
                scopes=[scope.value for scope in Scope],
            )
        )
        await session.commit()

    logger.warning(
        "bootstrap API key active; do not use this outside development",
        extra={"key_name": name},
    )


async def create_api_key(
    session: AsyncSession,
    name: str,
    scopes: list[Scope],
) -> str:
    """Mint a key, store its hash, and return the plaintext exactly once.

    The caller is responsible for showing the returned token to a human
    immediately. It cannot be recovered afterwards, by anyone, including whoever
    runs the database.
    """
    issued = generate_key()
    session.add(
        ApiKey(
            name=name,
            token_hash=issued.token_hash,
            scopes=[scope.value for scope in scopes],
        )
    )
    await session.commit()

    logger.info("api key created", extra={"key_name": name, "scopes": [s.value for s in scopes]})
    return issued.token
