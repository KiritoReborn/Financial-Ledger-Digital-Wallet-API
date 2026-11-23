"""API application factory and database startup."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from .api.admin import AdminCredentials, ReadSnapshot
from .api.admin import router as admin_router
from .api.health import router as health_router
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
        database.initialize()
        yield

    application = FastAPI(
        title="Financial Ledger & Digital Wallet API",
        description="Simulated-funds course project. Health and administrative reconciliation.",
        version="0.0.1",
        lifespan=lifespan,
    )
    application.state.database = database
    application.state.readiness = database if readiness is None else readiness
    application.state.read_snapshot = (
        read_snapshot if read_snapshot is not None else lambda: database.transaction(write=False)
    )
    application.state.admin_credentials = admin_credentials
    application.include_router(health_router)
    application.include_router(admin_router)
    return application
