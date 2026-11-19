"""Read-only SQLite readiness adapter used only by GET /health."""

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class DatabaseReadiness(Protocol):
    """Small injectable boundary; it does not own financial transactions."""

    def check(self) -> None:
        """Raise when the configured database cannot be read."""
        ...


@dataclass(frozen=True)
class SqliteReadiness:
    """Inspect an existing database without creating it or running migrations."""

    database_path: Path

    def check(self) -> None:
        uri = self.database_path.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=5.0)) as connection:
            connection.execute("PRAGMA query_only = ON")
            # Reading the catalog also detects a corrupt/non-SQLite file.
            connection.execute("SELECT name FROM sqlite_schema LIMIT 1").fetchone()
