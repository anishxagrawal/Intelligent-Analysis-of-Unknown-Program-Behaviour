"""Sample lookup by content hash."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.api.errors import AppError
from app.domain.schemas import SampleRead
from app.services.intake import find_sample

router = APIRouter(prefix="/samples", tags=["samples"])


class SampleRecordNotFoundError(AppError):
    """No database row for this digest.

    Distinct from storage.SampleNotFoundError, which means the bytes are missing
    from the backend. Different failures, deliberately different names.
    """

    status_code = status.HTTP_404_NOT_FOUND
    title = "Sample Not Found"
    code = "sample-not-found"


@router.get("/{sha256}", response_model=SampleRead, summary="Fetch one sample by digest")
async def read_sample(
    sha256: str,
    session: AsyncSession = Depends(get_session),
) -> SampleRead:
    """Return the stored record for a content hash."""
    sample = await find_sample(session, sha256.lower())
    if sample is None:
        raise SampleRecordNotFoundError(f"No sample stored with sha256 {sha256}.")
    return SampleRead.from_sample(sample)
