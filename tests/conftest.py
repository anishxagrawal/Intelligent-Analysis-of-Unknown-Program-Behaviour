"""Shared test fixtures.

Database strategy: one throwaway database per test session, created on the
server named by the settings, migrated to head, and dropped afterwards. Tables
are truncated between tests. A throwaway database means a crashed run cannot
poison the next one, and it means the suite never touches development data.

The schema comes from Alembic, not from ``create_all``. That is deliberate: it
means the migrations are exercised by every single test run, so a migration that
disagrees with the models is caught immediately rather than on the day someone
deploys.

Tests that need a database fail loudly when none is reachable rather than
skipping. A silently skipped test in a suite whose green result defines "done"
is worse than a failing one.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings, get_settings
from app.db.migrations import upgrade_database
from app.db.session import create_engine, create_sessionmaker

SETUP_HINT = (
    "Could not reach PostgreSQL at {url}.\n"
    "Integration tests need a running server.\n"
    "  1. psql -U postgres -f scripts/setup-db.sql\n"
    "  2. copy .env.example to .env and set UPA_DATABASE_URL\n"
    "See README.md for details."
)


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    """Ensure no test inherits settings cached by an earlier one."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def base_settings() -> Settings:
    """Settings as configured on this machine, read from the environment."""
    return Settings()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_database_url(base_settings: Settings) -> AsyncIterator[str]:
    """Create a throwaway database for this run, and drop it at the end."""
    admin_url = make_url(base_settings.test_database_url or base_settings.database_url)
    db_name = f"upa_test_{uuid.uuid4().hex[:12]}"

    # CREATE DATABASE cannot run inside a transaction block.
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as conn:
            await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    except Exception as exc:  # pragma: no cover - only hit when misconfigured
        await admin_engine.dispose()
        pytest.fail(
            SETUP_HINT.format(url=admin_url.render_as_string(hide_password=True))
            + f"\n\nUnderlying error: {type(exc).__name__}: {exc}"
        )

    try:
        # render_as_string(hide_password=False) is required: str(URL) masks the
        # password as "***", which produces a URL that cannot authenticate.
        url = admin_url.set(database=db_name).render_as_string(hide_password=False)
        await upgrade_database(url)
        yield url
    finally:
        async with admin_engine.connect() as conn:
            # Terminate stragglers so DROP cannot block on a lingering session.
            await conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": db_name},
            )
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
        await admin_engine.dispose()


@pytest.fixture
def settings(test_database_url: str, tmp_path: Path) -> Settings:
    """Settings pointing at the throwaway database and a temporary storage root."""
    return Settings(
        environment="test",
        database_url=test_database_url,
        storage_root=tmp_path / "samples",
    )


@pytest.fixture
def sample_bytes() -> bytes:
    """A small, fixed payload. Not a real executable - v1 does not inspect content."""
    return b"MZ\x90\x00 not a real program, just bytes for the walking skeleton\n"


@pytest_asyncio.fixture
async def app(settings: Settings) -> AsyncIterator[FastAPI]:
    """A running application bound to the throwaway database.

    The lifespan is entered explicitly because httpx's ASGI transport does not
    run it, and without it the engine and session factory would never be built.
    """
    from app.main import create_app

    application = create_app(settings)
    async with application.router.lifespan_context(application):
        await truncate_all_tables(application.state.engine)
        yield application


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """An HTTP client speaking directly to the app, with no network involved."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client


@pytest_asyncio.fixture
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    """An engine on the throwaway database, for tests that do not need the API.

    Separate from the ``app`` fixture on purpose. The queue is exercised
    directly by workers and the reaper, neither of which goes anywhere near
    HTTP, and testing it through the API would only obscure what is being
    tested.
    """
    db_engine = create_engine(settings)
    await truncate_all_tables(db_engine)
    try:
        yield db_engine
    finally:
        await db_engine.dispose()


@pytest_asyncio.fixture
async def sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """A session factory on the throwaway database.

    Handed out as a factory rather than a session because the concurrency tests
    need several sessions at once - one shared session would serialise the very
    contention they exist to create.
    """
    return create_sessionmaker(engine)


@pytest_asyncio.fixture
async def session(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """One session for tests that only need one."""
    async with sessionmaker() as db_session:
        yield db_session


async def truncate_all_tables(engine: AsyncEngine) -> None:
    """Empty every table so each test starts from a known state.

    Truncation is far simpler than savepoint-based rollback and fast enough at
    this scale. RESTART IDENTITY resets sequences; CASCADE handles the foreign
    key from jobs to samples.
    """
    from app.db.base import Base

    table_names = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    if not table_names:
        return

    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))
