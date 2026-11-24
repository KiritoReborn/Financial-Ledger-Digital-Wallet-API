import hashlib
from contextlib import closing

import pytest

auth = pytest.importorskip("app.auth")


def test_registration_token_resolves_only_its_owner(empty_ledger):
    token, digest = auth.issue_user_token()
    other, other_digest = auth.issue_user_token()
    assert token != other
    assert digest == hashlib.sha256(token.encode()).hexdigest()
    with closing(empty_ledger.connect()) as conn:
        conn.executemany(
            "INSERT INTO users VALUES (?, 'Member', ?, ?, '2026-11-23T00:00:00Z')",
            [("a", "a@example.test", digest), ("b", "b@example.test", other_digest)],
        )
        assert auth.authenticated_user_id(conn, f"Bearer {token}") == "a"
        assert auth.authenticated_user_id(conn, f"bearer {other}") == "b"
        for header in (None, "Bearer ", "Bearer unknown", f"Basic {token}", f"Bearer {digest}"):
            assert auth.authenticated_user_id(conn, header) is None
