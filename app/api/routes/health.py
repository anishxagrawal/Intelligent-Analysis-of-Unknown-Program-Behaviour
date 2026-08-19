"""Liveness and readiness.

Two endpoints because they answer two questions, and an orchestrator does
opposite things with the answers.

``/healthz`` asks *is this process alive*. It touches nothing external, and it
must not: a liveness probe that fails when the database is unreachable causes
the orchestrator to kill and restart every replica of a healthy service during a
database incident, turning a partial outage into a total one.

``/readyz`` asks *can this process serve traffic*. It checks the database,
because a process that cannot reach its database can accept a request and do
nothing useful with it. Failing readiness takes the instance out of the load
balancer and leaves it running, which is the correct response.

Neither requires authentication. Probes run before any credential exists, and
neither reveals anything a caller could not learn by sending a request.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from app.version import APP_VERSION

logger = get_logger(__name__)

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    version: str


class ReadinessResponse(BaseModel):
    status: str
    version: str
    database: str


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    """Report that the process is alive. Checks nothing else, on purpose."""
    return HealthResponse(status="ok", version=APP_VERSION)


@router.get(
    "/readyz",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse}},
)
async def readyz(request: Request, response: Response) -> ReadinessResponse:
    """Report whether this process can actually serve traffic.

    The session is acquired by hand rather than through ``Depends``: a
    dependency that raises produces a 500 from the error handler, and a
    readiness probe has to answer 503 with a body describing what is wrong.
    Being unready is an expected state, not an error.
    """
    database = "ok"

    try:
        sessionmaker = request.app.state.sessionmaker
        async with sessionmaker() as session:
            await _ping(session)
    except Exception as exc:
        logger.warning("readiness check failed", extra={"error": str(exc)})
        database = "unavailable"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(
        status="ok" if database == "ok" else "unavailable",
        version=APP_VERSION,
        database=database,
    )


async def _ping(session: AsyncSession) -> None:
    """The cheapest statement that proves a connection actually works.

    Cheap on purpose: this runs every few seconds, forever, on every instance,
    and a readiness probe that costs anything real becomes its own load problem.
    """
    await session.execute(text("SELECT 1"))
