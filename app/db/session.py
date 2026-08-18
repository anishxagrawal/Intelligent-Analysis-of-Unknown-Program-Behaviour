"""Database engine and session management.

The engine is built per application instance rather than at import time. That
keeps the test suite honest: each run points at its own throwaway database, and
nothing is shared through module-level state.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    """Build an async engine for the configured database."""
    return create_async_engine(
        settings.database_url,
        echo=settings.database_echo,
        pool_pre_ping=True,
    )


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Build a session factory bound to the given engine.

    ``expire_on_commit=False`` so that attributes remain readable after a commit.
    Without it, serialising an object after committing triggers a fresh database
    round trip, which fails once the request's session has closed.
    """
    return async_sessionmaker(bind=engine, expire_on_commit=False)
