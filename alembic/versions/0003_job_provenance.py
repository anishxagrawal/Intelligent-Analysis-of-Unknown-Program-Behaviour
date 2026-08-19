"""Provenance stamp on jobs.

Existing rows are backfilled with ``0.0.0`` rather than with the current
versions. Stamping them with today's numbers would assert that this code
created them, which is false for every row that already exists - and provenance
that lies is worse than provenance that admits it does not know.

Revision ID: 0003
Revises: 0002
Created: v5
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Reserved to mean "created before provenance was recorded".
UNKNOWN_VERSION = "0.0.0"

COLUMNS = ("app_version", "schema_version", "config_version")


def upgrade() -> None:
    for column in COLUMNS:
        # server_default fills existing rows and is then dropped: the
        # application always supplies a value, and a default left in place would
        # let a future insert silently omit one and still look stamped.
        op.add_column(
            "jobs",
            sa.Column(
                column,
                sa.String(length=32),
                nullable=False,
                server_default=UNKNOWN_VERSION,
            ),
        )
        op.alter_column("jobs", column, server_default=None)


def downgrade() -> None:
    for column in reversed(COLUMNS):
        op.drop_column("jobs", column)
