"""Member C API application factory; this increment adds health only."""

import os
from pathlib import Path

from fastapi import FastAPI

from .api.health import router as health_router
from .health import DatabaseReadiness, SqliteReadiness


def create_app(*, readiness: DatabaseReadiness | None = None) -> FastAPI:
    """Compose the API without creating a database or bootstrapping other features."""
    application = FastAPI(
        title="Financial Ledger & Digital Wallet API",
        description="Simulated-funds course project. Current increment: read-only health.",
        version="0.0.1",
    )
    application.state.readiness = (
        readiness
        if readiness is not None
        else SqliteReadiness(Path(os.environ.get("DATABASE_PATH", "data/ledger.sqlite3")))
    )
    application.include_router(health_router)
    return application
