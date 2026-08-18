"""File type on samples, plus API keys and the audit trail.

Existing samples are backfilled as ``unknown`` rather than re-detected. The
bytes are still there and could be read again, but a value written by a
detection that never ran is exactly the kind of quiet fiction this project
argues against. ``unknown`` is true: nothing has looked at them.

Revision ID: 0002
Revises: 0001
Created: v4
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FILE_TYPE = postgresql.ENUM(
    "pe",
    "elf",
    "mach_o",
    "script",
    "ole",
    "ooxml",
    "archive",
    "pdf",
    "unknown",
    name="file_type",
    create_type=False,
)


def upgrade() -> None:
    FILE_TYPE.create(op.get_bind(), checkfirst=True)

    # server_default fills existing rows, and is then dropped: the application
    # always supplies a value, and leaving a default in place would let a future
    # insert silently omit one.
    op.add_column(
        "samples",
        sa.Column("file_type", FILE_TYPE, nullable=False, server_default="unknown"),
    )
    op.alter_column("samples", "file_type", server_default=None)
    op.create_index("ix_samples_file_type", "samples", ["file_type"])

    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("scopes", sa.ARRAY(sa.String(length=64)), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_api_keys"),
    )
    # Unique: authentication is a lookup by this column, and two keys hashing
    # alike is a collision worth hearing about immediately.
    op.create_index("ix_api_keys_token_hash", "api_keys", ["token_hash"], unique=True)

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("api_key_id", sa.Uuid(), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("method", sa.String(length=8), nullable=True),
        sa.Column("path", sa.String(length=512), nullable=True),
        sa.Column("client_ip", sa.String(length=64), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
        # RESTRICT: a key referenced by the audit trail cannot be deleted, which
        # is the point. Keys are disabled, never removed.
        sa.ForeignKeyConstraint(
            ["api_key_id"],
            ["api_keys.id"],
            name="fk_audit_events_api_key_id_api_keys",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"])
    op.create_index("ix_audit_events_event", "audit_events", ["event"])
    op.create_index("ix_audit_events_outcome", "audit_events", ["outcome"])
    op.create_index("ix_audit_events_api_key_id", "audit_events", ["api_key_id"])
    op.create_index("ix_audit_events_request_id", "audit_events", ["request_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_request_id", table_name="audit_events")
    op.drop_index("ix_audit_events_api_key_id", table_name="audit_events")
    op.drop_index("ix_audit_events_outcome", table_name="audit_events")
    op.drop_index("ix_audit_events_event", table_name="audit_events")
    op.drop_index("ix_audit_events_occurred_at", table_name="audit_events")
    op.drop_table("audit_events")

    op.drop_index("ix_api_keys_token_hash", table_name="api_keys")
    op.drop_table("api_keys")

    op.drop_index("ix_samples_file_type", table_name="samples")
    op.drop_column("samples", "file_type")
    FILE_TYPE.drop(op.get_bind(), checkfirst=True)
