"""Submission intake.

This is where the coordination v2 introduces actually lives: stream, hash,
deduplicate, store, record. It is a service rather than route code because
several steps now have to agree with each other, and because the ordering below
carries reasoning worth keeping in one place.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.domain.hashing import ContentHashes, StreamHasher
from app.domain.models import Job, Sample
from app.logging import get_logger
from app.queue.base import JobQueue
from app.storage.base import SampleStorage

logger = get_logger(__name__)

#: Upload copy buffer. Large enough to keep syscall counts down, small enough
#: that memory use never tracks the size of the upload.
CHUNK_SIZE = 64 * 1024


class UploadTooLargeError(AppError):
    status_code = status.HTTP_413_CONTENT_TOO_LARGE
    title = "Payload Too Large"
    code = "upload-too-large"


@dataclass(frozen=True)
class IntakeResult:
    """What happened to one submission."""

    job: Job
    hashes: ContentHashes
    duplicate: bool


class IntakeService:
    """Accept an upload and turn it into a stored sample and a queued job."""

    def __init__(
        self,
        session: AsyncSession,
        storage: SampleStorage,
        queue: JobQueue,
        max_upload_bytes: int,
    ) -> None:
        self._session = session
        self._storage = storage
        self._queue = queue
        self._max_upload_bytes = max_upload_bytes

    async def submit(self, upload: UploadFile) -> IntakeResult:
        """Store the uploaded bytes and record a job for them."""
        staged, hashes = await self._stage(upload)
        try:
            return await self._record(staged, hashes, upload.filename or "unnamed")
        finally:
            # The staging file is always removed. It has either been copied into
            # storage or is not wanted, and either way leaving it would slowly
            # fill the disk with material nothing references.
            staged.unlink(missing_ok=True)

    async def _stage(self, upload: UploadFile) -> tuple[Path, ContentHashes]:
        """Stream the upload to a temporary file, hashing as it goes.

        The size limit is enforced *during* the stream. Checking afterwards
        would mean a caller could make the service consume unbounded disk before
        the request was refused.
        """
        hasher = StreamHasher()
        descriptor, name = tempfile.mkstemp(suffix=".upload")
        staged = Path(name)

        try:
            with os.fdopen(descriptor, "wb") as sink:
                while chunk := await upload.read(CHUNK_SIZE):
                    hasher.update(chunk)
                    if hasher.bytes_seen > self._max_upload_bytes:
                        raise UploadTooLargeError(
                            f"Upload exceeds the {self._max_upload_bytes} byte limit."
                        )
                    sink.write(chunk)
        except BaseException:
            staged.unlink(missing_ok=True)
            raise

        return staged, hasher.result()

    async def _record(self, staged: Path, hashes: ContentHashes, filename: str) -> IntakeResult:
        """Store the content if new, then create a job referring to it."""
        sample = await self._session.get(Sample, hashes.sha256)
        duplicate = sample is not None

        # Storing is idempotent because the key is the content hash, so a repeat
        # put writes identical bytes. The existence check also repairs the case
        # where a row survived but the object did not.
        if not await self._storage.exists(hashes.sha256):
            await self._storage.put(hashes.sha256, staged)

        if sample is None:
            sample = Sample(
                sha256=hashes.sha256,
                sha1=hashes.sha1,
                md5=hashes.md5,
                size_bytes=hashes.size_bytes,
            )
            self._session.add(sample)

        job = Job(original_filename=filename, sample_sha256=hashes.sha256)

        # Enqueueing joins this transaction rather than opening its own, so the
        # job becomes claimable at the same instant its sample row becomes
        # readable. A worker cannot see work whose input does not yet exist.
        await self._queue.enqueue(job)

        # Ordering note.
        #
        # The object is stored before the rows are committed. If the commit
        # fails, a stored object is left with nothing referring to it.
        #
        # In v1 that was a genuine leak. Content addressing makes it benign: the
        # object is keyed by its own hash, so the next submission of those bytes
        # finds it already present and adopts it rather than writing a second
        # copy. The orphan is inert and self-healing.
        #
        # The reverse ordering remains worse. A committed row pointing at
        # content that was never stored is a lie every later reader has to
        # defend against.
        await self._session.commit()
        await self._session.refresh(job, attribute_names=["sample"])

        logger.info(
            "submission accepted",
            extra={
                "job_id": str(job.id),
                "sha256": hashes.sha256,
                "size_bytes": hashes.size_bytes,
                "duplicate": duplicate,
            },
        )

        return IntakeResult(job=job, hashes=hashes, duplicate=duplicate)


async def find_sample(session: AsyncSession, sha256: str) -> Sample | None:
    """Look up one sample by digest."""
    result = await session.execute(select(Sample).where(Sample.sha256 == sha256))
    return result.unique().scalar_one_or_none()
