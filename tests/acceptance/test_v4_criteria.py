"""AC-06, AC-07, AC-10, AC-11, AC-12 and AC-19: the v4 acceptance criteria.

One test per numbered requirement in ACCEPTANCE.md. Passing this file is what
makes v4 finished.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.models import AuditEvent
from app.security import audit as events
from app.security.scopes import Scope
from tests.integration.test_auth import issue_key

pytestmark = pytest.mark.acceptance


def pe_bytes() -> bytes:
    """A structurally honest minimal PE: DOS stub, e_lfanew, PE signature."""
    header = bytearray(b"MZ" + b"\x90" * 62)
    header[0x3C:0x40] = (64).to_bytes(4, "little")
    return bytes(header) + b"PE\x00\x00" + b"\x00" * 32


async def test_ac06_a_pe_renamed_to_txt_is_still_a_pe(client: AsyncClient) -> None:
    """AC-06. The extension is attacker-controlled text and is never consulted."""
    response = await client.post(
        "/api/v1/submissions",
        files={"file": ("harmless-notes.txt", pe_bytes(), "text/plain")},
    )

    assert response.status_code == 202
    assert response.json()["file_type"] == "pe"

    # And it stays that way on the record, not only in the acknowledgement.
    sample = await client.get(f"/api/v1/samples/{response.json()['sha256']}")
    assert sample.json()["file_type"] == "pe"


async def test_ac07_an_unrecognised_file_is_unknown_not_guessed(
    client: AsyncClient,
) -> None:
    """AC-07. "We do not know" is usable; a wrong answer looks like knowledge."""
    response = await client.post(
        "/api/v1/submissions",
        files={"file": ("mystery.dat", b"\xde\xad\xbe\xef" * 64, "application/octet-stream")},
    )

    assert response.json()["file_type"] == "unknown"


async def test_ac10_a_missing_or_bad_key_returns_401(
    anonymous_client: AsyncClient,
) -> None:
    """AC-10."""
    payload = {"file": ("sample.bin", b"MZ bytes", "application/octet-stream")}

    missing = await anonymous_client.post("/api/v1/submissions", files=payload)
    bad = await anonymous_client.post(
        "/api/v1/submissions", files=payload, headers={"X-API-Key": "upa_wrong"}
    )

    assert missing.status_code == 401
    assert bad.status_code == 401


async def test_ac11_a_valid_key_with_the_wrong_scope_returns_403(
    anonymous_client: AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """AC-11. Known caller, disallowed action - so 403, not 401."""
    key = await issue_key(sessionmaker, Scope.JOBS_READ)

    response = await anonymous_client.post(
        "/api/v1/submissions",
        files={"file": ("sample.bin", b"MZ bytes", "application/octet-stream")},
        headers={"X-API-Key": key},
    )

    assert response.status_code == 403


async def test_ac12_exceeding_the_rate_limit_returns_429(
    settings, clean_database: None
) -> None:
    """AC-12."""
    from app.main import create_app

    limited = settings.model_copy(update={"rate_limit_per_minute": 60, "rate_limit_burst": 1})
    application = create_app(limited)

    async with application.router.lifespan_context(application):
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            key = await issue_key(application.state.sessionmaker, Scope.SUBMISSIONS_WRITE)
            payload = {"file": ("sample.bin", b"MZ bytes", "application/octet-stream")}
            headers = {"X-API-Key": key}

            first = await client.post("/api/v1/submissions", files=payload, headers=headers)
            second = await client.post("/api/v1/submissions", files=payload, headers=headers)

    assert first.status_code == 202
    assert second.status_code == 429


async def test_ac19_submissions_and_auth_failures_are_audited(
    client: AsyncClient,
    anonymous_client: AsyncClient,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """AC-19. Both halves: what was accepted, and what was turned away."""
    await client.post(
        "/api/v1/submissions",
        files={"file": ("sample.bin", b"MZ bytes", "application/octet-stream")},
    )
    await anonymous_client.post(
        "/api/v1/submissions",
        files={"file": ("sample.bin", b"MZ bytes", "application/octet-stream")},
    )

    async with sessionmaker() as session:
        recorded = dict(
            (
                await session.execute(
                    select(AuditEvent.event, func.count()).group_by(AuditEvent.event)
                )
            ).all()
        )

    assert recorded[events.SUBMISSION_ACCEPTED] == 1
    assert recorded[events.AUTH_FAILED] == 1
