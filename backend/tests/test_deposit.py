"""B02 POST /wallets/{id}/deposit over the real app and migrated SQLite (FR-1.6, FR-2.4 to FR-2.9).

Startup supplies the system wallets used by the posting service.
"""

from uuid import UUID, uuid4

import pytest

TestClient = pytest.importorskip("fastapi.testclient").TestClient
create_app = pytest.importorskip("app.main").create_app

ADMIN_TOKEN, ADMIN_KEY = "deposit-test-admin-token", "deposit-test-admin-key"
TRANSACTION_KEYS = {"id", "type", "description", "reverses_txn_id", "created_at", "entries"}
ENTRY_KEYS = {"id", "txn_id", "wallet_id", "type", "direction", "amount_minor", "currency", "created_at"}


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "deposit.sqlite3"))
    monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)
    monkeypatch.setenv("ADMIN_KEY", ADMIN_KEY)
    return create_app()


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


def register(client, name):
    response = client.post("/users", json={"name": name, "email": f"{name}@example.test"})
    assert response.status_code == 201
    user = response.json()
    return user["id"], {"Authorization": f"Bearer {user['token']}"}


def add_wallet(app, currency, user_id=None):
    wallet_id = str(uuid4())
    with app.state.database.transaction() as conn:
        conn.execute(
            "INSERT INTO wallets (id, user_id, currency, balance_minor, is_system, created_at) "
            "VALUES (?, ?, ?, 0, ?, '2026-11-25T00:00:00Z')",
            (wallet_id, user_id, currency, int(user_id is None)),
        )
    return wallet_id


def system_wallet(app, currency):
    with app.state.database.transaction(write=False) as conn:
        return conn.execute("SELECT id FROM wallets WHERE currency=? AND is_system=1", (currency,)).fetchone()[0]


@pytest.fixture
def ledger(app, client):
    """Alice and Bob each own an INR wallet; INR and JPY system wallets exist."""
    alice, alice_auth = register(client, "alice")
    bob, bob_auth = register(client, "bob")
    return {
        "system_inr": system_wallet(app, "INR"),
        "system_jpy": system_wallet(app, "JPY"),
        "alice_inr": add_wallet(app, "INR", alice),
        "bob_inr": add_wallet(app, "INR", bob),
        "alice": alice_auth,
        "bob": bob_auth,
        "alice_id": alice,
    }


def deposit(client, wallet_id, auth, amount=100, key="deposit-key-1", **extra_headers):
    headers = {**auth, **extra_headers}
    if key is not None:
        headers["Idempotency-Key"] = key
    return client.post(f"/wallets/{wallet_id}/deposit", json={"amount_minor": amount}, headers=headers)


def state(app):
    with app.state.database.transaction(write=False) as conn:
        return [
            conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
            for table in ("wallets", "transactions", "ledger_entries", "idempotency_keys")
        ]


def balance(app, wallet_id):
    with app.state.database.transaction(write=False) as conn:
        return conn.execute(
            "SELECT balance_minor FROM wallets WHERE id = ?", (wallet_id,)
        ).fetchone()[0]


def count(app, table):
    with app.state.database.transaction(write=False) as conn:
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code


# FR-1.6: a deposit is one DEPOSIT transaction with a system debit and a wallet credit


def test_deposit_credits_wallet_and_returns_the_transaction(app, client, ledger):
    response = deposit(client, ledger["alice_inr"], ledger["alice"], amount=2500)

    assert response.status_code == 201, response.text
    assert response.headers["Idempotent-Replayed"] == "false"
    assert UUID(response.headers["X-Request-ID"]).version == 4
    body = response.json()
    assert set(body) == TRANSACTION_KEYS
    assert UUID(body["id"]).version == 4
    assert (body["type"], body["description"], body["reverses_txn_id"]) == ("DEPOSIT", None, None)
    assert body["created_at"].endswith("Z")
    debit, credit = body["entries"]
    assert set(debit) == set(credit) == ENTRY_KEYS
    assert (debit["wallet_id"], debit["direction"]) == (ledger["system_inr"], "DEBIT")
    assert (credit["wallet_id"], credit["direction"]) == (ledger["alice_inr"], "CREDIT")
    for entry in (debit, credit):
        assert (entry["txn_id"], entry["type"]) == (body["id"], "DEPOSIT")
        assert (entry["amount_minor"], entry["currency"]) == (2500, "INR")
        assert isinstance(entry["id"], int)
    assert balance(app, ledger["alice_inr"]) == 2500
    assert balance(app, ledger["system_inr"]) == -2500


def test_deposit_uses_the_system_wallet_of_the_wallet_currency(app, client, ledger):
    alice_jpy = add_wallet(app, "JPY", ledger["alice_id"])
    response = deposit(client, alice_jpy, ledger["alice"], amount=500)

    assert response.status_code == 201, response.text
    assert {entry["currency"] for entry in response.json()["entries"]} == {"JPY"}
    assert response.json()["entries"][0]["wallet_id"] == ledger["system_jpy"]
    assert (balance(app, alice_jpy), balance(app, ledger["system_inr"])) == (500, 0)


def test_ledger_reconciles_after_deposits(client, ledger):
    deposit(client, ledger["alice_inr"], ledger["alice"], amount=700, key="a")
    deposit(client, ledger["bob_inr"], ledger["bob"], amount=300, key="b")

    response = client.get(
        "/admin/reconcile",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}", "X-Admin-Key": ADMIN_KEY},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True


# FR-2.7 and FR-2.8: replay and conflict over HTTP


def test_same_key_and_body_replays_without_a_second_deposit(app, client, ledger):
    first = deposit(client, ledger["alice_inr"], ledger["alice"])
    replay = deposit(client, ledger["alice_inr"], ledger["alice"])

    assert replay.status_code == first.status_code == 201
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert replay.json() == first.json()
    assert count(app, "transactions") == 1
    assert balance(app, ledger["alice_inr"]) == 100


def test_same_key_with_another_amount_conflicts_and_changes_nothing(app, client, ledger):
    deposit(client, ledger["alice_inr"], ledger["alice"], amount=100)
    before = state(app)

    response = deposit(client, ledger["alice_inr"], ledger["alice"], amount=999)

    assert_error(response, 422, "IDEMPOTENCY_CONFLICT")
    assert state(app) == before


def test_same_key_on_another_wallet_conflicts(app, client, ledger):
    alice_second = add_wallet(app, "JPY", ledger["alice_id"])
    deposit(client, ledger["alice_inr"], ledger["alice"], key="shared")

    assert_error(deposit(client, alice_second, ledger["alice"], key="shared"), 422,
                 "IDEMPOTENCY_CONFLICT")


def test_keys_are_scoped_per_user(app, client, ledger):
    deposit(client, ledger["alice_inr"], ledger["alice"], key="shared")
    response = deposit(client, ledger["bob_inr"], ledger["bob"], key="shared")

    assert response.status_code == 201
    assert response.headers["Idempotent-Replayed"] == "false"
    assert count(app, "transactions") == 2


# FR-2.4: Idempotency-Key header


@pytest.mark.parametrize("key", [None, "", "   "])
def test_missing_or_blank_key_is_400_and_changes_nothing(app, client, ledger, key):
    before = state(app)
    assert_error(deposit(client, ledger["alice_inr"], ledger["alice"], key=key), 400,
                 "IDEMPOTENCY_KEY_MISSING")
    assert state(app) == before


@pytest.mark.parametrize("key", ["has space", "a/b", "x" * 129, "semi;colon"])
def test_invalid_key_is_422_and_changes_nothing(app, client, ledger, key):
    before = state(app)
    assert_error(deposit(client, ledger["alice_inr"], ledger["alice"], key=key), 422,
                 "VALIDATION_ERROR")
    assert state(app) == before


# Authentication and ownership (FR-1.5, FR-1.6)


@pytest.mark.parametrize("auth", [{}, {"Authorization": "Bearer wrong-token"}, {"Authorization": "Basic x"}])
def test_missing_or_invalid_token_is_401(app, client, ledger, auth):
    before = state(app)
    assert_error(deposit(client, ledger["alice_inr"], auth), 401, "UNAUTHENTICATED")
    assert state(app) == before


def test_another_users_wallet_is_403(app, client, ledger):
    before = state(app)
    assert_error(deposit(client, ledger["bob_inr"], ledger["alice"]), 403, "FORBIDDEN")
    assert state(app) == before


def test_system_wallet_cannot_be_a_deposit_target(app, client, ledger):
    assert_error(deposit(client, ledger["system_inr"], ledger["alice"]), 403, "FORBIDDEN")


def test_unknown_wallet_is_404(client, ledger):
    assert_error(deposit(client, str(uuid4()), ledger["alice"]), 404, "NOT_FOUND")


@pytest.mark.parametrize("wallet_id", ["not-a-uuid", "123", "00000000-0000-4000-8000"])
def test_malformed_wallet_id_is_422(client, ledger, wallet_id):
    assert_error(deposit(client, wallet_id, ledger["alice"]), 422, "VALIDATION_ERROR")


# TQ-6 and security tests: integer minor units only


@pytest.mark.parametrize(
    "body",
    [
        {"amount_minor": 0},
        {"amount_minor": -100},
        {"amount_minor": 10.5},
        {"amount_minor": 100.0},
        {"amount_minor": "100"},
        {"amount_minor": True},
        {"amount_minor": None},
        {"amount_minor": 10**12 + 1},
        {},
        {"amount_minor": 100, "currency": "INR"},
    ],
)
def test_invalid_amount_or_body_is_422_and_changes_nothing(app, client, ledger, body):
    before = state(app)
    response = client.post(
        f"/wallets/{ledger['alice_inr']}/deposit",
        json=body,
        headers={**ledger["alice"], "Idempotency-Key": "amount-check"},
    )
    assert_error(response, 422, "VALIDATION_ERROR")
    assert state(app) == before


def test_largest_allowed_amount_is_accepted(app, client, ledger):
    response = deposit(client, ledger["alice_inr"], ledger["alice"], amount=10**12)
    assert response.status_code == 201
    assert balance(app, ledger["alice_inr"]) == 10**12


# FR-2.9: a failed deposit stores no key, so the same key works once the problem is fixed


def test_failed_deposit_stores_no_key_and_same_key_can_retry(app, client, ledger):
    alice_usd = add_wallet(app, "USD", ledger["alice_id"])
    with app.state.database.transaction() as conn:
        conn.execute("DELETE FROM wallets WHERE currency='USD' AND is_system=1")
    before = state(app)

    failed = deposit(client, alice_usd, ledger["alice"], key="retry-me")

    assert_error(failed, 500, "INTERNAL_ERROR")
    assert state(app) == before
    add_wallet(app, "USD")
    retried = deposit(client, alice_usd, ledger["alice"], key="retry-me")
    assert retried.status_code == 201
    assert retried.headers["Idempotent-Replayed"] == "false"
    assert balance(app, alice_usd) == 100
