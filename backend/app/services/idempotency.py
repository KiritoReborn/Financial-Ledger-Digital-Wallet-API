"""B01 idempotent replay wrapper for deposits, transfers and reversals (SRS FR-2.4 to FR-2.10).

The API opens one BEGIN IMMEDIATE transaction, then calls run_idempotent with
that connection. The wrapper either replays the stored response, rejects a
conflicting reuse of the key, or runs the operation and stores its response in
the same transaction. It never commits or rolls back: if the operation raises,
the caller's context rolls back and no key is stored, so the client can retry
with the same key (FR-2.9). Because BEGIN IMMEDIATE takes the write lock first,
a second request with the same key waits, then finds the stored row and gets a
replay instead of a second transaction (FR-2.10).

See docs/adr/0002-idempotency-fingerprint-and-replay.md.
"""

import hashlib
import json
import re
import sqlite3
from collections.abc import Callable, Mapping
from datetime import timedelta
from uuid import UUID

from app.contracts import Clock, IdempotencyRequest, OperationResult, UtcClock
from app.http import ApiError

SCOPES = frozenset({"DEPOSIT", "TRANSFER", "REVERSAL"})
# Same rule as the idempotency_keys.key CHECK in migration 001 and the OpenAPI header.
_KEY_PATTERN = re.compile(r"[A-Za-z0-9_.:-]{1,128}")
_KEY_RULE = (
    "Idempotency-Key must be 1 to 128 characters from A-Z, a-z, 0-9, "
    "hyphen, underscore, period and colon."
)


def parse_idempotency_key(value: str | None) -> str:
    """Validate the Idempotency-Key header value (FR-2.4).

    Missing or blank gives 400 IDEMPOTENCY_KEY_MISSING; any other invalid value
    gives 422 VALIDATION_ERROR. The key itself is never echoed in the error.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ApiError(400, "IDEMPOTENCY_KEY_MISSING", "Idempotency-Key header is required.")
    if not isinstance(value, str) or _KEY_PATTERN.fullmatch(value) is None:
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            _KEY_RULE,
            [{"location": ["header", "Idempotency-Key"], "code": "invalid_idempotency_key"}],
        )
    return value


def canonical_json(value: Mapping[str, object]) -> str:
    """Serialize with sorted keys and no whitespace; NaN and infinity are rejected."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def request_fingerprint(scope: str, target_id: UUID | None, body: Mapping[str, object]) -> str:
    """SHA-256 over operation name, URL target ID (empty for transfers) and canonical body (FR-2.6).

    The three parts are joined with newlines. Neither the scope nor a UUID can
    contain a newline, so different inputs cannot produce the same message.
    """
    if scope not in SCOPES:
        raise ValueError("Unknown idempotency scope.")
    target = "" if target_id is None else str(target_id)
    message = "\n".join((scope, target, canonical_json(body)))
    return hashlib.sha256(message.encode("utf-8")).hexdigest()


class SqliteRunIdempotent:
    """Real implementation of the C03 RunIdempotent protocol (B01).

    The request body and the operation's response body must already be
    JSON-ready (str, int, bool, None, lists and dicts), so the first response
    and every replay are byte-for-byte the same JSON.
    """

    def __init__(self, *, clock: Clock | None = None):
        self.clock = clock if clock is not None else UtcClock()

    def __call__(
        self,
        connection: sqlite3.Connection,
        request: IdempotencyRequest,
        operation: Callable[[], OperationResult],
    ) -> OperationResult:
        if not connection.in_transaction:
            raise RuntimeError("run_idempotent requires a caller-owned active write transaction.")
        key = parse_idempotency_key(request.key)
        fingerprint = request_fingerprint(request.scope, request.target_id, request.body)
        user_id = str(request.user_id)

        stored = connection.execute(
            "SELECT request_hash, response_status, response_body, txn_id "
            "FROM idempotency_keys WHERE user_id = ? AND scope = ? AND key = ?",
            (user_id, request.scope, key),
        ).fetchone()
        if stored is not None:
            request_hash, status, body, txn_id = stored
            if request_hash != fingerprint:
                raise ApiError(
                    422,
                    "IDEMPOTENCY_CONFLICT",
                    "Idempotency-Key was already used with a different request.",
                )
            return OperationResult(status, json.loads(body), UUID(txn_id), replayed=True)

        result = operation()
        if not isinstance(result, OperationResult) or not isinstance(result.txn_id, UUID):
            raise TypeError("The operation must return an OperationResult with a transaction ID.")
        if not 200 <= result.status_code < 300:
            raise RuntimeError("Only successful operations may be stored for replay.")

        created_at = self.clock.now()
        if created_at.tzinfo is None or created_at.utcoffset() != timedelta(0):
            raise RuntimeError("Clock must return timezone-aware UTC.")
        connection.execute(
            "INSERT INTO idempotency_keys (user_id, scope, key, request_hash, response_status, "
            "response_body, txn_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                request.scope,
                key,
                fingerprint,
                result.status_code,
                canonical_json(result.body),
                str(result.txn_id),
                created_at.isoformat().replace("+00:00", "Z"),
            ),
        )
        return OperationResult(result.status_code, result.body, result.txn_id)


run_idempotent = SqliteRunIdempotent()
