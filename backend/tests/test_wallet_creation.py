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
