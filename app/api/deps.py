"""Shared FastAPI dependencies.

Settings and the session factory are read from application state rather than
from the cached module-level accessor. That is what lets the test suite build an
application around a throwaway database without mutating process-wide state.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings


def get_settings_dep(request: Request) -> Settings:
    """Return the settings this application instance was built with."""
    settings: Settings = request.app.state.settings
    return settings


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a database session for the duration of one request."""
    sessionmaker = request.app.state.sessionmaker
    async with sessionmaker() as session:
        yield session
