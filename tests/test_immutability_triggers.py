import sqlite3
from pathlib import Path

import pytest

MIGRATION_002_PATH = (
    Path(__file__).resolve().parent.parent
    / "db"
    / "migrations"
    / "002_immutability_triggers.sql"
)


@pytest.fixture
def db_conn():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON;")

    # Minimal schema matching SRS Figure B-2 for testing FR-4.1 triggers
    conn.executescript(
        """
        CREATE TABLE users (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        );

        CREATE TABLE wallets (
            id TEXT PRIMARY KEY,
            user_id TEXT REFERENCES users(id),
            currency TEXT NOT NULL,
            balance_minor INTEGER NOT NULL,
            is_system INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE transactions (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            reverses_txn_id TEXT UNIQUE REFERENCES transactions(id),
            description TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE ledger_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            txn_id TEXT NOT NULL REFERENCES transactions(id),
            wallet_id TEXT NOT NULL REFERENCES wallets(id),
            direction TEXT NOT NULL,
            amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
            currency TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )

    # Apply Migration 002
    migration_sql = MIGRATION_002_PATH.read_text(encoding="utf-8")
    conn.executescript(migration_sql)

    # Seed valid rows before testing immutability
    conn.executescript(
        """
        INSERT INTO wallets (id, user_id, currency, balance_minor, is_system, created_at)
        VALUES
            ('w-sys-inr', NULL, 'INR', -5000, 1, '2026-11-17T00:00:00Z'),
            ('w-usr-inr', NULL, 'INR', 5000, 1, '2026-11-17T00:00:00Z');

        INSERT INTO transactions (id, type, reverses_txn_id, description, created_at)
        VALUES ('txn-001', 'DEPOSIT', NULL, 'Initial seed deposit', '2026-11-17T00:00:00Z');

        INSERT INTO ledger_entries (id, txn_id, wallet_id, direction, amount_minor, currency, created_at)
        VALUES
            (1, 'txn-001', 'w-sys-inr', 'DEBIT', 5000, 'INR', '2026-11-17T00:00:00Z'),
            (2, 'txn-001', 'w-usr-inr', 'CREDIT', 5000, 'INR', '2026-11-17T00:00:00Z');
        """
    )
    conn.commit()
    yield conn
    conn.close()


def test_transactions_update_is_blocked(db_conn):
    with pytest.raises(sqlite3.IntegrityError, match="FR-4.1 violation"):
        db_conn.execute(
            "UPDATE transactions SET description = 'Tampered' WHERE id = 'txn-001';"
        )

    row = db_conn.execute(
        "SELECT description FROM transactions WHERE id = 'txn-001';"
    ).fetchone()
    assert row[0] == "Initial seed deposit"


def test_transactions_delete_is_blocked(db_conn):
    with pytest.raises(sqlite3.IntegrityError, match="FR-4.1 violation"):
        db_conn.execute("DELETE FROM transactions WHERE id = 'txn-001';")

    count = db_conn.execute("SELECT COUNT(*) FROM transactions;").fetchone()[0]
    assert count == 1


def test_ledger_entries_update_is_blocked(db_conn):
    with pytest.raises(sqlite3.IntegrityError, match="FR-4.1 violation"):
        db_conn.execute(
            "UPDATE ledger_entries SET amount_minor = 999999 WHERE id = 2;"
        )

    amount = db_conn.execute(
        "SELECT amount_minor FROM ledger_entries WHERE id = 2;"
    ).fetchone()[0]
    assert amount == 5000


def test_ledger_entries_delete_is_blocked(db_conn):
    with pytest.raises(sqlite3.IntegrityError, match="FR-4.1 violation"):
        db_conn.execute("DELETE FROM ledger_entries WHERE id = 1;")

    count = db_conn.execute("SELECT COUNT(*) FROM ledger_entries;").fetchone()[0]
    assert count == 2