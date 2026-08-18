"""Job status queries.

v1 supports fetching one job by id. Listing, filtering and pagination arrive
later, once there is a lifecycle worth filtering on.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.api.errors import JobNotFoundError
from app.domain.models import Job
from app.domain.schemas import JobRead
from app.security.auth import Caller, require_scope
from app.security.scopes import Scope

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobRead, summary="Fetch one job")
async def read_job(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    caller: Caller = Depends(require_scope(Scope.JOBS_READ)),
) -> JobRead:
    """Return a single job, or a problem-details 404 if it does not exist."""
    job = await session.get(Job, job_id)
    if job is None:
        raise JobNotFoundError(f"No job with id {job_id}.")
    return JobRead.from_job(job)
