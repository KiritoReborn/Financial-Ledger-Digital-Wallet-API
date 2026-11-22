"""D02 reversal service and C03-compatible defaults (SRS FR-4.2 to FR-4.5).

Runs inside the caller's active BEGIN IMMEDIATE transaction and never begins,
commits, or rolls back internally.
"""

import hashlib
import json
import sqlite3
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID, uuid4

try:
    from ..contracts import (
        Currency,
        IdempotencyRequest,
        Operation,
        OperationResult,
        PostedTransaction,
        PostingRequest,
        PostTransaction,
        RunIdempotent,
        Transactions,
    )
except ModuleNotFoundError:
    Operation = Literal["DEPOSIT", "TRANSFER", "REVERSAL"]
    Currency = Literal["INR", "USD", "JPY"]

    @runtime_checkable
    class Transactions(Protocol):
        def transaction(
            self, *, write: bool = True
        ) -> AbstractContextManager[sqlite3.Connection]:
            """Own BEGIN/commit/rollback; use BEGIN IMMEDIATE for writes."""
            ...

    @dataclass(frozen=True)
    class PostingRequest:
        kind: Operation
        debit_wallet_id: UUID
        credit_wallet_id: UUID
        amount_minor: int
        currency: Currency
        description: str | None = None
        reverses_txn_id: UUID | None = None

    @dataclass(frozen=True)
    class PostedTransaction:
        txn_id: UUID
        created_at: datetime

    @dataclass(frozen=True)
    class IdempotencyRequest:
        user_id: UUID
        scope: Operation
        key: str
        target_id: UUID | None
        body: Mapping[str, object]

    @dataclass(frozen=True)
    class OperationResult:
        status_code: int
        body: Mapping[str, object]
        txn_id: UUID
        replayed: bool = False

    @runtime_checkable
    class PostTransaction(Protocol):
        def __call__(
            self, connection: sqlite3.Connection, request: PostingRequest
        ) -> PostedTransaction:
            """Post a balanced double-entry transaction on caller connection."""
            ...

    @runtime_checkable
    class RunIdempotent(Protocol):
        def __call__(
            self,
            connection: sqlite3.Connection,
            request: IdempotencyRequest,
            operation: Callable[[], OperationResult],
        ) -> OperationResult:
            """Execute or replay an operation inside the caller transaction."""
            ...


_REVERSIBLE_TYPES = frozenset({"DEPOSIT", "TRANSFER"})
_POSTING_ERROR_STATUS = {
    "NOT_FOUND": 404,
    "ALREADY_REVERSED": 409,
    "INSUFFICIENT_FUNDS": 422,
    "NOT_REVERSIBLE": 422,
    "CURRENCY_MISMATCH": 422,
    "VALIDATION_ERROR": 422,
    "IDEMPOTENCY_CONFLICT": 422,
}


@dataclass
class ReversalError(Exception):
    """Expected domain rejection carrying sanitized status, code, and message."""

    status: int
    code: str
    message: str


def map_posting_error(error: Exception) -> ReversalError | None:
    """Convert C04-style PostingError objects into sanitized ReversalError."""
    if isinstance(error, (ReversalError, sqlite3.Error)):
        return None
    code = getattr(error, "code", None)
    message = getattr(error, "message", None)
    if isinstance(code, str) and isinstance(message, str):
        status = _POSTING_ERROR_STATUS.get(code)
        if status is not None:
            return ReversalError(status, code, message)
    return None


def _utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _extract_mirrored_wallets(
    entries: list[tuple[str, str, int, str]],
) -> tuple[UUID, UUID, int, Currency]:
    if len(entries) != 2:
        raise ReversalError(422, "NOT_REVERSIBLE", "Transaction cannot be reversed.")
    by_dir = {direction: (wallet_id, amt, cur) for wallet_id, direction, amt, cur in entries}
    if "DEBIT" not in by_dir or "CREDIT" not in by_dir:
        raise ReversalError(422, "NOT_REVERSIBLE", "Transaction cannot be reversed.")
    orig_debit_wallet, debit_amt, debit_cur = by_dir["DEBIT"]
    orig_credit_wallet, credit_amt, credit_cur = by_dir["CREDIT"]
    if debit_amt != credit_amt or debit_amt <= 0 or debit_cur != credit_cur:
        raise ReversalError(422, "NOT_REVERSIBLE", "Transaction cannot be reversed.")
    if orig_debit_wallet == orig_credit_wallet:
        raise ReversalError(422, "NOT_REVERSIBLE", "Transaction cannot be reversed.")
    try:
        debit_uuid = UUID(orig_credit_wallet)
        credit_uuid = UUID(orig_debit_wallet)
    except ValueError as error:
        raise ReversalError(
            422, "NOT_REVERSIBLE", "Transaction cannot be reversed."
        ) from error
    return debit_uuid, credit_uuid, debit_amt, debit_cur  # type: ignore[return-value]


def _build_entries_payload(
    conn: sqlite3.Connection,
    reversal_txn_id: UUID,
    debit_wallet_id: UUID,
    credit_wallet_id: UUID,
    amount_minor: int,
    currency: Currency,
    created_at: str,
) -> list[dict[str, object]]:
    rows = conn.execute(
        "SELECT id, txn_id, wallet_id, direction, amount_minor, currency, created_at "
        "FROM ledger_entries WHERE txn_id = ? ORDER BY id ASC",
        (str(reversal_txn_id),),
    ).fetchall()
    if len(rows) == 2:
        return [
            {
                "id": row[0],
                "txn_id": row[1],
                "wallet_id": row[2],
                "type": "REVERSAL",
                "direction": row[3],
                "amount_minor": row[4],
                "currency": row[5],
                "created_at": row[6],
            }
            for row in rows
        ]
    # Pure contract fakes (C03 FakePostTransaction) return a PostedTransaction stub
    # without writing SQL rows; return the mirrored entries matching OpenAPI.
    return [
        {
            "id": 1,
            "txn_id": str(reversal_txn_id),
            "wallet_id": str(debit_wallet_id),
            "type": "REVERSAL",
            "direction": "DEBIT",
            "amount_minor": amount_minor,
            "currency": currency,
            "created_at": created_at,
        },
        {
            "id": 2,
            "txn_id": str(reversal_txn_id),
            "wallet_id": str(credit_wallet_id),
            "type": "REVERSAL",
            "direction": "CREDIT",
            "amount_minor": amount_minor,
            "currency": currency,
            "created_at": created_at,
        },
    ]


def reverse_transaction(
    conn: sqlite3.Connection,
    txn_id: UUID,
    post_transaction: PostTransaction,
    *,
    description: str | None = None,
) -> tuple[UUID, dict[str, object]]:
    """Validate eligibility and post a mirrored REVERSAL on the caller transaction."""
    if not conn.in_transaction:
        raise RuntimeError(
            "Reversal requires a caller-owned active write transaction."
        )
    if not isinstance(txn_id, UUID) or txn_id.version != 4:
        raise ReversalError(
            422, "VALIDATION_ERROR", "Transaction ID must be a valid UUID v4."
        )

    original = conn.execute(
        "SELECT id, type FROM transactions WHERE id = ?",
        (str(txn_id),),
    ).fetchone()
    if original is None:
        raise ReversalError(404, "NOT_FOUND", "Transaction not found.")
    if original[1] not in _REVERSIBLE_TYPES:
        raise ReversalError(
            422, "NOT_REVERSIBLE", "A reversal cannot itself be reversed."
        )

    if conn.execute(
        "SELECT 1 FROM transactions WHERE reverses_txn_id = ?",
        (str(txn_id),),
    ).fetchone():
        raise ReversalError(409, "ALREADY_REVERSED", "Transaction was already reversed.")

    entries = conn.execute(
        "SELECT wallet_id, direction, amount_minor, currency "
        "FROM ledger_entries WHERE txn_id = ? ORDER BY id ASC",
        (str(txn_id),),
    ).fetchall()
    debit_wallet_id, credit_wallet_id, amount_minor, currency = (
        _extract_mirrored_wallets(entries)
    )

    wallet_row = conn.execute(
        "SELECT balance_minor, is_system FROM wallets WHERE id = ?",
        (str(debit_wallet_id),),
    ).fetchone()
    if wallet_row is None:
        raise ReversalError(404, "NOT_FOUND", "Wallet not found.")
    balance_minor, is_system = wallet_row
    if is_system == 0 and balance_minor < amount_minor:
        raise ReversalError(
            422, "INSUFFICIENT_FUNDS", "Insufficient funds to reverse transaction."
        )

    posting_request = PostingRequest(
        kind="REVERSAL",
        debit_wallet_id=debit_wallet_id,
        credit_wallet_id=credit_wallet_id,
        amount_minor=amount_minor,
        currency=currency,
        description=description,
        reverses_txn_id=txn_id,
    )
    try:
        posted = post_transaction(conn, posting_request)
    except sqlite3.IntegrityError as error:
        if "reverses_txn_id" in str(error):
            raise ReversalError(
                409, "ALREADY_REVERSED", "Transaction was already reversed."
            ) from error
        raise
    except Exception as error:
        mapped = map_posting_error(error)
        if mapped is not None:
            raise mapped from error
        raise

    created_at = _utc_iso(posted.created_at)
    entries_payload = _build_entries_payload(
        conn,
        posted.txn_id,
        debit_wallet_id,
        credit_wallet_id,
        amount_minor,
        currency,
        created_at,
    )
    body: dict[str, object] = {
        "id": str(posted.txn_id),
        "type": "REVERSAL",
        "description": description,
        "reverses_txn_id": str(txn_id),
        "created_at": created_at,
        "entries": entries_payload,
    }
    return posted.txn_id, body


@contextmanager
def sqlite_write_transaction(database_path: Path) -> Iterator[sqlite3.Connection]:
    """Open one rw SQLite connection holding BEGIN IMMEDIATE until commit/rollback."""
    uri = Path(database_path).resolve().as_uri() + "?mode=rw"
    with closing(
        sqlite3.connect(uri, uri=True, isolation_level=None, timeout=5.0)
    ) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA synchronous = FULL")
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            if conn.in_transaction:
                conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise


def default_post_transaction(
    conn: sqlite3.Connection, request: PostingRequest
) -> PostedTransaction:
    """Fallback balanced SQLite poster used until C04 LedgerPoster is merged."""
    if not conn.in_transaction:
        raise RuntimeError(
            "Posting requires a caller-owned active write transaction."
        )
    debited = conn.execute(
        "UPDATE wallets SET balance_minor = balance_minor - ? "
        "WHERE id = ? AND (is_system = 1 OR balance_minor >= ?)",
        (request.amount_minor, str(request.debit_wallet_id), request.amount_minor),
    )
    if debited.rowcount != 1:
        raise ReversalError(
            422, "INSUFFICIENT_FUNDS", "Insufficient funds to reverse transaction."
        )
    credited = conn.execute(
        "UPDATE wallets SET balance_minor = balance_minor + ? WHERE id = ?",
        (request.amount_minor, str(request.credit_wallet_id)),
    )
    if credited.rowcount != 1:
        raise ReversalError(404, "NOT_FOUND", "Wallet not found.")

    txn_id = uuid4()
    created_at = datetime.now(UTC)
    timestamp = _utc_iso(created_at)
    conn.execute(
        "INSERT INTO transactions (id, type, reverses_txn_id, description, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            str(txn_id),
            request.kind,
            str(request.reverses_txn_id) if request.reverses_txn_id else None,
            request.description,
            timestamp,
        ),
    )
    conn.executemany(
        "INSERT INTO ledger_entries "
        "(txn_id, wallet_id, direction, amount_minor, currency, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                str(txn_id),
                str(wallet_id),
                direction,
                request.amount_minor,
                request.currency,
                timestamp,
            )
            for wallet_id, direction in (
                (request.debit_wallet_id, "DEBIT"),
                (request.credit_wallet_id, "CREDIT"),
            )
        ],
    )
    return PostedTransaction(txn_id=txn_id, created_at=created_at)


def request_fingerprint(request: IdempotencyRequest) -> str:
    """Compute FR-2.6 SHA-256 fingerprint over scope, target ID, and JSON body."""
    target = str(request.target_id) if request.target_id is not None else ""
    body_json = json.dumps(
        dict(request.body), sort_keys=True, separators=(",", ":")
    )
    payload = f"{request.scope}:{target}:{body_json}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def default_run_idempotent(
    conn: sqlite3.Connection,
    request: IdempotencyRequest,
    operation: Callable[[], OperationResult],
) -> OperationResult:
    """Fallback SQLite idempotency wrapper used until B01 is merged."""
    if not conn.in_transaction:
        raise RuntimeError(
            "Idempotency wrapper requires a caller-owned active write transaction."
        )
    fingerprint = request_fingerprint(request)
    existing = conn.execute(
        "SELECT request_hash, response_status, response_body, txn_id "
        "FROM idempotency_keys WHERE user_id = ? AND scope = ? AND key = ?",
        (str(request.user_id), request.scope, request.key),
    ).fetchone()
    if existing is not None:
        stored_hash, stored_status, stored_body, stored_txn_id = existing
        if not hmac_equal(stored_hash, fingerprint):
            raise ReversalError(
                422,
                "IDEMPOTENCY_CONFLICT",
                "Idempotency key was already used with a different request.",
            )
        return OperationResult(
            status_code=stored_status,
            body=json.loads(stored_body),
            txn_id=UUID(stored_txn_id),
            replayed=True,
        )

    result = operation()
    timestamp = _utc_iso(datetime.now(UTC))
    conn.execute(
        "INSERT INTO idempotency_keys "
        "(user_id, scope, key, request_hash, response_status, "
        "response_body, txn_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            str(request.user_id),
            request.scope,
            request.key,
            fingerprint,
            result.status_code,
            json.dumps(dict(result.body), separators=(",", ":")),
            str(result.txn_id),
            timestamp,
        ),
    )
    return result


def hmac_equal(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))
