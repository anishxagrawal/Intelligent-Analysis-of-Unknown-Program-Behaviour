"""ORM models.

One table in v1. It grows in later versions:
  v2 adds a Sample table keyed by content hash, and Job gains a link to it.
  v3 replaces the plain ``status`` string with an enum, and adds the five
     terminal run outcomes that the rest of the project depends on.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utc_now() -> datetime:
    """Timezone-aware current time.

    Defaulted in Python rather than by the database so that behaviour is
    identical wherever a row is created - including in tests, which need to
    reason about ordering without depending on server clock configuration.
    """
    return datetime.now(UTC)


class Job(Base):
    """One analysis request for one submitted file.

    ``status`` is a plain string in v1 and becomes a real enum in v3, alongside
    the run-outcome states. There is deliberately no ``storage_path`` column:
    where the bytes live is an infrastructure concern, and recording it here
    would fight the storage protocol that v2 introduces. The path is derived
    from the job id instead.
    """

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    def __repr__(self) -> str:
        return f"<Job id={self.id} status={self.status} file={self.original_filename!r}>"
