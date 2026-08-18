"""Request and response models.

Kept separate from the ORM models so a database change cannot silently alter
what clients receive.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.domain.models import Job, Sample


class SampleRead(BaseModel):
    """A stored sample, addressed by content."""

    model_config = ConfigDict(from_attributes=True)

    sha256: str
    sha1: str
    md5: str
    size_bytes: int
    first_seen_at: datetime
    submission_count: int = Field(
        description="How many times these exact bytes have been submitted."
    )

    @classmethod
    def from_sample(cls, sample: Sample) -> SampleRead:
        return cls(
            sha256=sample.sha256,
            sha1=sample.sha1,
            md5=sample.md5,
            size_bytes=sample.size_bytes,
            first_seen_at=sample.first_seen_at,
            submission_count=len(sample.jobs),
        )


class JobRead(BaseModel):
    """A job as returned to clients.

    Sample digests are flattened onto the job. Callers polling a job want to
    know what was analysed without a second request, and the alternative - a
    nested object - would break every existing consumer of ``size_bytes``.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    status: str
    original_filename: str

    sha256: str
    sha1: str
    md5: str
    size_bytes: int

    @classmethod
    def from_job(cls, job: Job) -> JobRead:
        return cls(
            id=job.id,
            created_at=job.created_at,
            status=job.status,
            original_filename=job.original_filename,
            sha256=job.sample.sha256,
            sha1=job.sample.sha1,
            md5=job.sample.md5,
            size_bytes=job.sample.size_bytes,
        )


class SubmissionAccepted(BaseModel):
    """Acknowledgement that a submission was accepted for analysis.

    202 rather than 201: the job has been queued, not completed. Nothing has
    been analysed at the point this is returned.
    """

    job_id: uuid.UUID = Field(description="Identifier for polling job status.")
    status: str = Field(description="Lifecycle state at the moment of acceptance.")
    sha256: str = Field(description="Content hash of the submitted bytes.")
    duplicate: bool = Field(
        description="True when these exact bytes had already been stored.",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sample_url(self) -> str:
        """Where to read the sample record."""
        return f"/api/v1/samples/{self.sha256}"
