"""Read committed postings created through the public ledger API."""

import os

import pytest

TestClient = pytest.importorskip("fastapi.testclient").TestClient
create_app = pytest.importorskip("app.main").create_app


def create_user_wallet(client, name):
    user = client.post("/users", json={"name": name, "email": f"{name.lower()}@example.com"})
    assert user.status_code == 201
    auth = {"Authorization": f"Bearer {user.json()['token']}"}
    wallet = client.post("/wallets", json={"currency": "INR"}, headers=auth)
    assert wallet.status_code == 201
    return wallet.json()["id"], auth


def test_history_reads_live_deposit_transfer_replay_and_reversal(api_environment):
    with TestClient(create_app()) as client:
        sender, alice = create_user_wallet(client, "Alice")
        receiver, bob = create_user_wallet(client, "Bob")
        _, stranger = create_user_wallet(client, "Charlie")
        deposit = client.post(
            f"/wallets/{sender}/deposit",
            json={"amount_minor": 5_000},
            headers={**alice, "Idempotency-Key": "history-opening"},
        )
        assert deposit.status_code == 201
        body = {
            "from_wallet_id": sender,
            "to_wallet_id": receiver,
            "amount_minor": 3_000,
            "currency": "INR",
            "description": "History integration",
        }
        headers = {**alice, "Idempotency-Key": "history-transfer"}
        posted = client.post("/transfers", json=body, headers=headers)
        replay = client.post("/transfers", json=body, headers=headers)
        assert posted.status_code == replay.status_code == 201
        assert replay.headers["Idempotent-Replayed"] == "true"
        transfer_id = posted.json()["id"]
        assert replay.json() == posted.json()

        path = f"/transfers/{transfer_id}"
        for auth in (alice, bob):
            details = client.get(path, headers=auth)
            assert details.status_code == 200
            assert details.json() == posted.json()
        assert client.get(path, headers=stranger).status_code == 403
        assert client.get(path).status_code == 401

        admin = {
            "Authorization": f"Bearer {os.environ['ADMIN_TOKEN']}",
            "X-Admin-Key": os.environ["ADMIN_KEY"],
        }
        reversal = client.post(
            f"/transactions/{transfer_id}/reverse",
            json={},
            headers={**admin, "Idempotency-Key": "history-reversal"},
        )
        assert reversal.status_code == 201

        path = f"/wallets/{sender}/transactions"
        history = client.get(path, headers=alice, params={"limit": 2})
        assert history.status_code == 200
        first = history.json()
        assert [(row["txn_id"], row["type"], row["direction"]) for row in first["entries"]] == [
            (reversal.json()["id"], "REVERSAL", "CREDIT"),
            (transfer_id, "TRANSFER", "DEBIT"),
        ]
        older = client.get(path, headers=alice, params={"before_id": first["next_before_id"]})
        assert older.status_code == 200
        assert [row["txn_id"] for row in older.json()["entries"]] == [deposit.json()["id"]]
        assert older.json()["next_before_id"] is None
        assert client.get(path, headers=bob).status_code == 403
        report = client.get("/admin/reconcile", headers=admin)
        assert report.status_code == 200
        assert report.json()["ok"] is True
