"""Authenticating and authorising a request.

The order below is the security decision worth stating: **authenticate, then
rate limit, then authorise.**

Rate limiting after authentication means the limit is per key, which is what
makes it meaningful - an anonymous limit is trivially evaded by reconnecting.
Authorising last means a caller with a valid key but the wrong scope gets a 403
rather than a 429, so the message they receive describes the actual problem.

Every refusal is audited, and every refusal says as little as possible. A bad
key and an unknown key produce the same 401 with the same wording: telling a
caller which of the two happened confirms that a key exists, and that is
information they have not earned.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from fastapi import Depends, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_audit_log, get_rate_limiter, get_session
from app.api.errors import AppError
from app.domain.models import ApiKey
from app.logging import get_logger
from app.security import audit as events
from app.security.audit import AuditLog
from app.security.keys import hash_key
from app.security.ratelimit import RateLimiter
from app.security.scopes import Scope, parse_scopes

logger = get_logger(__name__)

#: Header carrying the credential. A dedicated header rather than
#: ``Authorization: Bearer``, because this is not an OAuth token and pretending
#: otherwise invites clients to send it to an OAuth server.
API_KEY_HEADER = "X-API-Key"


class AuthenticationError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    title = "Unauthorized"
    code = "unauthorized"


class AuthorizationError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    title = "Forbidden"
    code = "forbidden"


class RateLimitExceededError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    title = "Too Many Requests"
    code = "rate-limited"

    def __init__(self, detail: str | None = None, retry_after: int = 1) -> None:
        super().__init__(detail)
        self.retry_after = retry_after


class Caller:
    """The authenticated identity behind one request."""

    def __init__(self, key_id: uuid.UUID, name: str, scopes: frozenset[Scope]) -> None:
        self.key_id = key_id
        self.name = name
        self.scopes = scopes

    def has(self, scope: Scope) -> bool:
        return scope in self.scopes

    def __repr__(self) -> str:
        return f"<Caller {self.name!r} scopes={sorted(scope.value for scope in self.scopes)}>"


async def authenticate(
    request: Request,
    session: AsyncSession,
    audit: AuditLog,
    limiter: RateLimiter,
) -> Caller:
    """Identify the caller, or refuse the request.

    Returns the caller only when the key exists, is active, and is inside its
    rate limit.
    """
    presented = request.headers.get(API_KEY_HEADER)
    if not presented:
        await audit.record(events.AUTH_FAILED, events.DENIED, request=request, detail="no key")
        raise AuthenticationError("An API key is required. Send it in the X-API-Key header.")

    # Looked up by hash, so the plaintext never reaches a query, a query log, or
    # a slow-query report.
    key = await session.scalar(select(ApiKey).where(ApiKey.token_hash == hash_key(presented)))

    if key is None or not key.is_active:
        # Deliberately one message for both. Distinguishing them would confirm
        # that a particular key exists.
        await audit.record(
            events.AUTH_FAILED,
            events.DENIED,
            request=request,
            api_key_id=key.id if key is not None else None,
            detail="unknown or disabled key",
        )
        raise AuthenticationError("The API key is not valid.")

    if not await limiter.allow(str(key.id)):
        retry_after = await limiter.retry_after(str(key.id))
        await audit.record(
            events.RATE_LIMITED,
            events.DENIED,
            request=request,
            api_key_id=key.id,
            detail=f"retry after {retry_after:.1f}s",
        )
        raise RateLimitExceededError(
            "Rate limit exceeded for this API key.",
            retry_after=max(1, int(retry_after) + 1),
        )

    key.last_used_at = datetime.now(UTC)
    await session.commit()

    return Caller(key_id=key.id, name=key.name, scopes=parse_scopes(list(key.scopes)))


def require_scope(scope: Scope) -> Callable[..., Awaitable[Caller]]:
    """Build a dependency that admits only callers holding ``scope``.

    A factory rather than one dependency reading the route, because the scope a
    route needs is a fact about that route and belongs written at it, where it
    is visible to anyone reading the endpoint.
    """

    async def dependency(
        request: Request,
        session: AsyncSession = Depends(get_session),
        audit: AuditLog = Depends(get_audit_log),
        limiter: RateLimiter = Depends(get_rate_limiter),
    ) -> Caller:
        caller = await authenticate(request, session, audit, limiter)

        if not caller.has(scope):
            await audit.record(
                events.AUTH_DENIED,
                events.DENIED,
                request=request,
                api_key_id=caller.key_id,
                detail=f"missing scope {scope.value}",
            )
            raise AuthorizationError(f"This API key lacks the {scope.value} scope.")

        request.state.caller = caller
        return caller

    return dependency
