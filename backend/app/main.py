"""API application factory, database startup, and shared HTTP boundaries."""

import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.admin import AdminCredentials, ReadSnapshot
from .api.admin import router as admin_router
from .api.health import router as health_router
from .api.users import router as users_router
from .auth import bootstrap_admin
from .database import SqliteDatabase
from .health import DatabaseReadiness
from .http import RequestContextMiddleware, RequestSafetyMiddleware, install_error_handlers


def _validate_frontend_origin(value: str) -> str:
    """Require one explicit HTTP origin instead of accepting wildcard access."""
    message = "FRONTEND_ORIGIN must be one HTTP(S) origin, without a path or credentials."
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise ValueError(message) from error
    if (
        not value
        or any(character.isspace() for character in value)
        or "*" in value
        or "," in value
        or parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or port == 0
    ):
        raise ValueError(message)
    return value


def create_app(
    *,
    readiness: DatabaseReadiness | None = None,
    frontend_origin: str | None = None,
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
    origin = _validate_frontend_origin(
        frontend_origin
        if frontend_origin is not None
        else os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173")
    )
    install_error_handlers(application)
    application.add_middleware(RequestSafetyMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[origin],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "X-Admin-Key",
            "X-Request-ID",
        ],
        expose_headers=["Idempotent-Replayed", "X-Request-ID"],
    )
    application.add_middleware(RequestContextMiddleware)
    application.include_router(users_router)
    application.include_router(health_router)
    application.include_router(admin_router)
    return application
