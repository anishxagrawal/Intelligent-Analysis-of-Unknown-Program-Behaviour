"""ORM models.

Two tables. The split matters: a *sample* is content, a *job* is a request to
analyse it. Submitting the same file twice creates two jobs referring to one
sample, which is what allows storage to be deduplicated while still recording
that the file was seen again.

Later versions extend this:
  v3 replaces the plain ``status`` string with an enum, and adds the five
     terminal run outcomes the rest of the project depends on.
  v4 adds the detected file type to Sample.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

SHA256_LENGTH = 64
SHA1_LENGTH = 40
MD5_LENGTH = 32


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
    """

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)

    sample_sha256: Mapped[str] = mapped_column(
        String(SHA256_LENGTH),
        ForeignKey("samples.sha256", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    sample: Mapped[Sample] = relationship(back_populates="jobs", lazy="joined")

    def __repr__(self) -> str:
        return f"<Job id={self.id} status={self.status} file={self.original_filename!r}>"
