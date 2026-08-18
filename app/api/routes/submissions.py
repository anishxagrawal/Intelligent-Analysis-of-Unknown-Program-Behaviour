"""Submission intake endpoint.

The route is deliberately thin. Streaming, hashing, deduplication and storage
all live in the intake service, because several of those steps have to agree
with each other and the reasoning belongs in one place.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Response, UploadFile, status

from app.api.deps import get_intake_service, get_settings_dep
from app.config import Settings
from app.domain.schemas import SubmissionAccepted
from app.services.intake import IntakeService

router = APIRouter(prefix="/submissions", tags=["submissions"])


@router.post(
    "",
    response_model=SubmissionAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a file for analysis",
)
async def create_submission(
    response: Response,
    file: UploadFile = File(description="The file to analyse."),
    intake: IntakeService = Depends(get_intake_service),
    settings: Settings = Depends(get_settings_dep),
) -> SubmissionAccepted:
    """Accept a file, store it, and queue a job for it.

    Returns 202 rather than 201: the work has been accepted, not performed.

    The submitted filename is attacker-controlled text. It is recorded as data
    and never used to build a path - stored objects are named by content hash -
    so a name like "../../evil.exe" cannot escape the storage root.
    """
    result = await intake.submit(file)

    response.headers["Location"] = f"{settings.api_prefix}/jobs/{result.job.id}"
    return SubmissionAccepted(
        job_id=result.job.id,
        status=result.job.status,
        sha256=result.hashes.sha256,
        duplicate=result.duplicate,
    )
