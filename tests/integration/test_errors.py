"""AC-V1b: errors have one consistent, machine-readable shape.

RFC 7807 problem details. Deciding this once, before the API grows, is far
cheaper than retrofitting a consistent error format across many routes later.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

PROBLEM_JSON = "application/problem+json"


async def test_unknown_route_returns_problem_json(client) -> None:  # type: ignore[no-untyped-def]
    response = await client.get("/no-such-route")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith(PROBLEM_JSON)

    body = response.json()
    assert body["status"] == 404
    assert body["title"]
    assert body["type"]


async def test_problem_response_carries_the_request_id(client) -> None:  # type: ignore[no-untyped-def]
    response = await client.get("/no-such-route", headers={"X-Request-ID": "trace-me"})

    assert response.json()["request_id"] == "trace-me"


async def test_validation_failure_returns_problem_json(client) -> None:  # type: ignore[no-untyped-def]
    """A malformed uuid in the path is a validation failure, not a crash."""
    response = await client.get("/api/v1/jobs/not-a-uuid")

    assert response.status_code == 422
    assert response.headers["content-type"].startswith(PROBLEM_JSON)

    body = response.json()
    assert body["status"] == 422
    assert body["errors"]
