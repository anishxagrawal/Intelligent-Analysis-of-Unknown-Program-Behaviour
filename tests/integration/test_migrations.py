"""Migrations, and whether they still agree with the models.

The whole test suite runs against a database built by Alembic, so a migration
that fails outright is caught everywhere at once. What that does *not* catch is
drift: a column added to a model and forgotten in a migration, where the models
and the database quietly describe different schemas and nothing complains until
a query touches the missing column in production.

The comparison below is what catches it, and it is the reason to have migrations
at all rather than ``create_all``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.base import Base
from app.db.migrations import ALEMBIC_INI, alembic_config
from app.domain.enums import JobStatus, RunOutcome

pytestmark = pytest.mark.integration


def test_the_alembic_configuration_is_findable_from_any_directory() -> None:
    """Paths are absolute, so migrations do not depend on the shell's cwd."""
    assert ALEMBIC_INI.is_file()
    assert alembic_config().get_main_option("script_location").endswith("alembic")


async def test_the_migrated_schema_has_every_table(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        tables = await conn.run_sync(lambda sync: set(inspect(sync).get_table_names()))

    assert {table.name for table in Base.metadata.sorted_tables} <= tables
    assert "alembic_version" in tables, "the applied revision must be recorded"


async def test_every_model_column_exists_in_the_database(engine: AsyncEngine) -> None:
    """Catches a model change that never became a migration."""

    def columns_of(sync_conn: object, table: str) -> set[str]:
        return {column["name"] for column in inspect(sync_conn).get_columns(table)}

    async with engine.connect() as conn:
        for table in Base.metadata.sorted_tables:
            actual = await conn.run_sync(columns_of, table.name)
            expected = {column.name for column in table.columns}

            assert expected <= actual, f"{table.name} is missing {sorted(expected - actual)}"
            assert actual <= expected, f"{table.name} has stray {sorted(actual - expected)}"


async def test_the_database_enforces_the_status_vocabulary(engine: AsyncEngine) -> None:
    """AC-13. The five outcomes exist in the schema, not only in Python.

    A native enum means a bad value is refused by PostgreSQL rather than by
    whichever application code happened to look.
    """
    async with engine.connect() as conn:
        enums = await conn.run_sync(lambda sync: inspect(sync).get_enums())

    by_name = {enum["name"]: set(enum["labels"]) for enum in enums}

    assert by_name["job_status"] == {status.value for status in JobStatus}
    assert by_name["run_outcome"] == {outcome.value for outcome in RunOutcome}


async def test_the_reaper_query_is_indexed(engine: AsyncEngine) -> None:
    """It runs on a timer forever; a full scan every sweep would not stay cheap."""
    async with engine.connect() as conn:
        indexes = await conn.run_sync(lambda sync: inspect(sync).get_indexes("jobs"))

    indexed = {tuple(index["column_names"]) for index in indexes}

    assert ("lease_expires_at",) in indexed
    assert ("status",) in indexed
