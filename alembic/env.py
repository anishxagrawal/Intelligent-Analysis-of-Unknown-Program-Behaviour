"""Alembic environment.

v3 replaces ``Base.metadata.create_all`` with migrations. The difference that
matters is not the first run - both produce the same tables - but every run
after it. ``create_all`` adds tables that do not exist and silently ignores
tables that have changed, so a column added in code simply never appears in a
database that already has the table. That failure is quiet, and it is discovered
in production.

The URL comes from application settings rather than from ``alembic.ini`` so
there is exactly one place a database is named. Tests override it through
``config.attributes["url"]``, which avoids ``ConfigParser`` interpolation
mangling any ``%`` in a password.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import get_settings
from app.db.base import Base

# Imported for the side effect of registering every model on Base.metadata.
# Without it autogenerate compares against an empty schema and proposes
# dropping the entire database.
import app.domain.models  # noqa: F401  isort:skip

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    """The database these migrations run against."""
    override = config.attributes.get("url")
    if override:
        return str(override)
    return get_settings().database_url


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it.

    Useful when a database is changed by someone who is not allowed to run the
    application, which is a normal arrangement in production.
    """
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations against a live database over the async driver."""
    engine = async_engine_from_config(
        {"sqlalchemy.url": _database_url()},
        prefix="sqlalchemy.",
        poolclass=None,
    )
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
