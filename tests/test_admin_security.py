"""D04 admin security, race/replay, error-sanitization, and tamper-detection suite."""

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
