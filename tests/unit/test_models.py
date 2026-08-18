"""Job model defaults."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.domain.models import Job

pytestmark = pytest.mark.unit


def test_defaults_are_applied_on_insert() -> None:
    """Defaults are declared on the column, so they apply at flush time."""
    job = Job(original_filename="a.bin", size_bytes=1)

    assert job.id is None
    assert Job.__table__.c.id.default is not None
    assert Job.__table__.c.status.default.arg == "queued"


def test_created_at_default_is_timezone_aware_utc() -> None:
    generated = Job.__table__.c.created_at.default.arg({})

    assert isinstance(generated, datetime)
    assert generated.tzinfo is not None
    assert generated.utcoffset() == UTC.utcoffset(None)


def test_id_default_generates_unique_uuids() -> None:
    factory = Job.__table__.c.id.default.arg

    first, second = factory({}), factory({})

    assert isinstance(first, uuid.UUID)
    assert first != second


def test_repr_is_useful_in_logs() -> None:
    job = Job(id=uuid.uuid4(), status="queued", original_filename="a.bin", size_bytes=1)

    assert "a.bin" in repr(job)
    assert "queued" in repr(job)
