"""D04 admin security, race/replay, error sanitization, and tamper-detection suite."""

import hashlib
import importlib.util
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
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

AdminCredentials = admin_mod.AdminCredentials

REPO_ROOT = Path(__file__).resolve().parents[1]
CREATED_AT = "2026-11-22T00:00:00Z"

ADMIN_TOKEN = "super-secret-admin-token"
ADMIN_KEY = "super-secret-admin-key"
ALICE_TOKEN = "alice-non-admin-user-token"

ADMIN_USER_ID = UUID("00000000-0000-4000-8000-000000000001")
ALICE_USER_ID = UUID("00000000-0000-4000-8000-000000000002")
BOB_USER_ID = UUID("00000000-0000-4000-8000-000000000003")

SYS_INR_ID = UUID("10000000-0000-4000-8000-000000000001")
ALICE_INR_ID = UUID("10000000-0000-4000-8000-000000000002")
BOB_INR_ID = UUID("10000000-0000-4000-8000-000000000003")

DEPOSIT_TXN_ID = UUID("20000000-0000-4000-8000-000000000001")
TRANSFER_TXN_ID = UUID("20000000-0000-4000-8000-000000000002")

ADMIN_AUTH = {"Authorization": f"Bearer {ADMIN_TOKEN}", "X-Admin-Key": ADMIN_KEY}
UNAUTHENTICATED_BODY = {
    "error": {
        "code": "UNAUTHENTICATED",
        "message": "Authentication is required.",
        "details": None,
    }
}


def _apply_migrations(conn: sqlite3.Connection) -> None:
    spec = importlib.util.spec_from_file_location(
        "ledger_migrate", REPO_ROOT / "db" / "migrate.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.apply_migrations(conn)


@pytest.fixture
def security_db(tmp_path, monkeypatch) -> Path:
    db_path = tmp_path / "security.sqlite3"
    admin_hash = hashlib.sha256(ADMIN_TOKEN.encode("utf-8")).hexdigest()
    alice_hash = hashlib.sha256(ALICE_TOKEN.encode("utf-8")).hexdigest()

    with closing(sqlite3.connect(db_path)) as conn:
        assert conn.execute("PRAGMA journal_mode = WAL").fetchone() == ("wal",)
        _apply_migrations(conn)
        with conn:
            conn.executemany(
                "INSERT INTO users (id, name, email, token_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        str(ADMIN_USER_ID),
                        "Admin",
                        "admin@example.test",
                        admin_hash,
                        CREATED_AT,
                    ),
                    (
                        str(ALICE_USER_ID),
                        "Alice",
                        "alice@example.test",
                        alice_hash,
                        CREATED_AT,
                    ),
                    (
                        str(BOB_USER_ID),
                        "Bob",
                        "bob@example.test",
                        "bob-hash",
                        CREATED_AT,
                    ),
                ],
            )
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
                    (str(DEPOSIT_TXN_ID), "DEPOSIT", None, "Deposit", CREATED_AT),
                    (str(TRANSFER_TXN_ID), "TRANSFER", None, "Transfer", CREATED_AT),
                ],
            )
            conn.executemany(
                "INSERT INTO ledger_entries "
                "(txn_id, wallet_id, direction, amount_minor, currency, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        str(DEPOSIT_TXN_ID),
                        str(SYS_INR_ID),
                        "DEBIT",
                        10_000,
                        "INR",
                        CREATED_AT,
                    ),
                    (
                        str(DEPOSIT_TXN_ID),
                        str(ALICE_INR_ID),
                        "CREDIT",
                        10_000,
                        "INR",
                        CREATED_AT,
                    ),
                    (
                        str(TRANSFER_TXN_ID),
                        str(ALICE_INR_ID),
                        "DEBIT",
                        4_000,
                        "INR",
                        CREATED_AT,
                    ),
                    (
                        str(TRANSFER_TXN_ID),
                        str(BOB_INR_ID),
                        "CREDIT",
                        4_000,
                        "INR",
                        CREATED_AT,
                    ),
                ],
            )

    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)
    monkeypatch.setenv("ADMIN_KEY", ADMIN_KEY)
    return db_path


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-Admin-Key": ADMIN_KEY},
        {"Authorization": f"Bearer {ADMIN_TOKEN}"},
        {"Authorization": "Bearer ", "X-Admin-Key": ADMIN_KEY},
        {"Authorization": "Bearer wrong-token", "X-Admin-Key": ADMIN_KEY},
        {"Authorization": f"Basic {ADMIN_TOKEN}", "X-Admin-Key": ADMIN_KEY},
        {"Authorization": f"Bearer {ADMIN_TOKEN}", "X-Admin-Key": "wrong-key"},
        {"Authorization": f"Bearer {ADMIN_TOKEN}", "X-Admin-Key": ""},
    ],
    ids=[
        "no-headers",
        "key-only",
        "token-only",
        "empty-bearer",
        "wrong-token",
        "basic-scheme",
        "wrong-admin-key",
        "empty-admin-key",
    ],
)
def test_missing_or_invalid_admin_credentials_rejected_on_both_endpoints(
    security_db, headers
):
    with TestClient(create_app()) as client:
        rec = client.get("/admin/reconcile", headers=headers)
        rev = client.post(
            f"/transactions/{TRANSFER_TXN_ID}/reverse",
            headers={**headers, "Idempotency-Key": "auth-check"},
        )

    for resp in (rec, rev):
        assert resp.status_code == 401
        assert resp.json() == UNAUTHENTICATED_BODY
        assert resp.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("unset_var", ["ADMIN_TOKEN", "ADMIN_KEY"])
def test_unconfigured_admin_env_vars_fail_closed(security_db, monkeypatch, unset_var):
    monkeypatch.setenv(unset_var, "")
    with TestClient(create_app()) as client:
        rec = client.get("/admin/reconcile", headers=ADMIN_AUTH)
        rev = client.post(
            f"/transactions/{TRANSFER_TXN_ID}/reverse",
            headers={**ADMIN_AUTH, "Idempotency-Key": "unset-env"},
        )
    assert rec.status_code == 401
    assert rev.status_code == 401


def test_admin_auth_uses_constant_time_hmac_without_short_circuit(
    security_db, monkeypatch
):
    calls: list[tuple[int, int]] = []
    real_compare = admin_mod.hmac.compare_digest

    def spy_compare(left, right):
        calls.append((len(left), len(right)))
        return real_compare(left, right)

    monkeypatch.setattr(admin_mod.hmac, "compare_digest", spy_compare)

    with TestClient(create_app()) as client:
        client.post(
            f"/transactions/{TRANSFER_TXN_ID}/reverse",
            headers={
                "Authorization": "Bearer wrong",
                "X-Admin-Key": "wrong-key",
                "Idempotency-Key": "spy-key",
            },
        )
    assert calls == [(32, 32), (32, 32)]


@pytest.mark.parametrize("include_admin_key", [False, True])
def test_non_admin_user_token_rejected_on_admin_endpoints(
    security_db, include_admin_key
):
    before = security_db.read_bytes()
    headers = {"Authorization": f"Bearer {ALICE_TOKEN}"}
    if include_admin_key:
        headers["X-Admin-Key"] = ADMIN_KEY

    with TestClient(create_app()) as client:
        rec = client.get("/admin/reconcile", headers=headers)
        rev = client.post(
            f"/transactions/{TRANSFER_TXN_ID}/reverse",
            headers={**headers, "Idempotency-Key": "non-admin-attempt"},
        )

    assert rec.status_code == 401
    assert rev.status_code == 401
    assert rec.json() == UNAUTHENTICATED_BODY
    assert rev.json() == UNAUTHENTICATED_BODY
    assert security_db.read_bytes() == before


def test_sequential_replay_and_second_key_rejection(security_db):
    with TestClient(create_app()) as client:
        first = client.post(
            f"/transactions/{TRANSFER_TXN_ID}/reverse",
            headers={**ADMIN_AUTH, "Idempotency-Key": "seq-rev-1"},
        )
        replay = client.post(
            f"/transactions/{TRANSFER_TXN_ID}/reverse",
            headers={**ADMIN_AUTH, "Idempotency-Key": "seq-rev-1"},
        )
        second = client.post(
            f"/transactions/{TRANSFER_TXN_ID}/reverse",
            headers={**ADMIN_AUTH, "Idempotency-Key": "seq-rev-2"},
        )
        rec = client.get("/admin/reconcile", headers=ADMIN_AUTH)

    assert first.status_code == 201
    assert "idempotent-replayed" not in first.headers
    assert replay.status_code == 201
    assert replay.headers["idempotent-replayed"] == "true"
    assert replay.json() == first.json()
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "ALREADY_REVERSED"
    assert rec.status_code == 200 and rec.json()["ok"] is True


def test_concurrent_double_reversal_different_keys_allows_only_one(security_db):
    barrier = threading.Barrier(2)

    def send_reverse(key: str):
        with TestClient(create_app()) as client:
            barrier.wait(timeout=5)
            return client.post(
                f"/transactions/{TRANSFER_TXN_ID}/reverse",
                headers={**ADMIN_AUTH, "Idempotency-Key": key},
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        r1, r2 = [
            fut.result()
            for fut in (
                pool.submit(send_reverse, "race-key-a"),
                pool.submit(send_reverse, "race-key-b"),
            )
        ]

    statuses = sorted([r1.status_code, r2.status_code])
    assert statuses == [201, 409]
    rejected = r1 if r1.status_code == 409 else r2
    assert rejected.json()["error"]["code"] == "ALREADY_REVERSED"

    with closing(sqlite3.connect(security_db)) as conn:
        reversals = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE type = 'REVERSAL'"
        ).fetchone()[0]
        assert reversals == 1

    with TestClient(create_app()) as client:
        assert client.get("/admin/reconcile", headers=ADMIN_AUTH).json()["ok"] is True


def test_concurrent_same_key_reversal_creates_once_and_replays(security_db):
    barrier = threading.Barrier(2)

    def send_reverse():
        with TestClient(create_app()) as client:
            barrier.wait(timeout=5)
            return client.post(
                f"/transactions/{TRANSFER_TXN_ID}/reverse",
                headers={**ADMIN_AUTH, "Idempotency-Key": "concurrent-same-key"},
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        r1, r2 = [
            fut.result()
            for fut in (pool.submit(send_reverse), pool.submit(send_reverse))
        ]

    assert (r1.status_code, r2.status_code) == (201, 201)
    assert r1.json() == r2.json()
    replayed_flags = sorted(
        [
            r1.headers.get("idempotent-replayed", "false"),
            r2.headers.get("idempotent-replayed", "false"),
        ]
    )
    assert replayed_flags == ["false", "true"]

    with closing(sqlite3.connect(security_db)) as conn:
        reversals = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE type = 'REVERSAL'"
        ).fetchone()[0]
        assert reversals == 1


def test_unexpected_errors_leak_no_sql_paths_traces_or_secrets(security_db):
    idem_key = "idem-key-1111"
    sensitive_msg = (
        f"Traceback SELECT * FROM users WHERE path={security_db} "
        f"token={ADMIN_TOKEN} key={ADMIN_KEY} idem={idem_key}"
    )

    @contextmanager
    def exploding_ctx():
        raise RuntimeError(sensitive_msg)
        yield  # pragma: no cover

    app = create_app(
        read_snapshot=exploding_ctx,
        write_transaction=exploding_ctx,
        admin_credentials=AdminCredentials(ADMIN_TOKEN, ADMIN_KEY),
    )

    with TestClient(app) as client:
        rec = client.get("/admin/reconcile", headers=ADMIN_AUTH)
        rev = client.post(
            f"/transactions/{TRANSFER_TXN_ID}/reverse",
            headers={**ADMIN_AUTH, "Idempotency-Key": idem_key},
        )

    expected = {
        "error": {"code": "INTERNAL_ERROR", "message": "An internal error occurred."}
    }
    for resp in (rec, rev):
        assert resp.status_code == 500
        assert resp.json() == expected
        for forbidden in (
            "Traceback",
            "SELECT",
            str(security_db),
            ADMIN_TOKEN,
            ADMIN_KEY,
            idem_key,
        ):
            assert forbidden not in resp.text


def test_sqlite_busy_sanitizes_internal_details(security_db):
    @contextmanager
    def busy_ctx():
        err = sqlite3.OperationalError(
            f"database {security_db} locked during SELECT * FROM wallets"
        )
        err.sqlite_errorcode = sqlite3.SQLITE_BUSY
        raise err
        yield  # pragma: no cover

    app = create_app(
        read_snapshot=busy_ctx,
        write_transaction=busy_ctx,
        admin_credentials=AdminCredentials(ADMIN_TOKEN, ADMIN_KEY),
    )
    with TestClient(app) as client:
        rec = client.get("/admin/reconcile", headers=ADMIN_AUTH)
        rev = client.post(
            f"/transactions/{TRANSFER_TXN_ID}/reverse",
            headers={**ADMIN_AUTH, "Idempotency-Key": "busy-probe"},
        )

    expected = {
        "error": {
            "code": "DATABASE_BUSY",
            "message": "Database is busy. Try again later.",
            "details": None,
        }
    }
    for resp in (rec, rev):
        assert resp.status_code == 503
        assert resp.json() == expected
        assert "wallets" not in resp.text
        assert str(security_db) not in resp.text


def test_missing_and_corrupt_database_responses_are_sanitized(tmp_path, monkeypatch):
    missing = tmp_path / "missing.sqlite3"
    monkeypatch.setenv("DATABASE_PATH", str(missing))
    monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)
    monkeypatch.setenv("ADMIN_KEY", ADMIN_KEY)

    with TestClient(create_app()) as client:
        rec = client.get("/admin/reconcile", headers=ADMIN_AUTH)
        rev = client.post(
            f"/transactions/{TRANSFER_TXN_ID}/reverse",
            headers={**ADMIN_AUTH, "Idempotency-Key": "missing-db"},
        )
    for resp in (rec, rev):
        assert resp.status_code == 500
        assert str(tmp_path) not in resp.text
        assert "sqlite" not in resp.text.lower()
    assert not missing.exists()


def test_reconciliation_detects_direct_sqlite_balance_and_ledger_tampering(
    security_db,
):
    with TestClient(create_app()) as client:
        assert (
            client.post(
                f"/transactions/{TRANSFER_TXN_ID}/reverse",
                headers={**ADMIN_AUTH, "Idempotency-Key": "clean-rev"},
            ).status_code
            == 201
        )
        clean = client.get("/admin/reconcile", headers=ADMIN_AUTH)
        assert clean.status_code == 200
        assert clean.json() == {
            "ok": True,
            "checks": {
                "currencies_balanced": True,
                "transactions_valid": True,
                "wallet_balances_match": True,
                "entry_currencies_match": True,
            },
            "mismatches": [],
        }

    # Tamper directly in SQLite (user + system wallet balances).
    with closing(sqlite3.connect(security_db)) as conn, conn:
        conn.execute(
            "UPDATE wallets SET balance_minor = balance_minor + 500 WHERE id = ?",
            (str(BOB_INR_ID),),
        )
        conn.execute(
            "UPDATE wallets SET balance_minor = 0 WHERE id = ?",
            (str(SYS_INR_ID),),
        )

    with TestClient(create_app()) as client:
        tampered = client.get("/admin/reconcile", headers=ADMIN_AUTH)

    assert tampered.status_code == 200
    body = tampered.json()
    assert body["ok"] is False
    assert body["checks"]["wallet_balances_match"] is False
    by_wallet = {item["wallet_id"]: item for item in body["mismatches"]}
    assert by_wallet[str(BOB_INR_ID)] == {
        "check": "wallet_balances_match",
        "currency": "INR",
        "wallet_id": str(BOB_INR_ID),
        "expected": 0,
        "actual": 500,
    }
    assert by_wallet[str(SYS_INR_ID)] == {
        "check": "wallet_balances_match",
        "currency": "INR",
        "wallet_id": str(SYS_INR_ID),
        "expected": -10_000,
        "actual": 0,
    }


def test_reconciliation_detects_direct_currency_and_unbalanced_tampering(security_db):
    bad_txn_id = "20000000-0000-4000-8000-000000000099"
    with closing(sqlite3.connect(security_db)) as conn, conn:
        conn.execute(
            "INSERT INTO transactions (id, type, created_at) VALUES (?, 'DEPOSIT', ?)",
            (bad_txn_id, CREATED_AT),
        )
        conn.execute(
            "INSERT INTO ledger_entries "
            "(txn_id, wallet_id, direction, amount_minor, currency, created_at) "
            "VALUES (?, ?, 'CREDIT', 250, 'INR', ?)",
            (bad_txn_id, str(BOB_INR_ID), CREATED_AT),
        )
        conn.execute(
            "UPDATE wallets SET currency = 'USD' WHERE id = ?",
            (str(BOB_INR_ID),),
        )

    with TestClient(create_app()) as client:
        report = client.get("/admin/reconcile", headers=ADMIN_AUTH)

    assert report.status_code == 200
    body = report.json()
    assert body["ok"] is False
    assert body["checks"] == {
        "currencies_balanced": False,
        "transactions_valid": False,
        "wallet_balances_match": False,
        "entry_currencies_match": False,
    }
