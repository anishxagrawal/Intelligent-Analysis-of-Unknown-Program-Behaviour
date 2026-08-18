"""Shared FastAPI dependencies.

Settings, the session factory and the storage backend are read from application
state rather than from module-level globals. That is what lets the test suite
build an application around a throwaway database and a temporary storage root
without mutating anything process-wide.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.queue.base import JobQueue
from app.queue.database import DatabaseJobQueue
from app.services.intake import IntakeService
from app.storage.base import SampleStorage


def get_settings_dep(request: Request) -> Settings:
    """Return the settings this application instance was built with."""
    settings: Settings = request.app.state.settings
    return settings


def get_storage(request: Request) -> SampleStorage:
    """Return the configured storage backend."""
    storage: SampleStorage = request.app.state.storage
    return storage


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a database session for the duration of one request."""
    sessionmaker = request.app.state.sessionmaker
    async with sessionmaker() as session:
        yield session


def get_queue(session: AsyncSession = Depends(get_session)) -> JobQueue:
    """Return a job queue bound to this request's session.

    Bound to the session on purpose: enqueueing has to commit with the sample
    row it depends on, not separately from it.
    """
    return DatabaseJobQueue(session)


def get_intake_service(
    session: AsyncSession = Depends(get_session),
    storage: SampleStorage = Depends(get_storage),
    queue: JobQueue = Depends(get_queue),
    settings: Settings = Depends(get_settings_dep),
) -> IntakeService:
    """Assemble the intake service for one request."""
    return IntakeService(
        session=session,
        storage=storage,
        queue=queue,
        max_upload_bytes=settings.max_upload_bytes,
    )
