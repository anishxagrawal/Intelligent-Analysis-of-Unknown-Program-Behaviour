"""Liveness and readiness, including when the database is gone.

The interesting case is the failing one, and it is the reason these two
endpoints are separate. Liveness must stay green while the database is down -
otherwise an orchestrator restarts every healthy replica during a database
incident and turns a partial outage into a total one.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.integration


class BrokenSessionmaker:
    """A session factory that fails the way an unreachable database does."""

    def __call__(self) -> BrokenSessionmaker:
        return self

    async def __aenter__(self) -> BrokenSessionmaker:
        raise OSError("connection refused")

    async def __aexit__(self, *exc: object) -> None:  # pragma: no cover - never reached
        return None


async def test_liveness_reports_the_process_is_up(anonymous_client: AsyncClient) -> None:
    response = await anonymous_client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_readiness_passes_when_the_database_is_reachable(
    anonymous_client: AsyncClient,
) -> None:
    response = await anonymous_client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": response.json()["version"],
        "database": "ok",
    }


async def test_readiness_fails_when_the_database_is_unreachable(
    app: FastAPI, anonymous_client: AsyncClient
) -> None:
    app.state.sessionmaker = BrokenSessionmaker()

    response = await anonymous_client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["database"] == "unavailable"


async def test_liveness_stays_green_when_the_database_is_unreachable(
    app: FastAPI, anonymous_client: AsyncClient
) -> None:
    """The whole reason liveness and readiness are different endpoints."""
    app.state.sessionmaker = BrokenSessionmaker()

    assert (await anonymous_client.get("/healthz")).status_code == 200


async def test_probes_need_no_credential(anonymous_client: AsyncClient) -> None:
    """Probes run before any credential exists."""
    for path in ("/healthz", "/readyz"):
        assert (await anonymous_client.get(path)).status_code != 401


async def test_an_unready_response_is_json_not_a_problem_document(
    app: FastAPI, anonymous_client: AsyncClient
) -> None:
    """Being unready is an expected state, not an error being reported."""
    app.state.sessionmaker = BrokenSessionmaker()

    response = await anonymous_client.get("/readyz")

    assert response.headers["content-type"].startswith("application/json")


async def test_readiness_survives_being_asked_repeatedly(
    anonymous_client: AsyncClient,
) -> None:
    """It runs every few seconds forever; leaking a connection would show here."""
    for _ in range(10):
        assert (await anonymous_client.get("/readyz")).status_code == 200


async def test_a_fresh_app_is_ready(app: FastAPI) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (await client.get("/readyz")).json()["database"] == "ok"
