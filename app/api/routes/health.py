"""Liveness endpoint.

v1 reports only that the process is up. A readiness endpoint that actually
checks the database arrives in v5, where its behaviour when the database is
down is part of the acceptance criteria.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.version import APP_VERSION

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    version: str


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    """Report that the process is alive."""
    return HealthResponse(status="ok", version=APP_VERSION)
