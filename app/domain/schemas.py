"""Request and response models.

These are the API's contract, kept separate from the ORM models so that a
database change does not silently alter what clients receive.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class JobRead(BaseModel):
    """A job as returned to clients."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    status: str
    original_filename: str
    size_bytes: int


class SubmissionAccepted(BaseModel):
    """Acknowledgement that a submission was accepted for analysis.

    202 rather than 201: the job has been queued, not completed. Nothing has
    been analysed at the point this is returned.
    """

    job_id: uuid.UUID = Field(description="Identifier for polling job status.")
    status: str = Field(description="Lifecycle state at the moment of acceptance.")
