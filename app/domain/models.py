"""ORM models.

Two tables. The split matters: a *sample* is content, a *job* is a request to
analyse it. Submitting the same file twice creates two jobs referring to one
sample, which is what allows storage to be deduplicated while still recording
that the file was seen again.

Later versions extend this:
  v4 adds the detected file type to Sample.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.domain.enums import JobStatus, RunOutcome
from app.domain.lifecycle import validate_transition

SHA256_LENGTH = 64
SHA1_LENGTH = 40
MD5_LENGTH = 32

#: Native PostgreSQL enum types. ``values_callable`` stores the lowercase
#: values rather than the Python member names, so what is in the database reads
#: the same as what appears in the API.
JOB_STATUS_ENUM = Enum(
    JobStatus,
    name="job_status",
    values_callable=lambda enum: [member.value for member in enum],
)
RUN_OUTCOME_ENUM = Enum(
    RunOutcome,
    name="run_outcome",
    values_callable=lambda enum: [member.value for member in enum],
)


def _utc_now() -> datetime:
    """Timezone-aware current time.

    Defaulted in Python rather than by the database so behaviour is identical
    wherever a row is created, including in tests that reason about ordering.
    """
    return datetime.now(UTC)


class Sample(Base):
    """One distinct piece of content, identified by its SHA-256 digest.

    The digest is the primary key. Content addressing means the same bytes are
    always the same row, so a duplicate submission is a lookup rather than an
    insert, and a stored object left behind by a failed transaction is adopted
    by the next submission of those bytes rather than duplicated.

    SHA-1 and MD5 are recorded for lookup against external corpora and feeds,
    which are still largely indexed by them. Neither is trusted to establish
    identity here.
    """

    __tablename__ = "samples"

    sha256: Mapped[str] = mapped_column(String(SHA256_LENGTH), primary_key=True)
    sha1: Mapped[str] = mapped_column(String(SHA1_LENGTH), nullable=False, index=True)
    md5: Mapped[str] = mapped_column(String(MD5_LENGTH), nullable=False, index=True)

    # BigInteger: a 32-bit column tops out at 2 GB, which is a limit worth not
    # discovering later.
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )

    jobs: Mapped[list[Job]] = relationship(back_populates="sample", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Sample sha256={self.sha256[:12]}... size={self.size_bytes}>"


class Job(Base):
    """One request to analyse one sample.

    ``original_filename`` lives here rather than on Sample because it belongs to
    the submission, not the content: the same bytes may arrive as
    ``invoice.exe`` one day and ``update.exe`` the next, and that difference is
    itself evidence.

    The lease columns - ``claimed_by`` and ``lease_expires_at`` - are what makes
    handing work to a worker survivable. A worker that dies mid-run cannot say
    so, so ownership is granted for a limited time and must be renewed. When it
    is not renewed the reaper takes the job back. Without that, one crashed
    worker quietly loses a submission forever.
    """

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )
    status: Mapped[JobStatus] = mapped_column(
        JOB_STATUS_ENUM, default=JobStatus.QUEUED, nullable=False, index=True
    )
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)

    # -- Run result ------------------------------------------------------
    #
    # Null until the job finishes, and never null once it has. The pairing is
    # enforced in :func:`app.domain.lifecycle.validate_transition` rather than
    # by a database constraint, because the rule is about the transition, not
    # about any single row state.
    run_outcome: Mapped[RunOutcome | None] = mapped_column(
        RUN_OUTCOME_ENUM, nullable=True, index=True
    )

    # -- Lease -----------------------------------------------------------
    claimed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # Counts attempts that were *given out*, not attempts that succeeded. A job
    # reclaimed three times has been attempted three times, however far each got.
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: Why a job stopped without a run outcome: lease exhaustion, or an operator
    #: cancelling it. Free text, because it is read by people rather than
    #: branched on by code.
    failure_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)

    sample_sha256: Mapped[str] = mapped_column(
        String(SHA256_LENGTH),
        ForeignKey("samples.sha256", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    sample: Mapped[Sample] = relationship(back_populates="jobs", lazy="joined")

    # -- Lifecycle -------------------------------------------------------

    @property
    def lease_expired(self) -> bool:
        """Whether ownership of this job has lapsed.

        A job with no lease has not lapsed; it is simply not held by anyone.
        """
        if self.lease_expires_at is None:
            return False
        return self.lease_expires_at <= _utc_now()

    def transition_to(
        self,
        target: JobStatus,
        *,
        run_outcome: RunOutcome | None = None,
        failure_reason: str | None = None,
    ) -> None:
        """Move to ``target``, or raise and change nothing.

        Validation runs first and mutation second, so a rejected transition
        leaves the object untouched and there is nothing for a later flush to
        persist. That ordering is the entire safety property.
        """
        validate_transition(self.status, target, run_outcome=run_outcome)

        now = _utc_now()
        if target is JobStatus.RUNNING:
            self.started_at = now
        elif target is JobStatus.FINISHED:
            self.finished_at = now
            self.run_outcome = run_outcome
            self.release_lease()
        elif target is JobStatus.CANCELLED:
            self.finished_at = now
            self.release_lease()
        elif target is JobStatus.QUEUED:
            # Returning to the queue drops ownership and the timestamps of the
            # attempt that failed. ``attempts`` deliberately survives, because
            # it is the record of how many times this has happened.
            self.release_lease()
            self.started_at = None

        if failure_reason is not None:
            self.failure_reason = failure_reason

        self.status = target

    def grant_lease(self, worker_id: str, lease_seconds: int) -> None:
        """Record that ``worker_id`` owns this job for the next ``lease_seconds``."""
        now = _utc_now()
        self.claimed_by = worker_id
        self.claimed_at = now
        self.lease_expires_at = now + timedelta(seconds=lease_seconds)

    def release_lease(self) -> None:
        """Drop ownership. Safe to call on a job nobody holds."""
        self.claimed_by = None
        self.claimed_at = None
        self.lease_expires_at = None

    def __repr__(self) -> str:
        return f"<Job id={self.id} status={self.status.value} file={self.original_filename!r}>"
