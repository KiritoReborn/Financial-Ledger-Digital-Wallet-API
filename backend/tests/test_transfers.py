"""B03 POST /transfers over the real app and migrated SQLite (FR-1.5, FR-1.7, FR-2.4 to FR-2.9).

Users, wallets and starting balances come from the real POST /users,
POST /wallets and POST /wallets/{id}/deposit routes.
"""

from uuid import UUID, uuid1, uuid4

import pytest

TestClient = pytest.importorskip("fastapi.testclient").TestClient
create_app = pytest.importorskip("app.main").create_app

ADMIN_TOKEN, ADMIN_KEY = "transfer-test-admin-token", "transfer-test-admin-key"
TRANSFER_KEYS = {
    "id", "type", "from_wallet_id", "to_wallet_id", "amount_minor", "currency", "description",
    "created_at",
}


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "transfers.sqlite3"))
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
    return {"Authorization": f"Bearer {response.json()['token']}"}


def create_wallet(client, auth, currency):
    response = client.post("/wallets", json={"currency": currency}, headers=auth)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def fund(client, wallet_id, auth, amount):
    response = client.post(
        f"/wallets/{wallet_id}/deposit",
        json={"amount_minor": amount},
        headers={**auth, "Idempotency-Key": f"fund-{uuid4()}"},
    )
    assert response.status_code == 201, response.text


@pytest.fixture
def ledger(client):
    """Alice has INR 1000 and an empty JPY wallet; Bob has empty INR and JPY wallets."""
    alice, bob = register(client, "alice"), register(client, "bob")
    wallets = {
        "alice_inr": create_wallet(client, alice, "INR"),
        "alice_jpy": create_wallet(client, alice, "JPY"),
        "bob_inr": create_wallet(client, bob, "INR"),
        "bob_jpy": create_wallet(client, bob, "JPY"),
    }
    fund(client, wallets["alice_inr"], alice, 1000)
    return {**wallets, "alice": alice, "bob": bob}


def transfer_body(ledger, source="alice_inr", target="bob_inr", amount=100, currency="INR", **extra):
    return {
        "from_wallet_id": ledger[source],
        "to_wallet_id": ledger[target],
        "amount_minor": amount,
        "currency": currency,
        **extra,
    }


def transfer(client, body, auth, key="transfer-key-1"):
    headers = dict(auth)
    if key is not None:
        headers["Idempotency-Key"] = key
    return client.post("/transfers", json=body, headers=headers)


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


def transfer_count(app):
    with app.state.database.transaction(write=False) as conn:
        return conn.execute("SELECT count(*) FROM transactions WHERE type = 'TRANSFER'").fetchone()[0]


def system_wallet(app, currency):
    with app.state.database.transaction(write=False) as conn:
        return conn.execute(
            "SELECT id FROM wallets WHERE is_system = 1 AND currency = ?", (currency,)
        ).fetchone()[0]


def assert_rejected(app, response, before, status, code):
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code
    assert state(app) == before


# FR-1.7: one balanced TRANSFER between two user wallets


def test_transfer_moves_funds_and_returns_the_transfer(app, client, ledger):
    response = transfer(client, transfer_body(ledger, amount=250, description="Rent"), ledger["alice"])

    assert response.status_code == 201, response.text
    assert response.headers["Idempotent-Replayed"] == "false"
    body = response.json()
    assert set(body) == TRANSFER_KEYS
    assert UUID(body["id"]).version == 4
    assert body["type"] == "TRANSFER"
    assert (body["from_wallet_id"], body["to_wallet_id"]) == (ledger["alice_inr"], ledger["bob_inr"])
    assert (body["amount_minor"], body["currency"], body["description"]) == (250, "INR", "Rent")
    assert body["created_at"].endswith("Z")
    assert (balance(app, ledger["alice_inr"]), balance(app, ledger["bob_inr"])) == (750, 250)


def test_transfer_writes_one_debit_and_one_credit(app, client, ledger):
    txn_id = transfer(client, transfer_body(ledger), ledger["alice"]).json()["id"]

    with app.state.database.transaction(write=False) as conn:
        entries = conn.execute(
            "SELECT wallet_id, direction, amount_minor, currency FROM ledger_entries "
            "WHERE txn_id = ? ORDER BY id",
            (txn_id,),
        ).fetchall()
    assert entries == [
        (ledger["alice_inr"], "DEBIT", 100, "INR"),
        (ledger["bob_inr"], "CREDIT", 100, "INR"),
    ]


def test_description_is_optional_and_null_when_omitted(client, ledger):
    response = transfer(client, transfer_body(ledger), ledger["alice"])
    assert response.json()["description"] is None


def test_whole_balance_can_be_sent(app, client, ledger):
    response = transfer(client, transfer_body(ledger, amount=1000), ledger["alice"])
    assert response.status_code == 201
    assert balance(app, ledger["alice_inr"]) == 0


def test_ledger_reconciles_after_transfers(client, ledger):
    transfer(client, transfer_body(ledger, amount=300), ledger["alice"], key="a")
    transfer(client, transfer_body(ledger, amount=200), ledger["alice"], key="b")
    transfer(client, transfer_body(ledger, "bob_inr", "alice_inr", 50), ledger["bob"], key="c")

    response = client.get(
        "/admin/reconcile",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}", "X-Admin-Key": ADMIN_KEY},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True


# Business rules: each rejection changes nothing and stores no key


def test_insufficient_funds_is_422(app, client, ledger):
    before = state(app)
    response = transfer(client, transfer_body(ledger, amount=1001), ledger["alice"])
    assert_rejected(app, response, before, 422, "INSUFFICIENT_FUNDS")


def test_empty_wallet_cannot_send(app, client, ledger):
    before = state(app)
    response = transfer(client, transfer_body(ledger, "bob_inr", "alice_inr", 1), ledger["bob"])
    assert_rejected(app, response, before, 422, "INSUFFICIENT_FUNDS")


def test_receiver_in_another_currency_is_currency_mismatch(app, client, ledger):
    before = state(app)
    response = transfer(client, transfer_body(ledger, target="bob_jpy"), ledger["alice"])
    assert_rejected(app, response, before, 422, "CURRENCY_MISMATCH")


def test_request_currency_must_match_the_wallets(app, client, ledger):
    before = state(app)
    response = transfer(client, transfer_body(ledger, currency="USD"), ledger["alice"])
    assert_rejected(app, response, before, 422, "CURRENCY_MISMATCH")


def test_same_wallet_is_422(app, client, ledger):
    before = state(app)
    response = transfer(client, transfer_body(ledger, target="alice_inr"), ledger["alice"])
    assert_rejected(app, response, before, 422, "VALIDATION_ERROR")


def test_own_wallets_in_another_currency_still_mismatch(app, client, ledger):
    before = state(app)
    response = transfer(client, transfer_body(ledger, target="alice_jpy"), ledger["alice"])
    assert_rejected(app, response, before, 422, "CURRENCY_MISMATCH")


def test_system_wallet_cannot_receive_a_transfer(app, client, ledger):
    ledger = {**ledger, "system_inr": system_wallet(app, "INR")}
    before = state(app)
    response = transfer(client, transfer_body(ledger, target="system_inr"), ledger["alice"])
    assert_rejected(app, response, before, 422, "VALIDATION_ERROR")


def test_rejected_transfer_stores_no_key_and_same_key_can_retry(app, client, ledger):
    failed = transfer(client, transfer_body(ledger, amount=1500), ledger["alice"], key="retry-me")
    assert failed.status_code == 422

    fund(client, ledger["alice_inr"], ledger["alice"], 500)
    retried = transfer(client, transfer_body(ledger, amount=1500), ledger["alice"], key="retry-me")

    assert retried.status_code == 201
    assert retried.headers["Idempotent-Replayed"] == "false"
    assert balance(app, ledger["bob_inr"]) == 1500


# FR-1.5: the sender must be the caller's; the receiver may be anyone's


def test_sending_from_another_users_wallet_is_403(app, client, ledger):
    before = state(app)
    response = transfer(client, transfer_body(ledger, "alice_inr", "bob_inr"), ledger["bob"])
    assert_rejected(app, response, before, 403, "FORBIDDEN")


def test_system_wallet_cannot_be_a_sender(app, client, ledger):
    ledger = {**ledger, "system_inr": system_wallet(app, "INR")}
    before = state(app)
    response = transfer(client, transfer_body(ledger, source="system_inr"), ledger["alice"])
    assert_rejected(app, response, before, 403, "FORBIDDEN")


@pytest.mark.parametrize("missing", ["from_wallet_id", "to_wallet_id"])
def test_unknown_wallet_is_404(app, client, ledger, missing):
    body = {**transfer_body(ledger), missing: str(uuid4())}
    before = state(app)
    assert_rejected(app, transfer(client, body, ledger["alice"]), before, 404, "NOT_FOUND")


@pytest.mark.parametrize(
    "auth", [{}, {"Authorization": "Bearer wrong-token"}, {"Authorization": "Basic x"}]
)
def test_missing_or_invalid_token_is_401(app, client, ledger, auth):
    before = state(app)
    response = transfer(client, transfer_body(ledger), auth)
    assert_rejected(app, response, before, 401, "UNAUTHENTICATED")


# FR-2.7 and FR-2.8: replay and conflict over HTTP


def test_same_key_and_body_replays_without_a_second_transfer(app, client, ledger):
    first = transfer(client, transfer_body(ledger), ledger["alice"])
    replay = transfer(client, transfer_body(ledger), ledger["alice"])

    assert replay.status_code == first.status_code == 201
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert replay.json() == first.json()
    assert transfer_count(app) == 1
    assert (balance(app, ledger["alice_inr"]), balance(app, ledger["bob_inr"])) == (900, 100)


def test_explicit_null_description_replays_like_an_omitted_one(client, ledger):
    transfer(client, transfer_body(ledger), ledger["alice"])
    replay = transfer(client, transfer_body(ledger, description=None), ledger["alice"])
    assert replay.headers["Idempotent-Replayed"] == "true"


@pytest.mark.parametrize(
    "change",
    [{"amount_minor": 101}, {"description": "changed"}, {"to_wallet_id": "alice_jpy"}],
)
def test_same_key_with_another_body_conflicts_and_changes_nothing(app, client, ledger, change):
    transfer(client, transfer_body(ledger), ledger["alice"])
    before = state(app)
    body = {**transfer_body(ledger), **change}
    if "to_wallet_id" in change:
        body["to_wallet_id"] = ledger[change["to_wallet_id"]]

    response = transfer(client, body, ledger["alice"])

    assert_rejected(app, response, before, 422, "IDEMPOTENCY_CONFLICT")


def test_keys_are_scoped_per_operation(app, client, ledger):
    """The key table is unique on (user, scope, key), so a deposit key does not block a transfer."""
    client.post(
        f"/wallets/{ledger['alice_inr']}/deposit",
        json={"amount_minor": 5},
        headers={**ledger["alice"], "Idempotency-Key": "shared"},
    )
    response = transfer(client, transfer_body(ledger), ledger["alice"], key="shared")
    assert response.status_code == 201
    assert response.headers["Idempotent-Replayed"] == "false"


def test_keys_are_scoped_per_user(app, client, ledger):
    fund(client, ledger["bob_inr"], ledger["bob"], 100)
    transfer(client, transfer_body(ledger), ledger["alice"], key="shared")
    response = transfer(
        client, transfer_body(ledger, "bob_inr", "alice_inr"), ledger["bob"], key="shared"
    )
    assert response.status_code == 201
    assert response.headers["Idempotent-Replayed"] == "false"
    assert transfer_count(app) == 2


# FR-2.4: Idempotency-Key header


@pytest.mark.parametrize("key", [None, "", "   "])
def test_missing_or_blank_key_is_400_and_changes_nothing(app, client, ledger, key):
    before = state(app)
    response = transfer(client, transfer_body(ledger), ledger["alice"], key=key)
    assert_rejected(app, response, before, 400, "IDEMPOTENCY_KEY_MISSING")


@pytest.mark.parametrize("key", ["has space", "a/b", "x" * 129])
def test_invalid_key_is_422_and_changes_nothing(app, client, ledger, key):
    before = state(app)
    response = transfer(client, transfer_body(ledger), ledger["alice"], key=key)
    assert_rejected(app, response, before, 422, "VALIDATION_ERROR")


# TQ-4 and TQ-6: malformed bodies never reach the ledger


@pytest.mark.parametrize(
    "change",
    [
        {"amount_minor": 0},
        {"amount_minor": -100},
        {"amount_minor": 10.5},
        {"amount_minor": 100.0},
        {"amount_minor": "100"},
        {"amount_minor": True},
        {"amount_minor": None},
        {"amount_minor": 10**12 + 1},
        {"currency": "EUR"},
        {"currency": "inr"},
        {"currency": None},
        {"from_wallet_id": "not-a-uuid"},
        {"to_wallet_id": "123"},
        {"to_wallet_id": None},
        {"from_wallet_id": str(uuid1())},
        {"description": "x" * 201},
        {"description": 5},
        {"note": "unknown field"},
    ],
)
def test_invalid_body_is_422_and_changes_nothing(app, client, ledger, change):
    before = state(app)
    response = transfer(client, {**transfer_body(ledger), **change}, ledger["alice"])
    assert_rejected(app, response, before, 422, "VALIDATION_ERROR")


@pytest.mark.parametrize("field", ["from_wallet_id", "to_wallet_id", "amount_minor", "currency"])
def test_missing_required_field_is_422(app, client, ledger, field):
    body = transfer_body(ledger)
    del body[field]
    before = state(app)
    assert_rejected(app, transfer(client, body, ledger["alice"]), before, 422, "VALIDATION_ERROR")


def test_description_at_the_limit_is_accepted(client, ledger):
    response = transfer(client, transfer_body(ledger, description="x" * 200), ledger["alice"])
    assert response.status_code == 201
