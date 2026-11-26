"""B04 exactly-once and negative suite over HTTP (FR-2.4 to FR-2.10, TQ-3, TQ-4, TQ-5).

Every test drives the real app through POST /users, POST /wallets, the deposit
route and POST /transfers on a fresh temporary SQLite file. Concurrent cases
send requests from many threads at once; each request opens its own connection
and BEGIN IMMEDIATE transaction, as it would under a real server.
"""

import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from uuid import UUID, uuid4

import pytest

TestClient = pytest.importorskip("fastapi.testclient").TestClient
create_app = pytest.importorskip("app.main").create_app
transfer_service = pytest.importorskip("app.services.transfers")

ADMIN_TOKEN, ADMIN_KEY = "exactly-once-admin-token", "exactly-once-admin-key"


@pytest.fixture
def database_path(tmp_path, monkeypatch):
    path = tmp_path / "exactly-once.sqlite3"
    monkeypatch.setenv("DATABASE_PATH", str(path))
    monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)
    monkeypatch.setenv("ADMIN_KEY", ADMIN_KEY)
    return path


@pytest.fixture
def client(database_path):
    with TestClient(create_app()) as client:
        yield client


def register(client, name):
    response = client.post("/users", json={"name": name, "email": f"{name}@example.test"})
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['token']}"}


def create_wallet(client, auth, currency="INR"):
    response = client.post("/wallets", json={"currency": currency}, headers=auth)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def deposit(client, wallet_id, auth, amount, key):
    return client.post(
        f"/wallets/{wallet_id}/deposit",
        json={"amount_minor": amount},
        headers={**auth, "Idempotency-Key": key},
    )


def transfer(client, auth, source, target, amount, key, **extra):
    body = {
        "from_wallet_id": source,
        "to_wallet_id": target,
        "amount_minor": amount,
        "currency": "INR",
        **extra,
    }
    return client.post("/transfers", json=body, headers={**auth, "Idempotency-Key": key})


@pytest.fixture
def ledger(client):
    """Alice holds INR 100,000; Bob has an empty INR wallet."""
    alice, bob = register(client, "alice"), register(client, "bob")
    wallets = {"alice_inr": create_wallet(client, alice), "bob_inr": create_wallet(client, bob)}
    assert deposit(client, wallets["alice_inr"], alice, 100_000, "opening").status_code == 201
    return {**wallets, "alice": alice, "bob": bob}


def query(database_path, sql, *params):
    with closing(sqlite3.connect(database_path)) as conn:
        return conn.execute(sql, params).fetchall()


def balance(database_path, wallet_id):
    return query(database_path, "SELECT balance_minor FROM wallets WHERE id = ?", wallet_id)[0][0]


def count(database_path, table, where="1"):
    return query(database_path, f"SELECT count(*) FROM {table} WHERE {where}")[0][0]


def snapshot(database_path):
    return [
        query(database_path, f"SELECT * FROM {table} ORDER BY 1")
        for table in ("wallets", "transactions", "ledger_entries", "idempotency_keys")
    ]


def assert_reconciled(client, database_path):
    response = client.get(
        "/admin/reconcile",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}", "X-Admin-Key": ADMIN_KEY},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert query(database_path, "PRAGMA integrity_check") == [("ok",)]


def run_together(count_, send):
    """Release all workers at once and return their responses in worker order."""
    barrier = threading.Barrier(count_)

    def worker(index):
        barrier.wait()
        return send(index)

    with ThreadPoolExecutor(max_workers=count_) as pool:
        return list(pool.map(worker, range(count_)))


# TQ-4: 50 competing transfers from one wallet never overdraw it


def test_fifty_competing_transfers_commit_exactly_what_the_balance_allows(
    client, database_path, ledger
):
    responses = run_together(
        50,
        lambda index: transfer(
            client, ledger["alice"], ledger["alice_inr"], ledger["bob_inr"], 3_000, f"race-{index}"
        ),
    )

    statuses = sorted(response.status_code for response in responses)
    assert statuses == [201] * 33 + [422] * 17
    rejected = [response for response in responses if response.status_code == 422]
    assert {response.json()["error"]["code"] for response in rejected} == {"INSUFFICIENT_FUNDS"}
    assert balance(database_path, ledger["alice_inr"]) == 1_000
    assert balance(database_path, ledger["bob_inr"]) == 99_000
    assert count(database_path, "transactions", "type = 'TRANSFER'") == 33
    assert count(database_path, "ledger_entries") == 2 + 33 * 2
    assert count(database_path, "idempotency_keys", "scope = 'TRANSFER'") == 33
    assert_reconciled(client, database_path)


def test_rejected_racers_can_retry_with_their_keys_once_funded(client, database_path, ledger):
    responses = run_together(
        50,
        lambda index: transfer(
            client, ledger["alice"], ledger["alice_inr"], ledger["bob_inr"], 3_000, f"race-{index}"
        ),
    )
    rejected_keys = [
        f"race-{index}" for index, response in enumerate(responses) if response.status_code == 422
    ]
    assert deposit(client, ledger["alice_inr"], ledger["alice"], 51_000, "top-up").status_code == 201

    retried = [
        transfer(client, ledger["alice"], ledger["alice_inr"], ledger["bob_inr"], 3_000, key)
        for key in rejected_keys
    ]

    assert [response.status_code for response in retried] == [201] * 17
    assert {response.headers["Idempotent-Replayed"] for response in retried} == {"false"}
    assert balance(database_path, ledger["alice_inr"]) == 1_000
    assert balance(database_path, ledger["bob_inr"]) == 150_000
    assert_reconciled(client, database_path)


# FR-2.10: concurrent requests with one key post once


@pytest.mark.parametrize("workers", [2, 10])
def test_concurrent_same_key_transfers_post_once(client, database_path, ledger, workers):
    responses = run_together(
        workers,
        lambda _: transfer(
            client, ledger["alice"], ledger["alice_inr"], ledger["bob_inr"], 500, "same-key"
        ),
    )

    assert {response.status_code for response in responses} == {201}
    replayed = sorted(response.headers["Idempotent-Replayed"] for response in responses)
    assert replayed == ["false"] + ["true"] * (workers - 1)
    assert len({json.dumps(response.json(), sort_keys=True) for response in responses}) == 1
    assert count(database_path, "transactions", "type = 'TRANSFER'") == 1
    assert balance(database_path, ledger["bob_inr"]) == 500


def test_concurrent_same_key_deposits_post_once(client, database_path, ledger):
    responses = run_together(
        10, lambda _: deposit(client, ledger["bob_inr"], ledger["bob"], 700, "same-deposit")
    )

    assert {response.status_code for response in responses} == {201}
    assert sum(response.headers["Idempotent-Replayed"] == "false" for response in responses) == 1
    assert len({response.json()["id"] for response in responses}) == 1
    assert balance(database_path, ledger["bob_inr"]) == 700


def test_concurrent_same_key_with_two_bodies_posts_only_the_winner(client, database_path, ledger):
    """Whichever body commits first owns the key; the other body always conflicts."""
    amounts = [100 if index % 2 else 200 for index in range(10)]
    responses = run_together(
        10,
        lambda index: transfer(
            client, ledger["alice"], ledger["alice_inr"], ledger["bob_inr"], amounts[index], "split"
        ),
    )

    winners = {amounts[i] for i, response in enumerate(responses) if response.status_code == 201}
    assert len(winners) == 1
    winner = winners.pop()
    for amount, response in zip(amounts, responses, strict=True):
        if amount == winner:
            assert response.status_code == 201
        else:
            assert response.status_code == 422
            assert response.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert count(database_path, "transactions", "type = 'TRANSFER'") == 1
    assert balance(database_path, ledger["bob_inr"]) == winner


def test_concurrent_different_keys_lose_no_update(client, database_path, ledger):
    responses = run_together(
        20,
        lambda index: transfer(
            client, ledger["alice"], ledger["alice_inr"], ledger["bob_inr"], 10, f"small-{index}"
        ),
    )

    assert {response.status_code for response in responses} == {201}
    assert len({response.json()["id"] for response in responses}) == 20
    assert balance(database_path, ledger["alice_inr"]) == 100_000 - 200
    assert balance(database_path, ledger["bob_inr"]) == 200
    assert_reconciled(client, database_path)


# FR-2.7: a replay returns the stored response and never re-runs the operation


def test_replay_matches_the_original_status_body_and_headers(client, ledger):
    first = transfer(client, ledger["alice"], ledger["alice_inr"], ledger["bob_inr"], 250, "k")
    replay = transfer(client, ledger["alice"], ledger["alice_inr"], ledger["bob_inr"], 250, "k")

    assert (first.status_code, replay.status_code) == (201, 201)
    assert replay.json() == first.json()
    assert (first.headers["Idempotent-Replayed"], replay.headers["Idempotent-Replayed"]) == (
        "false",
        "true",
    )
    assert replay.headers["content-type"] == first.headers["content-type"] == "application/json"
    assert replay.headers["X-Request-ID"] != first.headers["X-Request-ID"]


def test_replay_succeeds_after_the_balance_is_spent(client, database_path, ledger):
    """The stored 201 is replayed even though running the transfer again would now fail."""
    first = transfer(client, ledger["alice"], ledger["alice_inr"], ledger["bob_inr"], 100_000, "all")
    assert balance(database_path, ledger["alice_inr"]) == 0

    replay = transfer(client, ledger["alice"], ledger["alice_inr"], ledger["bob_inr"], 100_000, "all")

    assert replay.status_code == 201
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert replay.json() == first.json()
    assert balance(database_path, ledger["bob_inr"]) == 100_000


def test_replay_survives_an_application_restart(database_path, client, ledger):
    first = transfer(client, ledger["alice"], ledger["alice_inr"], ledger["bob_inr"], 400, "durable")

    with TestClient(create_app()) as restarted:
        replay = transfer(
            restarted, ledger["alice"], ledger["alice_inr"], ledger["bob_inr"], 400, "durable"
        )

    assert replay.status_code == 201
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert replay.json() == first.json()
    assert count(database_path, "transactions", "type = 'TRANSFER'") == 1


def test_key_order_and_whitespace_do_not_change_the_fingerprint(client, database_path, ledger):
    transfer(client, ledger["alice"], ledger["alice_inr"], ledger["bob_inr"], 300, "canonical")
    to_id, from_id = ledger["bob_inr"], ledger["alice_inr"]
    raw = (
        f'{{ "currency" : "INR",\n  "amount_minor": 300, "to_wallet_id": "{to_id}",'
        f' "from_wallet_id": "{from_id}" }}'
    )

    replay = client.post(
        "/transfers",
        content=raw,
        headers={**ledger["alice"], "Idempotency-Key": "canonical", "Content-Type": "application/json"},
    )

    assert replay.status_code == 201
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert count(database_path, "transactions", "type = 'TRANSFER'") == 1


def test_keys_are_case_sensitive(client, database_path, ledger):
    transfer(client, ledger["alice"], ledger["alice_inr"], ledger["bob_inr"], 10, "Key-A")
    second = transfer(client, ledger["alice"], ledger["alice_inr"], ledger["bob_inr"], 10, "key-a")

    assert second.headers["Idempotent-Replayed"] == "false"
    assert count(database_path, "transactions", "type = 'TRANSFER'") == 2


# FR-2.8: a conflicting reuse changes nothing and reveals nothing


def test_conflict_does_not_leak_the_stored_response(client, database_path, ledger):
    first = transfer(client, ledger["alice"], ledger["alice_inr"], ledger["bob_inr"], 10, "k")
    before = snapshot(database_path)

    response = transfer(client, ledger["alice"], ledger["alice_inr"], ledger["bob_inr"], 11, "k")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert response.json()["error"]["details"] is None
    assert first.json()["id"] not in response.text
    assert "Idempotent-Replayed" not in response.headers
    assert snapshot(database_path) == before


def test_another_user_reusing_a_key_neither_replays_nor_conflicts(client, database_path, ledger):
    """Bob cannot read Alice's stored response by guessing her key."""
    alice_first = transfer(client, ledger["alice"], ledger["alice_inr"], ledger["bob_inr"], 10, "k")

    # Same key and the exact same body, sent with Bob's token.
    bob_attempt = transfer(client, ledger["bob"], ledger["alice_inr"], ledger["bob_inr"], 10, "k")

    assert bob_attempt.status_code == 403
    assert alice_first.json()["id"] not in bob_attempt.text
    assert count(database_path, "transactions", "type = 'TRANSFER'") == 1


# FR-2.9: a failure after posting rolls back the transaction and the key


def test_failure_after_posting_rolls_back_entries_and_key(
    client, database_path, ledger, monkeypatch
):
    before = snapshot(database_path)

    def broken_body(*args, **kwargs):
        raise RuntimeError("fail after the ledger rows were written")

    with monkeypatch.context() as patch:
        patch.setattr(transfer_service, "_transfer_body", broken_body)
        failed = transfer(
            client, ledger["alice"], ledger["alice_inr"], ledger["bob_inr"], 500, "crash"
        )

    assert failed.status_code == 500
    assert failed.json() == {
        "error": {"code": "INTERNAL_ERROR", "message": "An internal error occurred."}
    }
    assert snapshot(database_path) == before

    retried = transfer(client, ledger["alice"], ledger["alice_inr"], ledger["bob_inr"], 500, "crash")
    assert retried.status_code == 201
    assert retried.headers["Idempotent-Replayed"] == "false"
    assert balance(database_path, ledger["bob_inr"]) == 500
    assert_reconciled(client, database_path)


def test_busy_database_returns_503_and_stores_nothing(client, database_path, ledger, monkeypatch):
    """A writer holding the lock past the busy timeout gives DATABASE_BUSY, not a partial write."""
    real_connect = sqlite3.connect
    before = snapshot(database_path)
    with closing(real_connect(database_path, isolation_level=None)) as holder, monkeypatch.context() as patch:
        # Shorten the provider's 5 s busy timeout so the test stays fast.
        patch.setattr(
            sqlite3,
            "connect",
            lambda *args, **kwargs: real_connect(*args, **{**kwargs, "timeout": 0.05}),
        )
        holder.execute("BEGIN IMMEDIATE")
        response = transfer(client, ledger["alice"], ledger["alice_inr"], ledger["bob_inr"], 5, "busy")
        holder.execute("ROLLBACK")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATABASE_BUSY"
    assert snapshot(database_path) == before
    retried = transfer(client, ledger["alice"], ledger["alice_inr"], ledger["bob_inr"], 5, "busy")
    assert retried.status_code == 201


# Error precedence: authentication, then the key, then ownership and business rules


ENDPOINTS = ["deposit", "transfer"]


def send(client, ledger, endpoint, auth, key, wallet="bob_inr"):
    headers = dict(auth)
    if key is not None:
        headers["Idempotency-Key"] = key
    if endpoint == "deposit":
        return client.post(
            f"/wallets/{ledger[wallet]}/deposit", json={"amount_minor": 1}, headers=headers
        )
    body = {
        "from_wallet_id": ledger[wallet],
        "to_wallet_id": ledger["alice_inr"] if wallet != "alice_inr" else ledger["bob_inr"],
        "amount_minor": 1,
        "currency": "INR",
    }
    return client.post("/transfers", json=body, headers=headers)


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize(
    ("auth", "key", "wallet", "status", "code"),
    [
        ({}, None, "bob_inr", 401, "UNAUTHENTICATED"),
        ({"Authorization": "Bearer wrong"}, "bad key", "bob_inr", 401, "UNAUTHENTICATED"),
        ("alice", None, "bob_inr", 400, "IDEMPOTENCY_KEY_MISSING"),
        ("alice", "bad key", "bob_inr", 422, "VALIDATION_ERROR"),
        ("alice", "good-key", "bob_inr", 403, "FORBIDDEN"),
    ],
)
def test_errors_are_reported_in_a_fixed_order(
    client, database_path, ledger, endpoint, auth, key, wallet, status, code
):
    before = snapshot(database_path)
    headers = ledger[auth] if isinstance(auth, str) else auth

    response = send(client, ledger, endpoint, headers, key, wallet)

    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code
    assert set(response.json()["error"]) == {"code", "message", "details"}
    assert UUID(response.headers["X-Request-ID"]).version == 4
    assert snapshot(database_path) == before


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_unknown_wallet_with_a_valid_key_is_404_and_stores_no_key(
    client, database_path, ledger, endpoint
):
    ledger = {**ledger, "ghost": str(uuid4())}
    before = snapshot(database_path)
    response = send(client, ledger, endpoint, ledger["alice"], "ghost-key", "ghost")
    assert response.status_code == 404
    assert snapshot(database_path) == before


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_every_error_response_is_never_marked_replayed(client, ledger, endpoint):
    for key in ("again", "again"):
        response = send(client, ledger, endpoint, ledger["alice"], key, "bob_inr")
        assert response.status_code == 403
        assert "Idempotent-Replayed" not in response.headers
