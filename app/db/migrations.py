"""Running Alembic from Python.

The command line is the normal way to apply migrations. This module exists for
the two callers that cannot use it: the test suite, which builds a throwaway
database per run, and any future task that wants to bring a database up to date
as part of starting.

Alembic's API is synchronous, and ``env.py`` starts its own event loop. Calling
it from inside a running loop therefore fails, which is why
:func:`upgrade_database` hands the work to a thread - a thread with no loop of
its own, where ``asyncio.run`` is legal again.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config

#: Repository root: app/db/migrations.py -> app/db -> app -> root.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"
SCRIPT_LOCATION = PROJECT_ROOT / "alembic"


def alembic_config(url: str | None = None) -> Config:
    """Build an Alembic config pointing at this repository.

    ``script_location`` is set to an absolute path so migrations work from any
    working directory, and the URL is passed through ``attributes`` rather than
    ``set_main_option`` because the latter runs values through ConfigParser
    interpolation, where a ``%`` in a password becomes a syntax error.
    """
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(SCRIPT_LOCATION))
    if url is not None:
        config.attributes["url"] = url
    return config


def upgrade_to_head(url: str | None = None) -> None:
    """Apply every outstanding migration. Blocking."""
    command.upgrade(alembic_config(url), "head")


def downgrade_to_base(url: str | None = None) -> None:
    """Undo every migration. Blocking, and destructive - tests only."""
    command.downgrade(alembic_config(url), "base")


async def upgrade_database(url: str | None = None) -> None:
    """Apply every outstanding migration from inside a running event loop."""
    await asyncio.to_thread(upgrade_to_head, url)
