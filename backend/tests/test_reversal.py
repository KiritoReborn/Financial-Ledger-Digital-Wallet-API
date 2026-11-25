"""D02 reversal service unit tests with C03 contract fakes and C04 LedgerPoster."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

pytestmark = pytest.mark.usefixtures("api_environment")

TestClient = pytest.importorskip(
    "fastapi.testclient", reason="API checks require backend[dev]."
).TestClient
create_app = pytest.importorskip(
    "app.main", reason="Backend package is required."
).create_app
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


ADMIN_TOKEN = "test-only-token"
ADMIN_KEY = "test-only-key"
ADMIN_HEADERS = {"Authorization": f"Bearer {ADMIN_TOKEN}", "X-Admin-Key": ADMIN_KEY}


def _setup_live_ledger(client) -> dict[str, str]:
    alice_res = client.post("/users", json={"name": "Alice", "email": "alice@example.test"})
    bob_res = client.post("/users", json={"name": "Bob", "email": "bob@example.test"})
    assert alice_res.status_code == 201 and bob_res.status_code == 201
    alice_token = alice_res.json()["token"]
    bob_token = bob_res.json()["token"]

    alice_w = client.post(
        "/wallets",
        json={"currency": "INR"},
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    bob_w = client.post(
        "/wallets",
        json={"currency": "INR"},
        headers={"Authorization": f"Bearer {bob_token}"},
    )
    assert alice_w.status_code == 201 and bob_w.status_code == 201
    alice_wallet_id = alice_w.json()["id"]
    bob_wallet_id = bob_w.json()["id"]

    deposit = client.post(
        f"/wallets/{alice_wallet_id}/deposit",
        json={"amount_minor": 10_000},
        headers={
            "Authorization": f"Bearer {alice_token}",
            "Idempotency-Key": "e2e-dep-1",
        },
    )
    assert deposit.status_code == 201
    transfer = client.post(
        "/transfers",
        json={
            "from_wallet_id": alice_wallet_id,
            "to_wallet_id": bob_wallet_id,
            "amount_minor": 4_000,
            "currency": "INR",
        },
        headers={
            "Authorization": f"Bearer {alice_token}",
            "Idempotency-Key": "e2e-xfer-1",
        },
    )
    assert transfer.status_code == 201
    return {
        "alice_token": alice_token,
        "bob_token": bob_token,
        "alice_wallet_id": alice_wallet_id,
        "bob_wallet_id": bob_wallet_id,
        "deposit_id": deposit.json()["id"],
        "transfer_id": transfer.json()["id"],
    }


def test_e2e_reverse_transfer_and_deposit_pass_reconciliation():
    with TestClient(create_app()) as client:
        data = _setup_live_ledger(client)

        rev_xfer = client.post(
            f"/transactions/{data['transfer_id']}/reverse",
            headers={**ADMIN_HEADERS, "Idempotency-Key": "rev-xfer-1"},
        )
        assert rev_xfer.status_code == 201
        assert rev_xfer.headers["idempotent-replayed"] == "false"
        assert UUID(rev_xfer.headers["x-request-id"]).version == 4
        body = rev_xfer.json()
        assert body["type"] == "REVERSAL"
        assert body["reverses_txn_id"] == data["transfer_id"]
        assert [(e["wallet_id"], e["direction"], e["amount_minor"]) for e in body["entries"]] == [
            (data["bob_wallet_id"], "DEBIT", 4_000),
            (data["alice_wallet_id"], "CREDIT", 4_000),
        ]

        alice_bal = client.get(
            f"/wallets/{data['alice_wallet_id']}",
            headers={"Authorization": f"Bearer {data['alice_token']}"},
        ).json()["balance_minor"]
        bob_bal = client.get(
            f"/wallets/{data['bob_wallet_id']}",
            headers={"Authorization": f"Bearer {data['bob_token']}"},
        ).json()["balance_minor"]
        assert (alice_bal, bob_bal) == (10_000, 0)
        assert client.get("/admin/reconcile", headers=ADMIN_HEADERS).json()["ok"] is True

        rev_dep = client.post(
            f"/transactions/{data['deposit_id']}/reverse",
            headers={**ADMIN_HEADERS, "Idempotency-Key": "rev-dep-1"},
            json={},
        )
        assert rev_dep.status_code == 201
        assert client.get(
            f"/wallets/{data['alice_wallet_id']}",
            headers={"Authorization": f"Bearer {data['alice_token']}"},
        ).json()["balance_minor"] == 0
        assert client.get("/admin/reconcile", headers=ADMIN_HEADERS).json()["ok"] is True


def test_e2e_reversal_replay_and_idempotency_conflict():
    with TestClient(create_app()) as client:
        data = _setup_live_ledger(client)

        first = client.post(
            f"/transactions/{data['transfer_id']}/reverse",
            headers={**ADMIN_HEADERS, "Idempotency-Key": "shared-rev-key"},
        )
        replay = client.post(
            f"/transactions/{data['transfer_id']}/reverse",
            headers={**ADMIN_HEADERS, "Idempotency-Key": "shared-rev-key"},
        )
        conflict = client.post(
            f"/transactions/{data['deposit_id']}/reverse",
            headers={**ADMIN_HEADERS, "Idempotency-Key": "shared-rev-key"},
        )

    assert first.status_code == 201
    assert first.headers["idempotent-replayed"] == "false"
    assert replay.status_code == 201
    assert replay.headers["idempotent-replayed"] == "true"
    assert replay.json() == first.json()
    assert conflict.status_code == 422
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_e2e_insufficient_funds_rollback_allows_same_key_retry():
    with TestClient(create_app()) as client:
        data = _setup_live_ledger(client)

        failed = client.post(
            f"/transactions/{data['deposit_id']}/reverse",
            headers={**ADMIN_HEADERS, "Idempotency-Key": "retryable-rev-key"},
        )
        assert failed.status_code == 422
        assert failed.json()["error"]["code"] == "INSUFFICIENT_FUNDS"

        assert (
            client.post(
                f"/transactions/{data['transfer_id']}/reverse",
                headers={**ADMIN_HEADERS, "Idempotency-Key": "restore-alice"},
            ).status_code
            == 201
        )

        retried = client.post(
            f"/transactions/{data['deposit_id']}/reverse",
            headers={**ADMIN_HEADERS, "Idempotency-Key": "retryable-rev-key"},
        )
        assert retried.status_code == 201
        assert retried.headers["idempotent-replayed"] == "false"


def test_e2e_reversal_eligibility_and_input_validation():
    with TestClient(create_app()) as client:
        data = _setup_live_ledger(client)

        not_found = client.post(
            f"/transactions/{UNKNOWN_TXN_ID}/reverse",
            headers={**ADMIN_HEADERS, "Idempotency-Key": "val-404"},
        )
        assert not_found.status_code == 404
        assert not_found.json()["error"]["code"] == "NOT_FOUND"

        rev = client.post(
            f"/transactions/{data['transfer_id']}/reverse",
            headers={**ADMIN_HEADERS, "Idempotency-Key": "val-ok"},
        )
        assert rev.status_code == 201
        rev_id = rev.json()["id"]

        not_reversible = client.post(
            f"/transactions/{rev_id}/reverse",
            headers={**ADMIN_HEADERS, "Idempotency-Key": "val-rev-of-rev"},
        )
        assert not_reversible.status_code == 422
        assert not_reversible.json()["error"]["code"] == "NOT_REVERSIBLE"

        already = client.post(
            f"/transactions/{data['transfer_id']}/reverse",
            headers={**ADMIN_HEADERS, "Idempotency-Key": "val-dup"},
        )
        assert already.status_code == 409
        assert already.json()["error"]["code"] == "ALREADY_REVERSED"

        missing_key = client.post(
            f"/transactions/{data['transfer_id']}/reverse",
            headers=ADMIN_HEADERS,
        )
        blank_key = client.post(
            f"/transactions/{data['transfer_id']}/reverse",
            headers={**ADMIN_HEADERS, "Idempotency-Key": "   "},
        )
        bad_key = client.post(
            f"/transactions/{data['transfer_id']}/reverse",
            headers={**ADMIN_HEADERS, "Idempotency-Key": "bad key!"},
        )
        bad_id = client.post(
            "/transactions/not-a-uuid/reverse",
            headers={**ADMIN_HEADERS, "Idempotency-Key": "val-bad-id"},
        )
        bad_body = client.post(
            f"/transactions/{data['transfer_id']}/reverse",
            headers={**ADMIN_HEADERS, "Idempotency-Key": "val-bad-body"},
            json={"unexpected": True},
        )

    assert missing_key.status_code == 400
    assert missing_key.json()["error"]["code"] == "IDEMPOTENCY_KEY_MISSING"
    assert blank_key.status_code == 400
    assert blank_key.json()["error"]["code"] == "IDEMPOTENCY_KEY_MISSING"
    assert bad_key.status_code == 422
    assert bad_key.json()["error"]["code"] == "VALIDATION_ERROR"
    assert bad_id.status_code == 422
    assert bad_id.json()["error"]["code"] == "VALIDATION_ERROR"
    assert bad_body.status_code == 422
    assert bad_body.json()["error"]["code"] == "VALIDATION_ERROR"
