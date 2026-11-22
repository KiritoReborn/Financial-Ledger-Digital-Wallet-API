"""D02 reversal unit tests (C03 fakes) and real WAL SQLite integration tests."""

import hashlib
import importlib.util
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

TestClient = pytest.importorskip(
    "fastapi.testclient", reason="API checks require backend[dev]."
).TestClient
create_app = pytest.importorskip(
    "app.main", reason="Install the backend or set PYTHONPATH=backend."
).create_app
admin_mod = pytest.importorskip(
    "app.api.admin", reason="Install the backend or set PYTHONPATH=backend."
)
reversal_mod = pytest.importorskip(
    "app.services.reversal", reason="Install the backend or set PYTHONPATH=backend."
)

AdminCredentials = admin_mod.AdminCredentials
IdempotencyRequest = reversal_mod.IdempotencyRequest
OperationResult = reversal_mod.OperationResult
PostedTransaction = reversal_mod.PostedTransaction
PostingRequest = reversal_mod.PostingRequest
PostTransaction = reversal_mod.PostTransaction
ReversalError = reversal_mod.ReversalError
RunIdempotent = reversal_mod.RunIdempotent
Transactions = reversal_mod.Transactions
reverse_transaction = reversal_mod.reverse_transaction

try:
    from app.contracts.fakes import (
        FakePostTransaction,
        FakeRunIdempotent,
        MemoryTransactions,
    )
except ModuleNotFoundError:

    class MemoryTransactions:
        """C03-compatible in-memory SQLite transaction double."""

        def __init__(self):
            self.connection = sqlite3.connect(":memory:", isolation_level=None)
            self.connection.execute("PRAGMA foreign_keys=ON")

        def close(self):
            self.connection.close()

        @contextmanager
        def transaction(self, *, write: bool = True):
            if self.connection.in_transaction:
                raise RuntimeError("Nested transaction contexts are not supported.")
            prev = self.connection.execute("PRAGMA query_only").fetchone()[0]
            if not write:
                self.connection.execute("PRAGMA query_only=ON")
            try:
                self.connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                try:
                    yield self.connection
                    self.connection.commit()
                except BaseException:
                    self.connection.rollback()
                    raise
            finally:
                if not write and not prev:
                    self.connection.execute("PRAGMA query_only=OFF")

    class FakePostTransaction:
        """C03-compatible posting stub capturing caller connection and request."""

        def __init__(self, result: PostedTransaction):
            self.result = result
            self.calls: list[tuple[sqlite3.Connection, PostingRequest]] = []

        def __call__(
            self, connection: sqlite3.Connection, request: PostingRequest
        ) -> PostedTransaction:
            if not connection.in_transaction:
                raise RuntimeError("The caller must start the transaction.")
            self.calls.append((connection, request))
            return self.result

    class FakeRunIdempotent:
        """C03-compatible idempotency stub supporting pass-through or replay."""

        def __init__(
            self,
            *,
            replay: OperationResult | None = None,
            failure: Exception | None = None,
        ):
            self.replay = replay
            self.failure = failure
            self.calls: list[tuple[sqlite3.Connection, IdempotencyRequest]] = []

        def __call__(self, connection, request, operation):
            if not connection.in_transaction:
                raise RuntimeError("The caller must start the transaction.")
            self.calls.append((connection, request))
            if self.failure is not None:
                raise self.failure
            if self.replay is not None:
                return self.replay
            return operation()


REPO_ROOT = Path(__file__).resolve().parents[2]
CREATED_AT = "2026-11-22T00:00:00Z"
ADMIN_TOKEN = "demo-admin-token"
ADMIN_KEY = "demo-admin-key"
ADMIN_HEADERS = {
    "Authorization": f"Bearer {ADMIN_TOKEN}",
    "X-Admin-Key": ADMIN_KEY,
    "Idempotency-Key": "rev-key-001",
}

ADMIN_USER_ID = UUID("00000000-0000-4000-8000-000000000001")
ALICE_USER_ID = UUID("00000000-0000-4000-8000-000000000002")
BOB_USER_ID = UUID("00000000-0000-4000-8000-000000000003")

SYS_INR_ID = UUID("10000000-0000-4000-8000-000000000001")
ALICE_INR_ID = UUID("10000000-0000-4000-8000-000000000002")
BOB_INR_ID = UUID("10000000-0000-4000-8000-000000000003")

DEPOSIT_TXN_ID = UUID("20000000-0000-4000-8000-000000000001")
TRANSFER_TXN_ID = UUID("20000000-0000-4000-8000-000000000002")
REVERSAL_TXN_ID = UUID("20000000-0000-4000-8000-000000000003")
STUB_NEW_TXN_ID = UUID("20000000-0000-4000-8000-000000000004")
UNKNOWN_TXN_ID = UUID("20000000-0000-4000-8000-999999999999")


def _apply_migrations(conn: sqlite3.Connection) -> None:
    spec = importlib.util.spec_from_file_location(
        "ledger_migrate", REPO_ROOT / "db" / "migrate.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.apply_migrations(conn)


def _seed_ledger(conn: sqlite3.Connection) -> None:
    admin_hash = hashlib.sha256(ADMIN_TOKEN.encode("utf-8")).hexdigest()
    conn.executemany(
        "INSERT INTO users (id, name, email, token_hash, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (str(ADMIN_USER_ID), "Admin", "admin@example.test", admin_hash, CREATED_AT),
            (str(ALICE_USER_ID), "Alice", "alice@example.test", "alice-hash", CREATED_AT),
            (str(BOB_USER_ID), "Bob", "bob@example.test", "bob-hash", CREATED_AT),
        ],
    )
    # Alice deposited 10_000 INR and transferred 4_000 INR to Bob -> Alice=6_000, Bob=4_000.
    conn.executemany(
        "INSERT INTO wallets "
        "(id, user_id, currency, balance_minor, is_system, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (str(SYS_INR_ID), None, "INR", -10_000, 1, CREATED_AT),
            (str(ALICE_INR_ID), str(ALICE_USER_ID), "INR", 6_000, 0, CREATED_AT),
            (str(BOB_INR_ID), str(BOB_USER_ID), "INR", 4_000, 0, CREATED_AT),
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
    _apply_migrations(tx.connection)
    with tx.transaction() as conn:
        _seed_ledger(conn)
    yield tx
    tx.close()


@pytest.fixture
def wal_db(tmp_path, monkeypatch) -> Path:
    db_path = tmp_path / "ledger.sqlite3"
    with closing(sqlite3.connect(db_path)) as conn:
        assert conn.execute("PRAGMA journal_mode = WAL").fetchone() == ("wal",)
        _apply_migrations(conn)
        with conn:
            _seed_ledger(conn)
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)
    monkeypatch.setenv("ADMIN_KEY", ADMIN_KEY)
    return db_path


def test_c03_fakes_conform_to_runtime_protocols(mem_tx):
    posted = PostedTransaction(STUB_NEW_TXN_ID, datetime(2026, 11, 22, tzinfo=UTC))
    assert isinstance(mem_tx, Transactions)
    assert isinstance(FakePostTransaction(posted), PostTransaction)
    assert isinstance(FakeRunIdempotent(), RunIdempotent)


def test_reverse_deposit_mirrors_entries_using_fake_post_transaction(mem_tx):
    # Top up Alice so she has >= 10_000 to reverse the original deposit.
    with mem_tx.transaction() as conn:
        conn.execute(
            "UPDATE wallets SET balance_minor = 10_000 WHERE id = ?",
            (str(ALICE_INR_ID),),
        )

    posted = PostedTransaction(STUB_NEW_TXN_ID, datetime(2026, 11, 22, 12, 0, tzinfo=UTC))
    fake_post = FakePostTransaction(posted)

    with mem_tx.transaction() as conn:
        txn_id, body = reverse_transaction(conn, DEPOSIT_TXN_ID, fake_post)
        assert conn.in_transaction

    assert txn_id == STUB_NEW_TXN_ID
    assert len(fake_post.calls) == 1
    called_conn, req = fake_post.calls[0]
    assert called_conn is mem_tx.connection
    assert req == PostingRequest(
        kind="REVERSAL",
        debit_wallet_id=ALICE_INR_ID,
        credit_wallet_id=SYS_INR_ID,
        amount_minor=10_000,
        currency="INR",
        description=None,
        reverses_txn_id=DEPOSIT_TXN_ID,
    )
    assert body["type"] == "REVERSAL"
    assert body["reverses_txn_id"] == str(DEPOSIT_TXN_ID)
    assert body["entries"][0]["direction"] == "DEBIT"
    assert body["entries"][0]["wallet_id"] == str(ALICE_INR_ID)
    assert body["entries"][1]["direction"] == "CREDIT"
    assert body["entries"][1]["wallet_id"] == str(SYS_INR_ID)


def test_reverse_transfer_mirrors_entries_using_fake_post_transaction(mem_tx):
    posted = PostedTransaction(STUB_NEW_TXN_ID, datetime(2026, 11, 22, 12, 0, tzinfo=UTC))
    fake_post = FakePostTransaction(posted)

    with mem_tx.transaction() as conn:
        _, body = reverse_transaction(conn, TRANSFER_TXN_ID, fake_post)
        assert conn.in_transaction

    assert len(fake_post.calls) == 1
    _, req = fake_post.calls[0]
    assert req.debit_wallet_id == BOB_INR_ID
    assert req.credit_wallet_id == ALICE_INR_ID
    assert req.amount_minor == 4_000
    assert req.reverses_txn_id == TRANSFER_TXN_ID
    assert body["id"] == str(STUB_NEW_TXN_ID)


def test_reverse_unknown_transaction_returns_404(mem_tx):
    fake_post = FakePostTransaction(
        PostedTransaction(STUB_NEW_TXN_ID, datetime(2026, 11, 22, tzinfo=UTC))
    )
    with pytest.raises(ReversalError) as exc, mem_tx.transaction() as conn:
        reverse_transaction(conn, UNKNOWN_TXN_ID, fake_post)
    assert (exc.value.status, exc.value.code) == (404, "NOT_FOUND")
    assert fake_post.calls == []


def test_reverse_a_reversal_returns_422_not_reversible(mem_tx):
    with mem_tx.transaction() as conn:
        conn.execute(
            "INSERT INTO transactions "
            "(id, type, reverses_txn_id, description, created_at) "
            "VALUES (?, 'REVERSAL', ?, NULL, ?)",
            (str(REVERSAL_TXN_ID), str(TRANSFER_TXN_ID), CREATED_AT),
        )
    fake_post = FakePostTransaction(
        PostedTransaction(STUB_NEW_TXN_ID, datetime(2026, 11, 22, tzinfo=UTC))
    )
    with pytest.raises(ReversalError) as exc, mem_tx.transaction() as conn:
        reverse_transaction(conn, REVERSAL_TXN_ID, fake_post)
    assert (exc.value.status, exc.value.code) == (422, "NOT_REVERSIBLE")
    assert fake_post.calls == []


def test_already_reversed_returns_409(mem_tx):
    with mem_tx.transaction() as conn:
        conn.execute(
            "INSERT INTO transactions "
            "(id, type, reverses_txn_id, description, created_at) "
            "VALUES (?, 'REVERSAL', ?, NULL, ?)",
            (str(REVERSAL_TXN_ID), str(TRANSFER_TXN_ID), CREATED_AT),
        )
    fake_post = FakePostTransaction(
        PostedTransaction(STUB_NEW_TXN_ID, datetime(2026, 11, 22, tzinfo=UTC))
    )
    with pytest.raises(ReversalError) as exc, mem_tx.transaction() as conn:
        reverse_transaction(conn, TRANSFER_TXN_ID, fake_post)
    assert (exc.value.status, exc.value.code) == (409, "ALREADY_REVERSED")
    assert fake_post.calls == []


def test_insufficient_funds_rolls_back_caller_transaction(mem_tx):
    # Deposit was 10_000, Alice currently only holds 6_000 -> cannot reverse deposit.
    mem_tx.connection.execute("CREATE TABLE rollback_probe (marker INTEGER)")
    fake_post = FakePostTransaction(
        PostedTransaction(STUB_NEW_TXN_ID, datetime(2026, 11, 22, tzinfo=UTC))
    )
    with pytest.raises(ReversalError) as exc, mem_tx.transaction() as conn:
        conn.execute("INSERT INTO rollback_probe VALUES (1)")
        reverse_transaction(conn, DEPOSIT_TXN_ID, fake_post)

    assert (exc.value.status, exc.value.code) == (422, "INSUFFICIENT_FUNDS")
    assert fake_post.calls == []
    assert not mem_tx.connection.in_transaction
    assert mem_tx.connection.execute("SELECT * FROM rollback_probe").fetchall() == []


def test_reverse_requires_active_transaction(mem_tx):
    fake_post = FakePostTransaction(
        PostedTransaction(STUB_NEW_TXN_ID, datetime(2026, 11, 22, tzinfo=UTC))
    )
    with pytest.raises(RuntimeError, match="active write transaction"):
        reverse_transaction(mem_tx.connection, TRANSFER_TXN_ID, fake_post)


def test_http_endpoint_with_c03_replay_fake_returns_stored_response(wal_db):
    stored_body = {
        "id": str(REVERSAL_TXN_ID),
        "type": "REVERSAL",
        "description": None,
        "reverses_txn_id": str(TRANSFER_TXN_ID),
        "created_at": CREATED_AT,
        "entries": [
            {
                "id": 10,
                "txn_id": str(REVERSAL_TXN_ID),
                "wallet_id": str(BOB_INR_ID),
                "type": "REVERSAL",
                "direction": "DEBIT",
                "amount_minor": 4_000,
                "currency": "INR",
                "created_at": CREATED_AT,
            },
            {
                "id": 11,
                "txn_id": str(REVERSAL_TXN_ID),
                "wallet_id": str(ALICE_INR_ID),
                "type": "REVERSAL",
                "direction": "CREDIT",
                "amount_minor": 4_000,
                "currency": "INR",
                "created_at": CREATED_AT,
            },
        ],
    }
    fake_post = FakePostTransaction(
        PostedTransaction(STUB_NEW_TXN_ID, datetime(2026, 11, 22, tzinfo=UTC))
    )
    fake_idem = FakeRunIdempotent(
        replay=OperationResult(201, stored_body, REVERSAL_TXN_ID, replayed=True)
    )
    app = create_app(
        post_transaction=fake_post,
        run_idempotent=fake_idem,
        admin_credentials=AdminCredentials(ADMIN_TOKEN, ADMIN_KEY),
    )

    with TestClient(app) as client:
        response = client.post(
            f"/transactions/{TRANSFER_TXN_ID}/reverse",
            headers=ADMIN_HEADERS,
            json={},
        )

    assert response.status_code == 201
    assert response.headers["idempotent-replayed"] == "true"
    assert response.json() == stored_body
    assert fake_post.calls == []
    assert len(fake_idem.calls) == 1
    assert fake_idem.calls[0][1].scope == "REVERSAL"
    assert fake_idem.calls[0][1].target_id == TRANSFER_TXN_ID


def test_http_endpoint_with_c03_passthrough_fakes(wal_db):
    fake_post = FakePostTransaction(
        PostedTransaction(STUB_NEW_TXN_ID, datetime(2026, 11, 22, tzinfo=UTC))
    )
    fake_idem = FakeRunIdempotent()
    app = create_app(
        post_transaction=fake_post,
        run_idempotent=fake_idem,
        admin_credentials=AdminCredentials(ADMIN_TOKEN, ADMIN_KEY),
    )

    with TestClient(app) as client:
        response = client.post(
            f"/transactions/{TRANSFER_TXN_ID}/reverse",
            headers=ADMIN_HEADERS,
        )

    assert response.status_code == 201
    assert "idempotent-replayed" not in response.headers
    body = response.json()
    assert body["id"] == str(STUB_NEW_TXN_ID)
    assert body["reverses_txn_id"] == str(TRANSFER_TXN_ID)
    assert len(fake_post.calls) == 1
    assert len(fake_idem.calls) == 1
    assert fake_idem.calls[0][1] == IdempotencyRequest(
        user_id=ADMIN_USER_ID,
        scope="REVERSAL",
        key="rev-key-001",
        target_id=TRANSFER_TXN_ID,
        body={},
    )


def test_http_endpoint_maps_c04_posting_error_and_rolls_back(wal_db):
    @dataclass
    class FakeC04PostingError(Exception):
        code: str
        message: str

    def failing_post(conn, req):
        conn.execute(
            "UPDATE wallets SET balance_minor = 0 WHERE id = ?", (str(BOB_INR_ID),)
        )
        raise FakeC04PostingError("INSUFFICIENT_FUNDS", "Balance is too low.")

    app = create_app(
        post_transaction=failing_post,
        run_idempotent=FakeRunIdempotent(),
        admin_credentials=AdminCredentials(ADMIN_TOKEN, ADMIN_KEY),
    )

    with TestClient(app) as client:
        response = client.post(
            f"/transactions/{TRANSFER_TXN_ID}/reverse",
            headers=ADMIN_HEADERS,
        )

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "INSUFFICIENT_FUNDS",
            "message": "Balance is too low.",
            "details": None,
        }
    }
    with closing(sqlite3.connect(wal_db)) as conn:
        assert conn.execute(
            "SELECT balance_minor FROM wallets WHERE id = ?", (str(BOB_INR_ID),)
        ).fetchone() == (4_000,)


def test_integration_reverse_transfer_and_deposit_pass_reconciliation(wal_db):
    with TestClient(create_app()) as client:
        rev_transfer = client.post(
            f"/transactions/{TRANSFER_TXN_ID}/reverse",
            headers={**ADMIN_HEADERS, "Idempotency-Key": "rev-transfer-1"},
        )
        assert rev_transfer.status_code == 201
        rev_body = rev_transfer.json()
        assert rev_body["type"] == "REVERSAL"
        assert rev_body["reverses_txn_id"] == str(TRANSFER_TXN_ID)
        assert [(e["wallet_id"], e["direction"], e["amount_minor"]) for e in rev_body["entries"]] == [
            (str(BOB_INR_ID), "DEBIT", 4_000),
            (str(ALICE_INR_ID), "CREDIT", 4_000),
        ]

        # Now Alice has 10_000 INR again, so reversing the deposit also succeeds.
        rev_deposit = client.post(
            f"/transactions/{DEPOSIT_TXN_ID}/reverse",
            headers={**ADMIN_HEADERS, "Idempotency-Key": "rev-deposit-1"},
        )
        assert rev_deposit.status_code == 201

        rec = client.get(
            "/admin/reconcile",
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}", "X-Admin-Key": ADMIN_KEY},
        )
        assert rec.status_code == 200
        assert rec.json()["ok"] is True

    with closing(sqlite3.connect(wal_db)) as conn:
        balances = dict(
            conn.execute("SELECT id, balance_minor FROM wallets").fetchall()
        )
        assert balances == {
            str(SYS_INR_ID): 0,
            str(ALICE_INR_ID): 0,
            str(BOB_INR_ID): 0,
        }
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 4
        assert conn.execute("SELECT COUNT(*) FROM idempotency_keys").fetchone()[0] == 2


def test_integration_failed_reversal_allows_retry_with_same_key(wal_db):
    with TestClient(create_app()) as client:
        # Deposit is 10_000; Alice has 6_000 -> fails 422 without storing key.
        first = client.post(
            f"/transactions/{DEPOSIT_TXN_ID}/reverse",
            headers={**ADMIN_HEADERS, "Idempotency-Key": "retryable-key"},
        )
        assert first.status_code == 422
        assert first.json()["error"]["code"] == "INSUFFICIENT_FUNDS"

        # Reverse the transfer so Alice returns to 10_000.
        assert (
            client.post(
                f"/transactions/{TRANSFER_TXN_ID}/reverse",
                headers={**ADMIN_HEADERS, "Idempotency-Key": "clear-transfer"},
            ).status_code
            == 201
        )

        # Retry deposit reversal with the exact same Idempotency-Key (FR-2.9).
        second = client.post(
            f"/transactions/{DEPOSIT_TXN_ID}/reverse",
            headers={**ADMIN_HEADERS, "Idempotency-Key": "retryable-key"},
        )
        assert second.status_code == 201
        assert "idempotent-replayed" not in second.headers


@pytest.mark.parametrize(
    ("txn_path", "headers", "body", "expected_status", "expected_code"),
    [
        (
            str(TRANSFER_TXN_ID),
            {"Authorization": f"Bearer {ADMIN_TOKEN}", "X-Admin-Key": ADMIN_KEY},
            {},
            400,
            "IDEMPOTENCY_KEY_MISSING",
        ),
        (
            str(TRANSFER_TXN_ID),
            {**ADMIN_HEADERS, "Idempotency-Key": "   "},
            {},
            400,
            "IDEMPOTENCY_KEY_MISSING",
        ),
        (
            str(TRANSFER_TXN_ID),
            {**ADMIN_HEADERS, "Idempotency-Key": "bad key!"},
            {},
            422,
            "VALIDATION_ERROR",
        ),
        (
            "not-a-uuid",
            ADMIN_HEADERS,
            {},
            422,
            "VALIDATION_ERROR",
        ),
        (
            str(TRANSFER_TXN_ID),
            ADMIN_HEADERS,
            {"unexpected": True},
            422,
            "VALIDATION_ERROR",
        ),
    ],
    ids=[
        "missing-key",
        "blank-key",
        "invalid-key",
        "invalid-txn-id",
        "unknown-body-field",
    ],
)
def test_integration_input_and_header_validation(
    wal_db, txn_path, headers, body, expected_status, expected_code
):
    with TestClient(create_app()) as client:
        response = client.post(
            f"/transactions/{txn_path}/reverse", headers=headers, json=body
        )
    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code


def test_integration_idempotency_conflict_on_reused_key(wal_db):
    with TestClient(create_app()) as client:
        first = client.post(
            f"/transactions/{TRANSFER_TXN_ID}/reverse",
            headers={**ADMIN_HEADERS, "Idempotency-Key": "shared-key"},
        )
        assert first.status_code == 201

        conflict = client.post(
            f"/transactions/{DEPOSIT_TXN_ID}/reverse",
            headers={**ADMIN_HEADERS, "Idempotency-Key": "shared-key"},
        )
        assert conflict.status_code == 422
        assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
