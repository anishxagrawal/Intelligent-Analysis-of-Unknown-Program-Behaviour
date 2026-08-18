"""Writing the audit trail.

One decision shapes this module: **audit rows are written on their own session**,
never on the request's.

The events most worth recording are the ones attached to requests that fail. An
authentication failure has no transaction to join, and a submission that raises
after being audited would take its own audit row down with it on rollback. A
separate session means the record survives whatever happens to the request that
produced it, which is the only version of an audit trail worth having.

The cost is that an audited action and its audit row are not atomic: the process
could die between them. Losing the occasional row to a crash is a far smaller
problem than losing every row attached to a failure, which is the alternative.
"""

from __future__ import annotations

import uuid

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.models import AuditEvent
from app.logging import get_logger

logger = get_logger(__name__)

# Event names. Dotted, subject first, so a prefix search groups them.
AUTH_FAILED = "auth.failed"
AUTH_DENIED = "auth.denied"
RATE_LIMITED = "auth.rate_limited"
SUBMISSION_ACCEPTED = "submission.accepted"
SUBMISSION_REJECTED = "submission.rejected"
SAMPLE_DOWNLOADED = "sample.downloaded"

ALLOWED = "allowed"
DENIED = "denied"


class AuditLog:
    """Append-only record of who did what."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def record(
        self,
        event: str,
        outcome: str,
        *,
        request: Request | None = None,
        api_key_id: uuid.UUID | None = None,
        detail: str | None = None,
    ) -> None:
        """Write one event.

        Never raises. An audit write that fails must not turn a successful
        request into a failed one, nor mask the error that was already being
        reported - so the failure is logged loudly and the caller continues.
        The trail is incomplete either way; the question is only whether the
        user also loses their request over it.
        """
        entry = AuditEvent(
            event=event,
            outcome=outcome,
            api_key_id=api_key_id,
            detail=detail,
            **_request_context(request),
        )

        try:
            async with self._sessionmaker() as session:
                session.add(entry)
                await session.commit()
        except Exception:
            logger.exception("audit write failed", extra={"event": event, "outcome": outcome})


def _request_context(request: Request | None) -> dict[str, str | None]:
    """Pull the identifying parts of a request, if there is one."""
    if request is None:
        return {"request_id": None, "method": None, "path": None, "client_ip": None}

    return {
        "request_id": getattr(request.state, "request_id", None),
        "method": request.method,
        "path": request.url.path,
        "client_ip": request.client.host if request.client else None,
    }
