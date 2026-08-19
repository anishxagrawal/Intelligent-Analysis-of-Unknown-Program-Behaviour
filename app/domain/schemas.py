"""Request and response models.

Kept separate from the ORM models so a database change cannot silently alter
what clients receive.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.domain.enums import JobStatus, RunOutcome
from app.domain.models import Job, Sample
from app.filetypes.base import FileType


class SampleRead(BaseModel):
    """A stored sample, addressed by content."""

    model_config = ConfigDict(from_attributes=True)

    sha256: str
    sha1: str
    md5: str
    size_bytes: int
    first_seen_at: datetime
    file_type: FileType = Field(
        description="Container format, decided from the leading bytes and never from the name.",
    )
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
            file_type=sample.file_type,
            submission_count=len(sample.jobs),
        )


class Provenance(BaseModel):
    """Which versions of this system handled a job.

    Stamped at creation, returned on every read, and never recomputed from the
    running process. A result explained months later has to be traceable to the
    code and schema that produced it, and a stamp that reflects today's
    deployment answers a different question than the one being asked.
    """

    app_version: str = Field(description="Version of the application code.")
    schema_version: str = Field(description="Version of the database schema.")
    config_version: str = Field(description="Version of the configuration contract.")


class JobRead(BaseModel):
    """A job as returned to clients.

    Sample digests are flattened onto the job. Callers polling a job want to
    know what was analysed without a second request, and the alternative - a
    nested object - would break every existing consumer of ``size_bytes``.

    ``status`` and ``run_outcome`` are separate fields rather than one merged
    value, mirroring the domain. A client asking "is this done" and a client
    asking "what did the run show" are asking different questions, and the
    second has no answer until the first is ``finished``.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    status: JobStatus
    original_filename: str

    run_outcome: RunOutcome | None = Field(
        default=None,
        description="What the run produced. Null until the job is finished.",
    )
    attempts: int = Field(
        default=0,
        description="How many times this job has been handed to a worker.",
    )
    failure_reason: str | None = Field(
        default=None,
        description="Why the job stopped without a run outcome, when that is what happened.",
    )

    sha256: str
    sha1: str
    md5: str
    size_bytes: int
    file_type: FileType = Field(
        default=FileType.UNKNOWN,
        description="Container format of the submitted bytes.",
    )

    provenance: Provenance = Field(
        description="Versions in force when this job was created.",
    )

    @classmethod
    def from_job(cls, job: Job) -> JobRead:
        return cls(
            id=job.id,
            created_at=job.created_at,
            status=job.status,
            original_filename=job.original_filename,
            run_outcome=job.run_outcome,
            attempts=job.attempts,
            failure_reason=job.failure_reason,
            sha256=job.sample.sha256,
            sha1=job.sample.sha1,
            md5=job.sample.md5,
            size_bytes=job.sample.size_bytes,
            file_type=job.sample.file_type,
            provenance=Provenance(
                app_version=job.app_version,
                schema_version=job.schema_version,
                config_version=job.config_version,
            ),
        )


class SubmissionAccepted(BaseModel):
    """Acknowledgement that a submission was accepted for analysis.

    202 rather than 201: the job has been queued, not completed. Nothing has
    been analysed at the point this is returned.
    """

    job_id: uuid.UUID = Field(description="Identifier for polling job status.")
    status: JobStatus = Field(description="Lifecycle state at the moment of acceptance.")
    sha256: str = Field(description="Content hash of the submitted bytes.")
    file_type: FileType = Field(
        description="Container format, decided from the leading bytes and never from the name.",
    )
    duplicate: bool = Field(
        description="True when these exact bytes had already been stored.",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sample_url(self) -> str:
        """Where to read the sample record."""
        return f"/api/v1/samples/{self.sha256}"
