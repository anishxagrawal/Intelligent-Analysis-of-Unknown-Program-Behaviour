"""Application factory and process wiring.

``create_app`` takes settings rather than reading the cached global, so the test
suite can build an application around a throwaway database and a temporary
storage root without touching process-wide state.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from app.api.errors import register_error_handlers
from app.api.routes import health, jobs, samples, submissions
from app.config import Settings, get_settings
from app.db.base import Base
from app.db.session import create_engine, create_sessionmaker
from app.logging import configure_logging, get_logger, set_request_id
from app.storage.factory import build_storage
from app.version import APP_VERSION

logger = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a configured application instance."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)

        # Tables are created directly in v1. Alembic replaces this in v3, at
        # which point schema changes become migrations rather than a side
        # effect of starting the process.
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        settings.storage_root.mkdir(parents=True, exist_ok=True)

        app.state.settings = settings
        app.state.engine = engine
        app.state.sessionmaker = create_sessionmaker(engine)
        app.state.storage = build_storage(settings)

        logger.info("application started", extra={"environment": settings.environment})
        try:
            yield
        finally:
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
