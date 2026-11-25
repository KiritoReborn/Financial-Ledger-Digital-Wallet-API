"""D02 reversal service unit tests with C03 contract fakes and C04 LedgerPoster."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

pytestmark = pytest.mark.usefixtures("api_environment")

contracts = pytest.importorskip(
    "app.contracts", reason="Backend package is required."
)
fakes = pytest.importorskip(
    "app.contracts.fakes", reason="Backend package is required."
)
database_mod = pytest.importorskip(
    "app.database", reason="Backend package is required."
)
http_mod = pytest.importorskip(
    "app.http", reason="Backend package is required."
)
posting_mod = pytest.importorskip(
    "app.posting", reason="Backend package is required."
)
reconcile_mod = pytest.importorskip(
    "app.services.reconciliation", reason="Backend package is required."
)
reversal_mod = pytest.importorskip(
    "app.services.reversal", reason="Backend package is required."
)

from db.migrate import apply_migrations

ApiError = http_mod.ApiError
FakePostTransaction = fakes.FakePostTransaction
LedgerPoster = posting_mod.LedgerPoster
MemoryTransactions = fakes.MemoryTransactions
PostedTransaction = contracts.PostedTransaction
PostingRequest = contracts.PostingRequest
SqliteDatabase = database_mod.SqliteDatabase
reconcile = reconcile_mod.reconcile
reverse_transaction = reversal_mod.reverse_transaction

CREATED_AT = "2026-11-25T00:00:00Z"
ALICE_ID = UUID("00000000-0000-4000-8000-000000000002")
BOB_ID = UUID("00000000-0000-4000-8000-000000000003")

SYS_INR_ID = UUID("10000000-0000-4000-8000-000000000001")
ALICE_INR_ID = UUID("10000000-0000-4000-8000-000000000002")
BOB_INR_ID = UUID("10000000-0000-4000-8000-000000000003")

DEPOSIT_TXN_ID = UUID("20000000-0000-4000-8000-000000000001")
TRANSFER_TXN_ID = UUID("20000000-0000-4000-8000-000000000002")
REVERSAL_TXN_ID = UUID("20000000-0000-4000-8000-000000000003")
STUB_REV_TXN_ID = UUID("20000000-0000-4000-8000-000000000004")
UNKNOWN_TXN_ID = UUID("20000000-0000-4000-8000-999999999999")


def _seed_ledger(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT INTO users (id, name, email, token_hash, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (str(ALICE_ID), "Alice", "alice@example.test", "alice-hash", CREATED_AT),
            (str(BOB_ID), "Bob", "bob@example.test", "bob-hash", CREATED_AT),
        ],
    )
    # Alice deposited 10_000 INR and transferred 4_000 INR to Bob -> Alice=6_000, Bob=4_000.
    conn.executemany(
        "INSERT INTO wallets "
        "(id, user_id, currency, balance_minor, is_system, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (str(SYS_INR_ID), None, "INR", -10_000, 1, CREATED_AT),
            (str(ALICE_INR_ID), str(ALICE_ID), "INR", 6_000, 0, CREATED_AT),
            (str(BOB_INR_ID), str(BOB_ID), "INR", 4_000, 0, CREATED_AT),
        ],
    )
    conn.executemany(
        "INSERT INTO transactions "
        "(id, type, reverses_txn_id, description, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (str(DEPOSIT_TXN_ID), "DEPOSIT", None, "Seed deposit", CREATED_AT),
            (str(TRANSFER_TXN_ID), "TRANSFER", None, "Seed transfer", CREATED_AT),
        ],
    )
    conn.executemany(
        "INSERT INTO ledger_entries "
        "(txn_id, wallet_id, direction, amount_minor, currency, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (str(DEPOSIT_TXN_ID), str(SYS_INR_ID), "DEBIT", 10_000, "INR", CREATED_AT),
            (str(DEPOSIT_TXN_ID), str(ALICE_INR_ID), "CREDIT", 10_000, "INR", CREATED_AT),
            (str(TRANSFER_TXN_ID), str(ALICE_INR_ID), "DEBIT", 4_000, "INR", CREATED_AT),
            (str(TRANSFER_TXN_ID), str(BOB_INR_ID), "CREDIT", 4_000, "INR", CREATED_AT),
        ],
    )


@pytest.fixture
def mem_tx():
    tx = MemoryTransactions()
    apply_migrations(tx.connection)
    with tx.transaction() as conn:
        _seed_ledger(conn)
    yield tx
    tx.close()


@pytest.fixture
def sqlite_db(tmp_path: Path) -> SqliteDatabase:
    db = SqliteDatabase(tmp_path / "reversal-unit.sqlite3")
    db.initialize()
    with db.transaction() as conn:
        _seed_ledger(conn)
    return db


def test_reverse_deposit_mirrors_entries_using_c03_fake(mem_tx):
    with mem_tx.transaction() as conn:
        conn.execute(
            "UPDATE wallets SET balance_minor = 10_000 WHERE id = ?",
            (str(ALICE_INR_ID),),
        )

    fake_post = FakePostTransaction(
        PostedTransaction(STUB_REV_TXN_ID, datetime(2026, 11, 25, 12, 0, tzinfo=UTC))
    )
    with mem_tx.transaction() as conn:
        result = reverse_transaction(conn, DEPOSIT_TXN_ID, post_transaction=fake_post)
        assert conn.in_transaction

    assert result.status_code == 201
    assert result.txn_id == STUB_REV_TXN_ID
    assert len(fake_post.calls) == 1
    called_conn, req = fake_post.calls[0]
    assert called_conn is mem_tx.connection
    assert req == PostingRequest(
        "REVERSAL",
        ALICE_INR_ID,
        SYS_INR_ID,
        10_000,
        "INR",
        None,
        DEPOSIT_TXN_ID,
    )
    assert result.body["type"] == "REVERSAL"
    assert result.body["reverses_txn_id"] == str(DEPOSIT_TXN_ID)
    assert result.body["entries"][0]["direction"] == "DEBIT"
    assert result.body["entries"][0]["wallet_id"] == str(ALICE_INR_ID)
    assert result.body["entries"][1]["direction"] == "CREDIT"
    assert result.body["entries"][1]["wallet_id"] == str(SYS_INR_ID)


def test_reverse_transfer_mirrors_entries_using_c03_fake(mem_tx):
    fake_post = FakePostTransaction(
        PostedTransaction(STUB_REV_TXN_ID, datetime(2026, 11, 25, 12, 0, tzinfo=UTC))
    )
    with mem_tx.transaction() as conn:
        result = reverse_transaction(conn, TRANSFER_TXN_ID, post_transaction=fake_post)
        assert conn.in_transaction

    assert len(fake_post.calls) == 1
    _, req = fake_post.calls[0]
    assert req == PostingRequest(
        "REVERSAL",
        BOB_INR_ID,
        ALICE_INR_ID,
        4_000,
        "INR",
        None,
        TRANSFER_TXN_ID,
    )
    assert result.body["id"] == str(STUB_REV_TXN_ID)


def test_reverse_unknown_transaction_raises_404(mem_tx):
    fake_post = FakePostTransaction(
        PostedTransaction(STUB_REV_TXN_ID, datetime(2026, 11, 25, tzinfo=UTC))
    )
    with pytest.raises(ApiError) as exc, mem_tx.transaction() as conn:
        reverse_transaction(conn, UNKNOWN_TXN_ID, post_transaction=fake_post)
    assert (exc.value.status, exc.value.code) == (404, "NOT_FOUND")
    assert fake_post.calls == []


def test_reverse_a_reversal_raises_422_not_reversible(mem_tx):
    with mem_tx.transaction() as conn:
        conn.execute(
            "INSERT INTO transactions "
            "(id, type, reverses_txn_id, description, created_at) "
            "VALUES (?, 'REVERSAL', ?, NULL, ?)",
            (str(REVERSAL_TXN_ID), str(TRANSFER_TXN_ID), CREATED_AT),
        )
    fake_post = FakePostTransaction(
        PostedTransaction(STUB_REV_TXN_ID, datetime(2026, 11, 25, tzinfo=UTC))
    )
    with pytest.raises(ApiError) as exc, mem_tx.transaction() as conn:
        reverse_transaction(conn, REVERSAL_TXN_ID, post_transaction=fake_post)
    assert (exc.value.status, exc.value.code) == (422, "NOT_REVERSIBLE")
    assert fake_post.calls == []


def test_reverse_already_reversed_raises_409(mem_tx):
    with mem_tx.transaction() as conn:
        conn.execute(
            "INSERT INTO transactions "
            "(id, type, reverses_txn_id, description, created_at) "
            "VALUES (?, 'REVERSAL', ?, NULL, ?)",
            (str(REVERSAL_TXN_ID), str(TRANSFER_TXN_ID), CREATED_AT),
        )
    fake_post = FakePostTransaction(
        PostedTransaction(STUB_REV_TXN_ID, datetime(2026, 11, 25, tzinfo=UTC))
    )
    with pytest.raises(ApiError) as exc, mem_tx.transaction() as conn:
        reverse_transaction(conn, TRANSFER_TXN_ID, post_transaction=fake_post)
    assert (exc.value.status, exc.value.code) == (409, "ALREADY_REVERSED")
    assert fake_post.calls == []


def test_reverse_insufficient_funds_rolls_back_caller_transaction(mem_tx):
    mem_tx.connection.execute("CREATE TABLE rollback_probe (marker INTEGER)")
    fake_post = FakePostTransaction(
        PostedTransaction(STUB_REV_TXN_ID, datetime(2026, 11, 25, tzinfo=UTC))
    )
    with pytest.raises(ApiError) as exc, mem_tx.transaction() as conn:
        conn.execute("INSERT INTO rollback_probe VALUES (1)")
        reverse_transaction(conn, DEPOSIT_TXN_ID, post_transaction=fake_post)

    assert (exc.value.status, exc.value.code) == (422, "INSUFFICIENT_FUNDS")
    assert fake_post.calls == []
    assert not mem_tx.connection.in_transaction
    assert mem_tx.connection.execute("SELECT * FROM rollback_probe").fetchall() == []


def test_reverse_requires_active_transaction(mem_tx):
    fake_post = FakePostTransaction(
        PostedTransaction(STUB_REV_TXN_ID, datetime(2026, 11, 25, tzinfo=UTC))
    )
    with pytest.raises(RuntimeError, match="active write transaction"):
        reverse_transaction(mem_tx.connection, TRANSFER_TXN_ID, post_transaction=fake_post)


def test_reverse_with_real_ledger_poster_and_reconcile(sqlite_db):
    poster = LedgerPoster()
    with sqlite_db.transaction() as conn:
        rev_transfer = reverse_transaction(conn, TRANSFER_TXN_ID, post_transaction=poster)
        assert rev_transfer.body["reverses_txn_id"] == str(TRANSFER_TXN_ID)
        assert [
            (entry["wallet_id"], entry["direction"], entry["amount_minor"])
            for entry in rev_transfer.body["entries"]
        ] == [
            (str(BOB_INR_ID), "DEBIT", 4_000),
            (str(ALICE_INR_ID), "CREDIT", 4_000),
        ]

        rev_deposit = reverse_transaction(conn, DEPOSIT_TXN_ID, post_transaction=poster)
        assert rev_deposit.body["reverses_txn_id"] == str(DEPOSIT_TXN_ID)

    with sqlite_db.transaction(write=False) as conn:
        balances = dict(conn.execute("SELECT id, balance_minor FROM wallets").fetchall())
        assert balances == {
            str(SYS_INR_ID): 0,
            str(ALICE_INR_ID): 0,
            str(BOB_INR_ID): 0,
        }
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 4
        assert reconcile(conn).as_dict()["ok"] is True
