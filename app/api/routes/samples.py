"""Sample lookup and retrieval by content hash."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_audit_log, get_session, get_storage
from app.api.errors import AppError
from app.domain.schemas import SampleRead
from app.security import audit as events
from app.security.audit import AuditLog
from app.security.auth import Caller, require_scope
from app.security.scopes import Scope
from app.services.intake import find_sample
from app.storage.base import SampleNotFoundError, SampleStorage

router = APIRouter(prefix="/samples", tags=["samples"])


class SampleRecordNotFoundError(AppError):
    """No database row for this digest.

    Distinct from storage.SampleNotFoundError, which means the bytes are missing
    from the backend. Different failures, deliberately different names.
    """

    status_code = status.HTTP_404_NOT_FOUND
    title = "Sample Not Found"
    code = "sample-not-found"


class SampleBytesMissingError(AppError):
    """The record exists but the stored object does not.

    A 500 rather than a 404, deliberately. The caller asked for something this
    system said it had; the failure is ours, and reporting it as "not found"
    would hide a store and a database that disagree.
    """

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    title = "Sample Bytes Missing"
    code = "sample-bytes-missing"


@router.get("/{sha256}", response_model=SampleRead, summary="Fetch one sample by digest")
async def read_sample(
    sha256: str,
    session: AsyncSession = Depends(get_session),
    caller: Caller = Depends(require_scope(Scope.JOBS_READ)),
) -> SampleRead:
    """Return the stored record for a content hash."""
    sample = await find_sample(session, sha256.lower())
    if sample is None:
        raise SampleRecordNotFoundError(f"No sample stored with sha256 {sha256}.")
    return SampleRead.from_sample(sample)


@router.get(
    "/{sha256}/download",
    summary="Download the stored bytes of one sample",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
async def download_sample(
    request: Request,
    sha256: str,
    session: AsyncSession = Depends(get_session),
    storage: SampleStorage = Depends(get_storage),
    audit: AuditLog = Depends(get_audit_log),
    caller: Caller = Depends(require_scope(Scope.SAMPLES_DOWNLOAD)),
) -> Response:
    """Return the sample bytes as an attachment.

    This is the most dangerous thing the API can be asked to do - it hands back
    a file that may be live malware - so it is fenced on four sides:

      * its own scope, so nothing else in the system implies permission to do it
      * ``application/octet-stream``, never a type a browser will act on
      * ``Content-Disposition: attachment``, so it is saved rather than rendered
      * ``X-Content-Type-Options: nosniff``, so the declared type is the type,
        and no browser gets to decide the bytes look like something runnable

    The download filename is the digest, never the submitted name. The submitted
    name is attacker-controlled and could be chosen to look harmless, to carry a
    misleading extension, or to attempt traversal in whatever writes it out.
    """
    digest = sha256.lower()
    sample = await find_sample(session, digest)
    if sample is None:
        raise SampleRecordNotFoundError(f"No sample stored with sha256 {sha256}.")

    try:
        payload = await storage.get(digest)
    except SampleNotFoundError as exc:
        # The row exists and the object does not. Rare, and worth its own
        # message: it means the record and the store disagree, which is an
        # operational problem rather than a client mistake.
        raise SampleBytesMissingError(f"The stored object for {digest} is missing.") from exc

    await audit.record(
        events.SAMPLE_DOWNLOADED,
        events.ALLOWED,
        request=request,
        api_key_id=caller.key_id,
        detail=f"sha256 {digest} ({len(payload)} bytes)",
    )

    return Response(
        content=payload,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{digest}.bin"',
            "X-Content-Type-Options": "nosniff",
        },
    )
