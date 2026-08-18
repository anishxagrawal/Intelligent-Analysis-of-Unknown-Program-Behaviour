"""Error responses in RFC 7807 problem-details format.

One error shape for the whole API, decided before the API grows. Every failure
response carries the request id, so a user reporting a problem gives you the
exact identifier needed to find the matching log lines.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_JSON = "application/problem+json"

#: Base for the ``type`` field. A real URL is expected to document each error;
#: until that documentation exists, a stable URN is more honest than a link to
#: a page that does not exist.
PROBLEM_TYPE_BASE = "urn:upa:error"


class AppError(Exception):
    """Base class for errors this application raises deliberately.

    Carrying the status code and title on the exception keeps the decision about
    how a failure is reported next to the code that detects it.
    """

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    title: str = "Internal Server Error"
    code: str = "internal-error"

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.title
        super().__init__(self.detail)


class JobNotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    title = "Job Not Found"
    code = "job-not-found"


def problem_response(
    *,
    status_code: int,
    title: str,
    detail: str,
    code: str,
    request: Request,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    """Build one problem-details response."""
    body: dict[str, Any] = {
        "type": f"{PROBLEM_TYPE_BASE}:{code}",
        "title": title,
        "status": status_code,
        "detail": detail,
        "instance": str(request.url.path),
        "request_id": getattr(request.state, "request_id", None),
    }
    if extra:
        body.update(extra)

    return JSONResponse(status_code=status_code, content=body, media_type=PROBLEM_JSON)


def register_error_handlers(app: FastAPI) -> None:
    """Install handlers so every failure leaves as problem details."""

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return problem_response(
            status_code=exc.status_code,
            title=exc.title,
            detail=exc.detail,
            code=exc.code,
            request=request,
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        title = _TITLES.get(exc.status_code, "Error")
        return problem_response(
            status_code=exc.status_code,
            title=title,
            detail=str(exc.detail),
            code=_CODES.get(exc.status_code, "http-error"),
            request=request,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Validation errors carry per-field information. It is genuinely useful
        # to the caller, so it is preserved rather than flattened into prose.
        errors = [
            {
                "location": list(error.get("loc", ())),
                "message": error.get("msg", ""),
                "type": error.get("type", ""),
            }
            for error in exc.errors()
        ]
        return problem_response(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            title="Validation Failed",
            detail="The request did not pass validation.",
            code="validation-failed",
            request=request,
            extra={"errors": errors},
        )


_TITLES = {
    status.HTTP_400_BAD_REQUEST: "Bad Request",
    status.HTTP_401_UNAUTHORIZED: "Unauthorized",
    status.HTTP_403_FORBIDDEN: "Forbidden",
    status.HTTP_404_NOT_FOUND: "Not Found",
    status.HTTP_405_METHOD_NOT_ALLOWED: "Method Not Allowed",
    status.HTTP_413_CONTENT_TOO_LARGE: "Payload Too Large",
    status.HTTP_422_UNPROCESSABLE_CONTENT: "Validation Failed",
    status.HTTP_429_TOO_MANY_REQUESTS: "Too Many Requests",
    status.HTTP_500_INTERNAL_SERVER_ERROR: "Internal Server Error",
}

_CODES = {
    status.HTTP_400_BAD_REQUEST: "bad-request",
    status.HTTP_401_UNAUTHORIZED: "unauthorized",
    status.HTTP_403_FORBIDDEN: "forbidden",
    status.HTTP_404_NOT_FOUND: "not-found",
    status.HTTP_405_METHOD_NOT_ALLOWED: "method-not-allowed",
    status.HTTP_413_CONTENT_TOO_LARGE: "payload-too-large",
    status.HTTP_422_UNPROCESSABLE_CONTENT: "validation-failed",
    status.HTTP_429_TOO_MANY_REQUESTS: "rate-limited",
    status.HTTP_500_INTERNAL_SERVER_ERROR: "internal-error",
}
