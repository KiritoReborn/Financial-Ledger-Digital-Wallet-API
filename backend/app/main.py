"""API application factory and database startup."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError

from .api.admin import AdminCredentials, ReadSnapshot
from .api.admin import router as admin_router
from .api.errors import error_response
from .api.health import router as health_router
from .api.users import router as users_router
from .auth import bootstrap_admin
from .database import SqliteDatabase
from .health import DatabaseReadiness


def create_app(
    *,
    readiness: DatabaseReadiness | None = None,
    read_snapshot: ReadSnapshot | None = None,
    admin_credentials: AdminCredentials | None = None,
) -> FastAPI:
    """Create the API and initialize its database during ASGI startup."""
    database = SqliteDatabase(Path(os.environ.get("DATABASE_PATH", "data/ledger.sqlite3")))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        credentials = (
            admin_credentials if admin_credentials is not None else AdminCredentials.from_env()
        )
        for variable, value in (("ADMIN_TOKEN", credentials.token), ("ADMIN_KEY", credentials.key)):
            if not value.strip():
                raise ValueError(f"{variable} must be set and nonempty")
        database.initialize()
        with database.transaction() as conn:
            bootstrap_admin(conn, credentials.token)
        app.state.admin_credentials = credentials
        yield

    application = FastAPI(
        title="Financial Ledger & Digital Wallet API",
        description="Simulated-funds course project. Registration, health and administrative reconciliation.",
        version="0.0.1",
        lifespan=lifespan,
    )
    application.state.database = database
    application.state.readiness = database if readiness is None else readiness
    application.state.read_snapshot = (
        read_snapshot if read_snapshot is not None else lambda: database.transaction(write=False)
    )

    @application.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError):
        return error_response(422, "VALIDATION_ERROR", "Request validation failed.")

    application.include_router(users_router)
    application.include_router(health_router)
    application.include_router(admin_router)
    return application
