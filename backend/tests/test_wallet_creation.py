from concurrent.futures import ThreadPoolExecutor

import pytest

TestClient = pytest.importorskip("fastapi.testclient").TestClient
create_app = pytest.importorskip("app.main").create_app

pytestmark = pytest.mark.usefixtures("api_environment")


def test_wallets_are_created_for_the_bearer_only():
    app = create_app()
    with TestClient(app) as client:
        for name in ("alice", "bob"):
            user = client.post("/users", json={"name": name, "email": name + "@example.org"}).json()
            headers = {"Authorization": "Bearer " + user["token"]}
            for currency in ("INR", "USD", "JPY"):
                response = client.post("/wallets", headers=headers, json={"currency": currency})
                assert response.status_code == 201
                row = response.json()
                assert row["user_id"] == user["id"] and row["currency"] == currency
                assert row["balance_minor"] == 0 and row["is_system"] is False
                with app.state.database.transaction(write=False) as conn:
                    assert conn.execute(
                        "SELECT user_id, currency, balance_minor, is_system FROM wallets WHERE id=?",
                        (row["id"],),
                    ).fetchone() == (user["id"], currency, 0, 0)


def test_rejected_requests_cannot_create_wallets():
    app = create_app()
    with TestClient(app) as client:
        user = client.post("/users", json={"name": "A", "email": "a@example.org"}).json()
        headers = {"Authorization": "Bearer " + user["token"]}
        for bad_headers in ({}, {"Authorization": "Bearer unknown"}):
            response = client.post("/wallets", headers=bad_headers, json={"currency": "INR"})
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "UNAUTHENTICATED"
        for body in ({"currency": "EUR"}, {"currency": "INR", "user_id": user["id"]}):
            assert client.post("/wallets", headers=headers, json=body).status_code == 422
        with app.state.database.transaction(write=False) as conn:
            assert conn.execute("SELECT count(*) FROM wallets WHERE is_system=0").fetchone() == (0,)


def test_concurrent_wallet_creation_has_one_winner():
    with TestClient(create_app()) as client:
        user = client.post("/users", json={"name": "A", "email": "a@example.org"}).json()

        def create():
            return client.post(
                "/wallets",
                headers={"Authorization": "Bearer " + user["token"]},
                json={"currency": "INR"},
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(create) for _ in range(2)]
            responses = sorted((f.result() for f in futures), key=lambda r: r.status_code)
        assert [r.status_code for r in responses] == [201, 422]
        assert responses[1].json()["error"]["code"] == "VALIDATION_ERROR"


def test_wallet_reads_enforce_ownership():
    from uuid import uuid4

    with TestClient(create_app()) as client:

        def register(name):
            user = client.post("/users", json={"name": name, "email": name + "@example.org"}).json()
            return {"Authorization": "Bearer " + user["token"]}

        alice, bob = register("Alice"), register("Bob")
        wallet = client.post("/wallets", headers=alice, json={"currency": "USD"}).json()
        url = "/wallets/" + wallet["id"]
        assert client.get("/wallets", headers=alice).json() == {"wallets": [wallet]}
        assert client.get("/wallets", headers=bob).json() == {"wallets": []}
        assert client.get("/wallets?user_id=" + wallet["user_id"], headers=bob).status_code == 422
        assert client.get(url, headers=alice).json() == wallet
        for path, headers, status in [
            (url, bob, 403),
            ("/wallets/" + str(uuid4()), alice, 404),
            ("/wallets/invalid", alice, 422),
            (url, {}, 401),
            ("/wallets", {}, 401),
        ]:
            assert client.get(path, headers=headers).status_code == status


def test_restart_preserves_system_wallets_and_restores_missing_currency():
    from app.currencies import CURRENCY_EXPONENTS

    assert dict(CURRENCY_EXPONENTS) == {"INR": 2, "USD": 2, "JPY": 0}
    app = create_app()
    query = "SELECT currency, id, balance_minor, user_id FROM wallets WHERE is_system=1 ORDER BY currency"
    with TestClient(app), app.state.database.transaction() as conn:
        original = conn.execute(query).fetchall()
        assert [r[0] for r in original] == ["INR", "JPY", "USD"]
        assert all(r[2:] == (0, None) for r in original)
        conn.execute("UPDATE wallets SET balance_minor=-123 WHERE is_system=1 AND currency='INR'")
        conn.execute("DELETE FROM wallets WHERE is_system=1 AND currency='JPY'")
    with TestClient(app), app.state.database.transaction(write=False) as conn:
        restored = conn.execute(query).fetchall()
        assert len(restored) == 3 and restored[0] == ("INR", original[0][1], -123, None)
        assert restored[1][0] == "JPY" and restored[1][2:] == (0, None)
        assert restored[2] == original[2]


def test_wallet_creation_rejects_server_managed_fields():
    with TestClient(create_app()) as client:
        user = client.post("/users", json={"name": "Alice", "email": "alice@example.org"}).json()
        headers = {"Authorization": "Bearer " + user["token"]}
        for field, value in (("balance_minor", 500), ("is_system", True), ("id", user["id"])):
            body = {"currency": "USD", field: value}
            response = client.post("/wallets", headers=headers, json=body)
            assert response.status_code == 422, field
            assert response.json()["error"]["code"] == "VALIDATION_ERROR"

        assert client.get("/wallets", headers=headers).json() == {"wallets": []}
        created = client.post("/wallets", headers=headers, json={"currency": "USD"})
        assert created.status_code == 201
        assert created.json()["balance_minor"] == 0


def test_invalid_credentials_cannot_read_or_create_wallets():
    import hashlib

    with TestClient(create_app()) as client:
        user = client.post("/users", json={"name": "Alice", "email": "alice@example.org"}).json()
        token = user["token"]
        owner = {"Authorization": "Bearer " + token}
        wallet = client.post("/wallets", headers=owner, json={"currency": "USD"}).json()
        digest = hashlib.sha256(token.encode()).hexdigest()
        for credential in ("Basic " + token, "Bearer " + digest, "Bearer"):
            headers = {"Authorization": credential}
            responses = [
                client.get("/wallets", headers=headers),
                client.get("/wallets/" + wallet["id"], headers=headers),
                client.post("/wallets", headers=headers, json={"currency": "JPY"}),
            ]
            for response in responses:
                assert response.status_code == 401
                assert response.json()["error"]["code"] == "UNAUTHENTICATED"
                assert token not in response.text and digest not in response.text
        assert client.get("/wallets", headers=owner).json() == {"wallets": [wallet]}
