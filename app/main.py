"""Application factory and process wiring.

``create_app`` takes settings rather than reading the cached global, so the test
suite can build an application around a throwaway database and a temporary
storage root without touching process-wide state.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import register_error_handlers
from app.api.routes import health, jobs, samples, submissions
from app.config import Settings, get_settings
from app.db.session import create_engine, create_sessionmaker
from app.logging import configure_logging, get_logger, set_request_id
from app.queue.database import DatabaseJobQueue
from app.queue.reaper import Reaper
from app.security.audit import AuditLog
from app.security.provisioning import ensure_bootstrap_key
from app.security.ratelimit import TokenBucketRateLimiter
from app.storage.factory import build_storage
from app.version import APP_VERSION

logger = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


async def _stop_reaper(
    task: asyncio.Task[None] | None, session: AsyncSession | None
) -> None:
    """Cancel the reaper, wait for it to stop, then release its session.

    The waiting matters. A cancelled task that is never awaited can still be
    mid-statement when the engine is disposed, which turns a clean shutdown into
    a warning nobody can reproduce.
    """
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    if session is not None:
        await session.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a configured application instance."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)

        # The schema is not created here. v1 and v2 called
        # ``Base.metadata.create_all`` at startup; v3 replaces it with Alembic.
        #
        # The reason is not tidiness. ``create_all`` creates missing tables and
        # ignores existing ones entirely, so a column added in code never
        # reaches a database that already has that table - quietly, with no
        # error, until something reads the column in production. Migrations are
        # an explicit, ordered, reviewable record instead.
        #
        # Run `alembic upgrade head` before starting. See README.md.
        settings.storage_root.mkdir(parents=True, exist_ok=True)

        sessionmaker = create_sessionmaker(engine)

        app.state.settings = settings
        app.state.engine = engine
        app.state.sessionmaker = sessionmaker
        app.state.storage = build_storage(settings)
        app.state.audit = AuditLog(sessionmaker)
        app.state.rate_limiter = TokenBucketRateLimiter(
            rate_per_minute=settings.rate_limit_per_minute,
            burst=settings.rate_limit_burst,
        )

        if settings.bootstrap_api_key:
            await ensure_bootstrap_key(sessionmaker, settings.bootstrap_api_key)

        # The reaper runs beside the API rather than as its own service. Two
        # reapers sweeping the same table is harmless - every update is guarded
        # by the state it expects to find - so one per instance needs no
        # coordination, and it removes the failure mode where a separate process
        # is simply forgotten and abandoned jobs pile up unnoticed.
        #
        # One session for the life of the process, not one per sweep. Each sweep
        # commits, so the next begins a new transaction and sees current data;
        # a session per sweep would only add connection churn to a loop that
        # runs forever.
        app.state.reaper_task = None
        app.state.reaper_session = None
        if settings.run_reaper:
            reaper_session = sessionmaker()
            app.state.reaper_session = reaper_session
            reaper = Reaper(
                queue=DatabaseJobQueue(reaper_session),
                max_attempts=settings.job_max_attempts,
                interval_seconds=settings.reaper_interval_seconds,
            )
            app.state.reaper_task = asyncio.create_task(reaper.run_forever())

        logger.info("application started", extra={"environment": settings.environment})
        try:
            yield
        finally:
            await _stop_reaper(app.state.reaper_task, app.state.reaper_session)
            await engine.dispose()
            logger.info("application stopped")

    app = FastAPI(
        title="Intelligent Analysis of Unknown Program Behaviour",
        description="Stage 1: Input and Submission.",
        version=APP_VERSION,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def request_id_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Bind a correlation id to the request and echo it on the response.

        An id supplied by the caller is honoured, so a request crossing several
        services keeps one identifier. Otherwise one is generated.
        """
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        set_request_id(request_id)
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        finally:
            set_request_id(None)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

    register_error_handlers(app)

    app.include_router(health.router)
    app.include_router(jobs.router, prefix=settings.api_prefix)
    app.include_router(samples.router, prefix=settings.api_prefix)
    app.include_router(submissions.router, prefix=settings.api_prefix)

    return app


app = create_app()
