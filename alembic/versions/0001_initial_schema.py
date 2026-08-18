"""Initial schema: samples, jobs, and the job lifecycle enums.

One migration rather than three. v1 and v2 created their tables with
``create_all``, so no database anywhere was built by a migration and there is no
history to preserve. Reconstructing an imagined sequence of earlier migrations
would be fiction, and fiction that later readers would trust.

Revision ID: 0001
Revises:
Created: v3
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SHA256_LENGTH = 64
SHA1_LENGTH = 40
MD5_LENGTH = 32

# Native PostgreSQL enum types. Declared with create_type=False so that the
# CREATE TYPE below is the only thing that creates them; left to itself,
# create_table would try as well and the second attempt would fail.
JOB_STATUS = postgresql.ENUM(
    "queued",
    "claimed",
    "running",
    "finished",
    "cancelled",
    name="job_status",
    create_type=False,
)
RUN_OUTCOME = postgresql.ENUM(
    "completed",
    "timed_out",
    "crashed_on_launch",
    "no_activity_observed",
    "evasion_suspected",
    name="run_outcome",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    JOB_STATUS.create(bind, checkfirst=True)
    RUN_OUTCOME.create(bind, checkfirst=True)

    op.create_table(
        "samples",
        sa.Column("sha256", sa.String(length=SHA256_LENGTH), nullable=False),
        sa.Column("sha1", sa.String(length=SHA1_LENGTH), nullable=False),
        sa.Column("md5", sa.String(length=MD5_LENGTH), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("sha256", name="pk_samples"),
    )
    op.create_index("ix_samples_sha1", "samples", ["sha1"])
    op.create_index("ix_samples_md5", "samples", ["md5"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", JOB_STATUS, nullable=False),
        sa.Column("original_filename", sa.String(length=512), nullable=False),
        sa.Column("run_outcome", RUN_OUTCOME, nullable=True),
        sa.Column("claimed_by", sa.String(length=128), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.String(length=512), nullable=True),
        sa.Column("sample_sha256", sa.String(length=SHA256_LENGTH), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_jobs"),
        # RESTRICT rather than CASCADE: deleting a sample that jobs still refer
        # to should fail loudly, not quietly erase the record that it was ever
        # submitted.
        sa.ForeignKeyConstraint(
            ["sample_sha256"],
            ["samples.sha256"],
            name="fk_jobs_sample_sha256_samples",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_jobs_sample_sha256", "jobs", ["sample_sha256"])
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_run_outcome", "jobs", ["run_outcome"])

    # The reaper's query is exactly this pair of columns, and it runs on a timer
    # forever. An index costs one write per claim and saves a full scan of the
    # jobs table on every sweep.
    op.create_index("ix_jobs_lease_expires_at", "jobs", ["lease_expires_at"])


def downgrade() -> None:
    op.drop_index("ix_jobs_lease_expires_at", table_name="jobs")
    op.drop_index("ix_jobs_run_outcome", table_name="jobs")
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_index("ix_jobs_sample_sha256", table_name="jobs")
    op.drop_table("jobs")

    op.drop_index("ix_samples_md5", table_name="samples")
    op.drop_index("ix_samples_sha1", table_name="samples")
    op.drop_table("samples")

    bind = op.get_bind()
    RUN_OUTCOME.drop(bind, checkfirst=True)
    JOB_STATUS.drop(bind, checkfirst=True)
