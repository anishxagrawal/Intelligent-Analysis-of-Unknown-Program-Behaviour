"""Submission intake.

v1 is deliberately naive. It does not hash, encrypt, deduplicate, detect the
file type, or enforce a size limit, and it deliberately contains no storage
abstraction. Those arrive in v2 and v4, at which point this route's body is
replaced wholesale.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, get_settings_dep
from app.config import Settings
from app.domain.models import Job
from app.domain.schemas import SubmissionAccepted
from app.logging import get_logger

router = APIRouter(prefix="/submissions", tags=["submissions"])
logger = get_logger(__name__)

#: Upload copy buffer. Large enough to keep syscalls down, small enough that
#: memory use does not track the size of the upload.
CHUNK_SIZE = 64 * 1024


async def _write_upload(upload: UploadFile, destination: Path) -> int:
    """Copy an upload to disk in chunks, returning the number of bytes written.

    Chunked rather than ``await upload.read()`` so that memory use stays flat
    regardless of file size. This is not an abstraction over storage - it is a
    loop - and v2 replaces it with a real storage backend.
    """
    total = 0
    with destination.open("wb") as sink:
        while chunk := await upload.read(CHUNK_SIZE):
            sink.write(chunk)
            total += len(chunk)
    return total


@router.post(
    "",
    response_model=SubmissionAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a file for analysis",
)
async def create_submission(
    response: Response,
    file: UploadFile = File(description="The file to analyse."),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings_dep),
) -> SubmissionAccepted:
    """Accept a file, store it, and queue a job for it.

    Returns 202 rather than 201: the work has been accepted, not performed.
    Nothing has been analysed by the time this responds.
    """
    job_id = uuid.uuid4()

    # The submitted filename is attacker-controlled text. It is recorded as
    # data and never used to build a path, so a name like "../../evil.exe"
    # cannot escape the storage root. The job id is the filename on disk.
    destination = settings.storage_root / str(job_id)

    # Ordering note, and a known limitation of v1.
    #
    # The file is written before the row is committed. If the write succeeds and
    # the commit then fails, an orphaned file is left in storage with no row
    # referring to it: wasted disk that nothing cleans up.
    #
    # The alternative ordering fails worse. Committing first would allow a job
    # row that points at a file which does not exist - a lie that every later
    # reader has to defend against. An unreferenced file is inert.
    #
    # v1 accepts this rather than introducing a transaction manager, an outbox,
    # a compensating delete or a background reaper. The question belongs with
    # the storage boundary in v2.
    size_bytes = await _write_upload(file, destination)

    job = Job(
        id=job_id,
        original_filename=file.filename or "unnamed",
        size_bytes=size_bytes,
    )
    session.add(job)
    await session.commit()

    logger.info(
        "submission accepted",
        extra={"job_id": str(job_id), "size_bytes": size_bytes},
    )

    response.headers["Location"] = f"{settings.api_prefix}/jobs/{job_id}"
    return SubmissionAccepted(job_id=job_id, status=job.status)
