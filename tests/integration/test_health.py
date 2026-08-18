"""AC-V1c and AC-V1d: the app starts, answers, and correlates requests.

This is the first test written in v1 and the first to go green. If FastAPI,
async SQLAlchemy, asyncpg or the ASGI transport are going to cause trouble, it
surfaces here, where nothing else could be at fault.
"""

from __future__ import annotations

import pytest

from app.version import APP_VERSION

pytestmark = pytest.mark.integration


async def test_healthz_returns_200(client) -> None:  # type: ignore[no-untyped-def]
    response = await client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == APP_VERSION


async def test_response_carries_a_request_id(client) -> None:  # type: ignore[no-untyped-def]
    response = await client.get("/healthz")

    request_id = response.headers.get("X-Request-ID")
    assert request_id
    assert len(request_id) > 8


async def test_incoming_request_id_is_echoed(client) -> None:  # type: ignore[no-untyped-def]
    response = await client.get("/healthz", headers={"X-Request-ID": "caller-supplied-id"})

    assert response.headers["X-Request-ID"] == "caller-supplied-id"


async def test_each_request_gets_a_distinct_id(client) -> None:  # type: ignore[no-untyped-def]
    first = await client.get("/healthz")
    second = await client.get("/healthz")

    assert first.headers["X-Request-ID"] != second.headers["X-Request-ID"]
