"""Authentication, authorisation, rate limiting and the audit trail, over HTTP.

These tests use ``anonymous_client`` and mint their own keys, so the guarantees
are proved rather than inherited from the shared authenticated fixture.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.models import ApiKey, AuditEvent
from app.security import audit as events
from app.security.keys import generate_key
from app.security.scopes import Scope

pytestmark = pytest.mark.integration

SUBMISSIONS = "/api/v1/submissions"


async def issue_key(
    sessionmaker: async_sessionmaker[AsyncSession],
    *scopes: Scope,
    disabled: bool = False,
) -> str:
    """Create a key with exactly the scopes given, and return its plaintext."""
    from datetime import UTC, datetime

    issued = generate_key()
    async with sessionmaker() as session:
        session.add(
            ApiKey(
                name="test",
                token_hash=issued.token_hash,
                scopes=[scope.value for scope in scopes],
                disabled_at=datetime.now(UTC) if disabled else None,
            )
        )
        await session.commit()
    return issued.token


async def submit(client: AsyncClient, key: str | None = None) -> object:
    headers = {"X-API-Key": key} if key else {}
    return await client.post(
        SUBMISSIONS,
        files={"file": ("sample.bin", b"MZ\x90\x00 bytes", "application/octet-stream")},
        headers=headers,
    )


async def count_events(
    sessionmaker: async_sessionmaker[AsyncSession], event: str
) -> int:
    async with sessionmaker() as session:
        return await session.scalar(
            select(func.count()).select_from(AuditEvent).where(AuditEvent.event == event)
        ) or 0


# -- 401 -------------------------------------------------------------------


async def test_a_missing_key_is_refused(anonymous_client: AsyncClient) -> None:
    """AC-10."""
    response = await submit(anonymous_client)

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_a_bad_key_is_refused(anonymous_client: AsyncClient) -> None:
    """AC-10."""
    response = await submit(anonymous_client, "upa_not_a_real_key")

    assert response.status_code == 401


async def test_a_disabled_key_is_refused(
    anonymous_client: AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """Revocation has to take effect immediately, not at the next restart."""
    key = await issue_key(sessionmaker, Scope.SUBMISSIONS_WRITE, disabled=True)

    assert (await submit(anonymous_client, key)).status_code == 401


async def test_unknown_and_disabled_keys_are_indistinguishable(
    anonymous_client: AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """Telling them apart would confirm that a particular key exists."""
    disabled = await issue_key(sessionmaker, Scope.SUBMISSIONS_WRITE, disabled=True)

    unknown_body = (await submit(anonymous_client, "upa_nonsense")).json()
    disabled_body = (await submit(anonymous_client, disabled)).json()

    assert unknown_body["detail"] == disabled_body["detail"]
    assert unknown_body["title"] == disabled_body["title"]


async def test_a_refusal_never_echoes_the_key(anonymous_client: AsyncClient) -> None:
    presented = "upa_secret_value_that_must_not_come_back"

    body = (await submit(anonymous_client, presented)).text

    assert presented not in body


# -- 403 -------------------------------------------------------------------


async def test_a_valid_key_with_the_wrong_scope_is_forbidden(
    anonymous_client: AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """AC-11. Authenticated, so 403 and not 401: the caller is known, just not allowed."""
    key = await issue_key(sessionmaker, Scope.JOBS_READ)

    response = await submit(anonymous_client, key)

    assert response.status_code == 403
    assert "submissions:write" in response.json()["detail"]


async def test_the_right_scope_is_admitted(
    anonymous_client: AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    key = await issue_key(sessionmaker, Scope.SUBMISSIONS_WRITE)

    assert (await submit(anonymous_client, key)).status_code == 202


async def test_reading_a_job_needs_its_own_scope(
    anonymous_client: AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """A submitter that cannot read is a normal and useful configuration."""
    writer = await issue_key(sessionmaker, Scope.SUBMISSIONS_WRITE)
    job_id = (await submit(anonymous_client, writer)).json()["job_id"]

    response = await anonymous_client.get(
        f"/api/v1/jobs/{job_id}", headers={"X-API-Key": writer}
    )

    assert response.status_code == 403


# -- 429 -------------------------------------------------------------------


async def test_exceeding_the_rate_limit_returns_429(
    settings, clean_database: None
) -> None:
    """AC-12."""
    from httpx import ASGITransport

    from app.main import create_app

    limited = settings.model_copy(update={"rate_limit_per_minute": 60, "rate_limit_burst": 2})
    application = create_app(limited)

    async with application.router.lifespan_context(application):
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            key = await issue_key(application.state.sessionmaker, Scope.SUBMISSIONS_WRITE)

            statuses = [(await submit(client, key)).status_code for _ in range(4)]

    assert statuses[:2] == [202, 202]
    assert 429 in statuses[2:]


async def test_a_429_says_how_long_to_wait(settings, clean_database: None) -> None:
    """A caller told exactly how long to wait stops making the problem worse."""
    from httpx import ASGITransport

    from app.main import create_app

    limited = settings.model_copy(update={"rate_limit_per_minute": 60, "rate_limit_burst": 1})
    application = create_app(limited)

    async with application.router.lifespan_context(application):
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            key = await issue_key(application.state.sessionmaker, Scope.SUBMISSIONS_WRITE)
            await submit(client, key)
            response = await submit(client, key)

    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) >= 1


async def test_limits_apply_per_key(settings, clean_database: None) -> None:
    """One noisy client must not throttle everybody else."""
    from httpx import ASGITransport

    from app.main import create_app

    limited = settings.model_copy(update={"rate_limit_per_minute": 60, "rate_limit_burst": 1})
    application = create_app(limited)

    async with application.router.lifespan_context(application):
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            noisy = await issue_key(application.state.sessionmaker, Scope.SUBMISSIONS_WRITE)
            quiet = await issue_key(application.state.sessionmaker, Scope.SUBMISSIONS_WRITE)

            await submit(client, noisy)
            throttled = await submit(client, noisy)
            other = await submit(client, quiet)

    assert throttled.status_code == 429
    assert other.status_code == 202


# -- Audit -----------------------------------------------------------------


async def test_every_submission_is_audited(
    client: AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """AC-19, the success half."""
    await submit(client)

    assert await count_events(sessionmaker, events.SUBMISSION_ACCEPTED) == 1


async def test_every_auth_failure_is_audited(
    anonymous_client: AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """AC-19, the half that matters more."""
    await submit(anonymous_client)
    await submit(anonymous_client, "upa_wrong")

    assert await count_events(sessionmaker, events.AUTH_FAILED) == 2


async def test_a_scope_refusal_is_audited(
    anonymous_client: AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """The pattern worth finding: a key repeatedly reaching past its permissions."""
    key = await issue_key(sessionmaker, Scope.JOBS_READ)

    await submit(anonymous_client, key)

    assert await count_events(sessionmaker, events.AUTH_DENIED) == 1


async def test_an_audit_row_identifies_the_request(
    client: AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """So an audit row and the log lines for the same request can be lined up."""
    await client.post(
        SUBMISSIONS,
        files={"file": ("sample.bin", b"MZ bytes", "application/octet-stream")},
        headers={"X-Request-ID": "known-request-id"},
    )

    async with sessionmaker() as session:
        entry = await session.scalar(
            select(AuditEvent).where(AuditEvent.event == events.SUBMISSION_ACCEPTED)
        )

    assert entry is not None
    assert entry.request_id == "known-request-id"
    assert entry.method == "POST"
    assert entry.path == SUBMISSIONS
    assert entry.api_key_id is not None


async def test_an_audit_row_never_carries_the_credential(
    anonymous_client: AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """A rejected key must not be recoverable from the trail meant to police it."""
    presented = "upa_a_key_that_must_not_be_stored"

    await submit(anonymous_client, presented)

    async with sessionmaker() as session:
        details = list(await session.scalars(select(AuditEvent.detail)))

    assert all(presented not in (detail or "") for detail in details)


async def test_the_audit_trail_survives_the_request_that_failed(
    anonymous_client: AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """Audit rows are written on their own session, so a rollback cannot take them."""
    await submit(anonymous_client, "upa_wrong")

    async with sessionmaker() as session:
        stored = await session.scalar(select(func.count()).select_from(AuditEvent))

    assert stored == 1


async def test_a_successful_call_updates_last_used(
    client: AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """An unused key is one that can be retired; the trail has to show that."""
    await submit(client)

    async with sessionmaker() as session:
        key = await session.scalar(select(ApiKey).where(ApiKey.name == "bootstrap"))

    assert key is not None
    assert key.last_used_at is not None


async def test_an_unknown_job_still_requires_a_key(anonymous_client: AsyncClient) -> None:
    """Authentication runs before existence, so a 404 cannot be used to probe."""
    response = await anonymous_client.get(f"/api/v1/jobs/{uuid.uuid4()}")

    assert response.status_code == 401
