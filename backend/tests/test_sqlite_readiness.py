"""Real SQLite checks; run with unittest or the backend's pytest environment."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

try:
    from app.health import SqliteReadiness
except ModuleNotFoundError as error:
    if error.name != "app":
        raise
    raise unittest.SkipTest("Install the backend or set PYTHONPATH=backend.") from error


class SqliteReadinessTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def database(self, name="ledger.sqlite3"):
        path = self.root / name
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("CREATE TABLE sample (value INTEGER NOT NULL)")
            connection.execute("INSERT INTO sample VALUES (41)")
            connection.commit()
        return path

    def test_existing_database_is_read_without_changing_its_bytes_or_rows(self):
        path = self.database()
        before = path.read_bytes()
        files_before = set(self.root.iterdir())

        SqliteReadiness(path).check()

        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(set(self.root.iterdir()), files_before)
        with closing(sqlite3.connect(path)) as connection:
            self.assertEqual(connection.execute("SELECT value FROM sample").fetchall(), [(41,)])

    def test_missing_database_is_not_created(self):
        path = self.root / "missing.sqlite3"
        with self.assertRaises(sqlite3.OperationalError):
            SqliteReadiness(path).check()
        self.assertFalse(path.exists())

    def test_missing_parent_directory_is_not_created(self):
        path = self.root / "missing-folder" / "ledger.sqlite3"
        with self.assertRaises(sqlite3.OperationalError):
            SqliteReadiness(path).check()
        self.assertFalse(path.parent.exists())

    def test_non_sqlite_file_is_rejected_without_modification(self):
        path = self.root / "invalid.sqlite3"
        path.write_bytes(b"This is not a SQLite database." * 20)
        before = path.read_bytes()
        with self.assertRaises(sqlite3.DatabaseError):
            SqliteReadiness(path).check()
        self.assertEqual(path.read_bytes(), before)

    def test_space_and_hash_in_database_path_are_uri_encoded(self):
        SqliteReadiness(self.database("ledger #1.sqlite3")).check()

    def test_committed_wal_database_remains_unchanged(self):
        path = self.root / "wal.sqlite3"
        with closing(sqlite3.connect(path)) as writer:
            self.assertEqual(writer.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
            writer.execute("CREATE TABLE sample (value INTEGER NOT NULL)")
            writer.execute("INSERT INTO sample VALUES (73)")
            writer.commit()
            wal_path = Path(str(path) + "-wal")
            before = wal_path.read_bytes()

            SqliteReadiness(path).check()

            self.assertEqual(wal_path.read_bytes(), before)
            self.assertEqual(writer.execute("SELECT value FROM sample").fetchall(), [(73,)])
