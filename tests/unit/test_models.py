"""Job and Sample model defaults."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.domain.models import Job, Sample

pytestmark = pytest.mark.unit


def test_job_column_defaults_are_declared() -> None:
    """Defaults live on the column, so they apply at flush time."""
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


def test_job_repr_is_useful_in_logs() -> None:
    job = Job(id=uuid.uuid4(), status="queued", original_filename="a.bin")

    assert "a.bin" in repr(job)
    assert "queued" in repr(job)


def test_sample_is_keyed_by_content_hash() -> None:
    """Content addressing is the whole basis of deduplication."""
    assert Sample.__table__.primary_key.columns.keys() == ["sha256"]


def test_sample_size_uses_a_wide_integer() -> None:
    """A 32-bit column tops out at 2 GB, which is a limit worth not hitting."""
    assert "BIGINT" in str(Sample.__table__.c.size_bytes.type).upper()


def test_sample_repr_truncates_the_digest() -> None:
    sample = Sample(sha256="a" * 64, sha1="b" * 40, md5="c" * 32, size_bytes=10)

    assert "a" * 12 in repr(sample)
    assert "a" * 64 not in repr(sample)


def test_job_references_a_sample() -> None:
    assert Job.__table__.c.sample_sha256.nullable is False
    assert len(Job.__table__.c.sample_sha256.foreign_keys) == 1
