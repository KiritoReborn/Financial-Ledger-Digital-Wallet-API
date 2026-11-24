import sqlite3
from contextlib import closing

import pytest

from db.migrate import apply_migrations


@pytest.fixture
def db_conn(tmp_path):
    db_path = tmp_path / "immutability.sqlite3"
    with closing(sqlite3.connect(db_path)) as conn:
        assert conn.execute("PRAGMA journal_mode = WAL").fetchone() == ("wal",)
        apply_migrations(conn)
        conn.executescript(
            """
            INSERT INTO users (id, name, email, token_hash, created_at)
            VALUES ('user-1', 'Wallet Owner', 'owner@example.test', 'test-hash',
                    '2026-11-17T00:00:00Z');

            INSERT INTO wallets (id, user_id, currency, balance_minor, is_system, created_at)
            VALUES
                ('w-sys-inr', NULL, 'INR', -5000, 1, '2026-11-17T00:00:00Z'),
                ('w-usr-inr', 'user-1', 'INR', 5000, 0, '2026-11-17T00:00:00Z');

            INSERT INTO transactions (id, type, reverses_txn_id, description, created_at)
            VALUES ('txn-001', 'DEPOSIT', NULL, 'Initial seed deposit', '2026-11-17T00:00:00Z');

            INSERT INTO ledger_entries
                (id, txn_id, wallet_id, direction, amount_minor, currency, created_at)
            VALUES
                (1, 'txn-001', 'w-sys-inr', 'DEBIT', 5000, 'INR', '2026-11-17T00:00:00Z'),
                (2, 'txn-001', 'w-usr-inr', 'CREDIT', 5000, 'INR', '2026-11-17T00:00:00Z');
            """
        )
        yield conn


def test_real_migrations_and_triggers_installed_on_file_db(db_conn):
    main_db_file = next(
        file_path
        for _, name, file_path in db_conn.execute("PRAGMA database_list").fetchall()
        if name == "main"
    )
    assert main_db_file.endswith("immutability.sqlite3")

    versions = db_conn.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    ).fetchall()
    assert versions == [(1,), (2,)]

    triggers = {
        row[0]
        for row in db_conn.execute(
            "SELECT name FROM sqlite_schema WHERE type = 'trigger'"
        ).fetchall()
    }
    assert {
        "prevent_transactions_update",
        "prevent_transactions_delete",
        "prevent_ledger_entries_update",
        "prevent_ledger_entries_delete",
        "ledger_entries_check_wallet_currency",
    }.issubset(triggers)


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
        db_conn.execute("UPDATE ledger_entries SET amount_minor = 999999 WHERE id = 2;")

    amount = db_conn.execute(
        "SELECT amount_minor FROM ledger_entries WHERE id = 2;"
    ).fetchone()[0]
    assert amount == 5000


def test_ledger_entries_delete_is_blocked(db_conn):
    with pytest.raises(sqlite3.IntegrityError, match="FR-4.1 violation"):
        db_conn.execute("DELETE FROM ledger_entries WHERE id = 1;")

    count = db_conn.execute("SELECT COUNT(*) FROM ledger_entries;").fetchone()[0]
    assert count == 2


def test_wallet_balance_minor_updates_succeed(db_conn):
    db_conn.execute(
        "UPDATE wallets SET balance_minor = balance_minor + 2500 WHERE id = 'w-usr-inr';"
    )
    assert db_conn.execute(
        "SELECT balance_minor FROM wallets WHERE id = 'w-usr-inr';"
    ).fetchone() == (7500,)

    db_conn.execute(
        "UPDATE wallets SET balance_minor = balance_minor - 7500 WHERE id = 'w-usr-inr';"
    )
    db_conn.execute(
        "UPDATE wallets SET balance_minor = balance_minor - 2500 WHERE id = 'w-sys-inr';"
    )
    db_conn.commit()

    assert db_conn.execute(
        "SELECT balance_minor FROM wallets WHERE id = 'w-usr-inr';"
    ).fetchone() == (0,)
    assert db_conn.execute(
        "SELECT balance_minor FROM wallets WHERE id = 'w-sys-inr';"
    ).fetchone() == (-7500,)
    assert db_conn.execute("SELECT COUNT(*) FROM transactions;").fetchone()[0] == 1
    assert db_conn.execute("SELECT COUNT(*) FROM ledger_entries;").fetchone()[0] == 2


@pytest.mark.parametrize(
    ("wallet_id", "direction", "entry_currency"),
    [
        ("w-usr-inr", "CREDIT", "USD"),
        ("w-usr-inr", "DEBIT", "JPY"),
        ("w-sys-inr", "DEBIT", "USD"),
    ],
)
def test_ledger_entry_currency_mismatch_aborts(
    db_conn, wallet_id, direction, entry_currency
):
    with pytest.raises(
        sqlite3.IntegrityError,
        match="Ledger entry currency must match its wallet currency",
    ):
        db_conn.execute(
            "INSERT INTO ledger_entries "
            "(txn_id, wallet_id, direction, amount_minor, currency, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?);",
            ("txn-001", wallet_id, direction, 1000, entry_currency, "2026-11-17T00:00:00Z"),
        )

    assert db_conn.execute("SELECT COUNT(*) FROM ledger_entries;").fetchone()[0] == 2
