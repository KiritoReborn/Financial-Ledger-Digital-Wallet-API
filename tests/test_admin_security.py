"""D04 admin security, race/replay, error-sanitization, and tamper-detection suite."""

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from uuid import UUID

import pytest

pytestmark = pytest.mark.usefixtures("api_environment")

TestClient = pytest.importorskip(
    "fastapi.testclient", reason="API checks require backend[dev]."
).TestClient
create_app = pytest.importorskip(
    "app.main", reason="Backend package is required."
).create_app
admin_mod = pytest.importorskip(
    "app.api.admin", reason="Backend package is required."
)

ADMIN_TOKEN = "test-only-token"
ADMIN_KEY = "test-only-key"
ADMIN_AUTH = {"Authorization": f"Bearer {ADMIN_TOKEN}", "X-Admin-Key": ADMIN_KEY}
UNAUTHENTICATED_BODY = {
    "error": {
        "code": "UNAUTHENTICATED",
        "message": "Authentication is required.",
        "details": None,
    }
}
SAMPLE_TXN_ID = UUID("20000000-0000-4000-8000-000000000001")


def _seed_live_ledger(client) -> dict[str, str]:
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
            "Idempotency-Key": "sec-seed-dep",
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
            "Idempotency-Key": "sec-seed-xfer",
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
def test_missing_or_invalid_admin_credentials_rejected_on_both_endpoints(headers):
    with TestClient(create_app()) as client:
        data = _seed_live_ledger(client)
        rec = client.get("/admin/reconcile", headers=headers)
        rev = client.post(
            f"/transactions/{data['transfer_id']}/reverse",
            headers={**headers, "Idempotency-Key": "auth-check"},
        )

    for resp in (rec, rev):
        assert resp.status_code == 401
        assert resp.json() == UNAUTHENTICATED_BODY
        assert resp.headers["www-authenticate"] == "Bearer"


def test_admin_auth_uses_constant_time_hmac_without_short_circuit(monkeypatch):
    calls: list[tuple[int, int]] = []
    real_compare = admin_mod.hmac.compare_digest

    def spy_compare(left, right):
        calls.append((len(left), len(right)))
        return real_compare(left, right)

    monkeypatch.setattr(admin_mod.hmac, "compare_digest", spy_compare)

    with TestClient(create_app()) as client:
        calls.clear()
        rec = client.get(
            "/admin/reconcile",
            headers={"Authorization": "Bearer wrong", "X-Admin-Key": "wrong-key"},
        )
        assert rec.status_code == 401
        assert calls == [(32, 32), (32, 32)]

        calls.clear()
        rev = client.post(
            f"/transactions/{SAMPLE_TXN_ID}/reverse",
            headers={
                "Authorization": "Bearer wrong",
                "X-Admin-Key": "wrong-key",
                "Idempotency-Key": "spy-key",
            },
        )
        assert rev.status_code == 401
        assert calls == [(32, 32), (32, 32)]


@pytest.mark.parametrize("unset_var", ["ADMIN_TOKEN", "ADMIN_KEY"])
def test_startup_refuses_missing_admin_secrets(monkeypatch, unset_var):
    monkeypatch.setenv(unset_var, "")
    with pytest.raises(ValueError, match=unset_var), TestClient(create_app()):
        pytest.fail("Startup accepted missing admin secret")


@pytest.mark.parametrize("include_admin_key", [False, True])
def test_non_admin_user_token_rejected_on_both_admin_endpoints(include_admin_key):
    app = create_app()
    with TestClient(app) as client:
        data = _seed_live_ledger(client)

        with app.state.database.transaction(write=False) as conn:
            tx_count_before = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
            balances_before = conn.execute(
                "SELECT id, balance_minor FROM wallets ORDER BY id"
            ).fetchall()

        headers = {"Authorization": f"Bearer {data['alice_token']}"}
        if include_admin_key:
            headers["X-Admin-Key"] = ADMIN_KEY

        rec = client.get("/admin/reconcile", headers=headers)
        rev = client.post(
            f"/transactions/{data['transfer_id']}/reverse",
            headers={**headers, "Idempotency-Key": "non-admin-attempt"},
        )

        with app.state.database.transaction(write=False) as conn:
            tx_count_after = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
            balances_after = conn.execute(
                "SELECT id, balance_minor FROM wallets ORDER BY id"
            ).fetchall()

    assert rec.status_code == 401
    assert rev.status_code == 401
    assert rec.json() == UNAUTHENTICATED_BODY
    assert rev.json() == UNAUTHENTICATED_BODY
    assert tx_count_after == tx_count_before
    assert balances_after == balances_before


def test_sequential_replay_and_second_key_rejection():
    with TestClient(create_app()) as client:
        data = _seed_live_ledger(client)
        first = client.post(
            f"/transactions/{data['transfer_id']}/reverse",
            headers={**ADMIN_AUTH, "Idempotency-Key": "seq-rev-1"},
        )
        replay = client.post(
            f"/transactions/{data['transfer_id']}/reverse",
            headers={**ADMIN_AUTH, "Idempotency-Key": "seq-rev-1"},
        )
        second = client.post(
            f"/transactions/{data['transfer_id']}/reverse",
            headers={**ADMIN_AUTH, "Idempotency-Key": "seq-rev-2"},
        )
        rec = client.get("/admin/reconcile", headers=ADMIN_AUTH)

    assert first.status_code == 201
    assert first.headers["idempotent-replayed"] == "false"
    assert replay.status_code == 201
    assert replay.headers["idempotent-replayed"] == "true"
    assert replay.json() == first.json()
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "ALREADY_REVERSED"
    assert rec.status_code == 200 and rec.json()["ok"] is True


def test_concurrent_double_reversal_different_keys_allows_only_one():
    app = create_app()
    with TestClient(app) as setup_client:
        data = _seed_live_ledger(setup_client)

    barrier = threading.Barrier(2)

    def send_reverse(key: str):
        with TestClient(create_app()) as worker:
            barrier.wait(timeout=5)
            return worker.post(
                f"/transactions/{data['transfer_id']}/reverse",
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

    assert sorted([r1.status_code, r2.status_code]) == [201, 409]
    rejected = r1 if r1.status_code == 409 else r2
    assert rejected.json()["error"]["code"] == "ALREADY_REVERSED"

    with app.state.database.transaction(write=False) as conn:
        reversals = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE type = 'REVERSAL'"
        ).fetchone()[0]
        assert reversals == 1

    with TestClient(create_app()) as client:
        assert client.get("/admin/reconcile", headers=ADMIN_AUTH).json()["ok"] is True


def test_concurrent_same_key_reversal_creates_once_and_replays():
    app = create_app()
    with TestClient(app) as setup_client:
        data = _seed_live_ledger(setup_client)

    barrier = threading.Barrier(2)

    def send_reverse():
        with TestClient(create_app()) as worker:
            barrier.wait(timeout=5)
            return worker.post(
                f"/transactions/{data['transfer_id']}/reverse",
                headers={**ADMIN_AUTH, "Idempotency-Key": "concurrent-same-key"},
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        r1, r2 = [fut.result() for fut in (pool.submit(send_reverse), pool.submit(send_reverse))]

    assert (r1.status_code, r2.status_code) == (201, 201)
    assert r1.json() == r2.json()
    assert sorted(
        [r1.headers["idempotent-replayed"], r2.headers["idempotent-replayed"]]
    ) == ["false", "true"]

    with app.state.database.transaction(write=False) as conn:
        reversals = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE type = 'REVERSAL'"
        ).fetchone()[0]
        assert reversals == 1

    with TestClient(create_app()) as client:
        assert client.get("/admin/reconcile", headers=ADMIN_AUTH).json()["ok"] is True


def test_unexpected_errors_leak_no_sql_paths_traces_or_secrets():
    probe_header = "idem-01"
    app = create_app()
    db_path = app.state.database.path
    sensitive_msg = (
        f"Traceback SELECT * FROM users WHERE path={db_path} "
        f"token={ADMIN_TOKEN} key={ADMIN_KEY} idem={probe_header}"
    )

    @contextmanager
    def exploding_ctx():
        raise RuntimeError(sensitive_msg)
        yield  # pragma: no cover

    with TestClient(app) as client:
        app.state.read_snapshot = exploding_ctx
        app.state.write_transaction = exploding_ctx
        rec = client.get("/admin/reconcile", headers=ADMIN_AUTH)
        rev = client.post(
            f"/transactions/{SAMPLE_TXN_ID}/reverse",
            headers={**ADMIN_AUTH, "Idempotency-Key": probe_header},
        )

    expected = {"error": {"code": "INTERNAL_ERROR", "message": "An internal error occurred."}}
    for resp in (rec, rev):
        assert resp.status_code == 500
        assert resp.json() == expected
        for forbidden in (
            "Traceback",
            "SELECT",
            str(db_path),
            ADMIN_TOKEN,
            ADMIN_KEY,
            probe_header,
        ):
            assert forbidden not in resp.text


def test_sqlite_busy_sanitizes_internal_details():
    app = create_app()
    db_path = app.state.database.path

    @contextmanager
    def busy_ctx():
        err = sqlite3.OperationalError(
            f"database {db_path} locked during SELECT * FROM wallets"
        )
        err.sqlite_errorcode = sqlite3.SQLITE_BUSY
        raise err
        yield  # pragma: no cover

    with TestClient(app) as client:
        app.state.read_snapshot = busy_ctx
        app.state.write_transaction = busy_ctx
        rec = client.get("/admin/reconcile", headers=ADMIN_AUTH)
        rev = client.post(
            f"/transactions/{SAMPLE_TXN_ID}/reverse",
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
        assert str(db_path) not in resp.text
