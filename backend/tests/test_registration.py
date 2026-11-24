import hashlib
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest

TestClient = pytest.importorskip("fastapi.testclient").TestClient
create_app = pytest.importorskip("app.main").create_app
from app.auth import ADMIN_ID, authenticated_user_id


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "ledger.db"))
    monkeypatch.setenv("ADMIN_TOKEN", "registration-test-token")
    monkeypatch.setenv("ADMIN_KEY", "registration-test-key")
    return create_app()


def test_registration_and_authentication(app):
    with TestClient(app) as client:
        body = {"name": "  Example User ", "email": "  USER@Example.test "}
        response = client.post("/users", json=body)
        assert response.status_code == 201
        user = response.json()
        assert set(user) == {"id", "name", "email", "token", "created_at"}
        assert UUID(user["id"]).version == 4 and user["created_at"].endswith("Z")
        assert (user["name"], user["email"]) == ("Example User", "user@example.test")
        duplicate = client.post("/users", json={**body, "email": "user@example.test"})
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "EMAIL_ALREADY_EXISTS"
        with app.state.database.transaction(write=False) as conn:
            stored = conn.execute(
                "SELECT token_hash FROM users WHERE id=?", (user["id"],)
            ).fetchone()
            assert stored == (hashlib.sha256(user["token"].encode()).hexdigest(),)
            assert authenticated_user_id(conn, "Bearer " + user["token"]) == user["id"]
        assert (
            client.get(
                "/admin/reconcile",
                headers={
                    "Authorization": "Bearer " + user["token"],
                    "X-Admin-Key": "registration-test-key",
                },
            ).status_code
            == 401
        )


@pytest.mark.parametrize(
    "body",
    [
        {"email": "x@example.org"},
        {"name": "   ", "email": "x@example.org"},
        {"name": "x" * 101, "email": "x@example.org"},
        {"name": "X", "email": "bad"},
        {"name": "X", "email": "Display Name <x@example.org>"},
        {"name": "X", "email": "x" * 249 + "@foo.org"},
        {"name": 12, "email": "x@example.org"},
        {"name": "X", "email": "x@example.org", "token": "private"},
    ],
)
def test_invalid_registration_creates_nothing(app, body):
    with TestClient(app) as client:
        response = client.post("/users", json=body)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
        assert "private" not in response.text
        with app.state.database.transaction(write=False) as conn:
            assert conn.execute("SELECT count(*) FROM users").fetchone() == (1,)


def test_concurrent_duplicate_has_one_winner(app):
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as threads:

        def register(email):
            return client.post("/users", json={"name": "A", "email": email}).status_code

        assert sorted(threads.map(register, ["A@example.org", "a@example.org"])) == [201, 409]


def test_restart_rotates_admin_token_and_retains_identity(app, monkeypatch):
    with TestClient(app), app.state.database.transaction(write=False) as conn:
        original = conn.execute("SELECT id, created_at FROM users").fetchone()
        assert original[0] == ADMIN_ID

    monkeypatch.setenv("ADMIN_TOKEN", "rotated-test-token")
    restarted = create_app()
    with TestClient(restarted) as client, restarted.state.database.transaction(write=False) as conn:
        assert conn.execute("SELECT id, created_at FROM users").fetchall() == [original]
        assert authenticated_user_id(conn, "Bearer registration-test-token") is None
        assert authenticated_user_id(conn, "Bearer rotated-test-token") == ADMIN_ID
        assert (
            client.get(
                "/admin/reconcile",
                headers={
                    "Authorization": "Bearer rotated-test-token",
                    "X-Admin-Key": "registration-test-key",
                },
            ).status_code
            == 200
        )


@pytest.mark.parametrize("variable", ["ADMIN_TOKEN", "ADMIN_KEY"])
def test_missing_secret_refuses_startup_before_database_creation(app, monkeypatch, variable):
    monkeypatch.delenv(variable)
    with pytest.raises(ValueError, match=variable), TestClient(app):
        pytest.fail("Startup should fail")
    assert not app.state.database.path.exists()
