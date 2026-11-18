"""Unauthenticated, read-only health endpoint (final SRS EI-SW-1)."""

import sqlite3
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter()


class HealthStatus(BaseModel):
    status: Literal["ok"] = "ok"


@router.get(
    "/health",
    response_model=HealthStatus,
    tags=["health"],
    responses={
        500: {"description": "The database could not be read; details are not exposed."},
        503: {"description": "SQLite could not acquire a lock within its busy timeout."},
    },
)
def health(request: Request) -> HealthStatus | JSONResponse:
    """Check readability through the injected readiness adapter."""
    try:
        request.app.state.readiness.check()
    # This HTTP boundary must sanitize unexpected adapter failures too.
    except Exception as error:  # noqa: BLE001
        sqlite_code = getattr(error, "sqlite_errorcode", 0)
        if isinstance(error, sqlite3.OperationalError) and sqlite_code & 0xFF == sqlite3.SQLITE_BUSY:
            return JSONResponse(
                status_code=503,
                content={
                    "error": {
                        "code": "DATABASE_BUSY",
                        "message": "Database is busy. Try again later.",
                        "details": None,
                    }
                },
            )
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL_ERROR", "message": "An internal error occurred."}},
        )
    return HealthStatus()
