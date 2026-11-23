"""Bearer tokens for user registration and authenticated requests (FR-1.2)."""

import hashlib
import secrets
import sqlite3


def token_digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def issue_user_token() -> tuple[str, str]:
    """Return the registration response token and the hex digest for users.token_hash."""
    token = secrets.token_urlsafe(32)
    return token, token_digest(token).hex()


def bearer_token(authorization: str | None) -> str:
    scheme, _, token = (authorization or "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


def authenticated_user_id(conn: sqlite3.Connection, authorization: str | None) -> str | None:
    """Resolve a bearer token using the request's existing SQLite connection."""
    token = bearer_token(authorization)
    if not token:
        return None
    row = conn.execute(
        "SELECT id FROM users WHERE token_hash = ?", (token_digest(token).hex(),)
    ).fetchone()
    return row[0] if row else None
