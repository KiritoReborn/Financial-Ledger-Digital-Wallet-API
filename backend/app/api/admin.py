"""D02 & D03 administrative endpoints: reversal and reconciliation.

Both GET /admin/reconcile (FR-5.1..FR-5.4) and POST /transactions/{id}/reverse
(FR-4.2..FR-4.5) require the admin bearer token and X-Admin-Key (NFR-SEC-2, BR-5).
Both secrets are compared in constant time and every auth failure returns the same
401 UNAUTHENTICATED envelope before touching the database.
"""

import hashlib
import hmac
import json
import os
import re
import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi import Path as PathParam
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from ..services.reconciliation import reconcile, sqlite_read_snapshot
from ..services.reversal import (
    IdempotencyRequest,
    OperationResult,
    PostTransaction,
    ReversalError,
    RunIdempotent,
    default_post_transaction,
    default_run_idempotent,
    map_posting_error,
    reverse_transaction,
    sqlite_write_transaction,
)

router = APIRouter()

ReadSnapshot = Callable[[], AbstractContextManager[sqlite3.Connection]]
WriteTransaction = Callable[[], AbstractContextManager[sqlite3.Connection]]

MAX_BODY_BYTES = 16 * 1024
DEFAULT_ADMIN_USER_ID = UUID("00000000-0000-4000-8000-000000000000")
_IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_UUID4_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}"
    r"-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)


@dataclass(frozen=True, repr=False)
class AdminCredentials:
    """Admin secrets from the environment; repr hides values from logs."""

    token: str
    key: str

    @classmethod
    def from_env(cls) -> "AdminCredentials":
        return cls(
            token=os.environ.get("ADMIN_TOKEN", ""),
            key=os.environ.get("ADMIN_KEY", ""),
        )

    def __repr__(self) -> str:
        return "AdminCredentials(<redacted>)"


def _digest(value: str) -> bytes:
    # Hashing first gives equal-length inputs, so compare_digest leaks no length.
    return hashlib.sha256(value.encode("utf-8")).digest()


def _bearer_token(authorization: str | None) -> str:
    scheme, _, token = (authorization or "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


def is_admin(
    credentials: AdminCredentials,
    authorization: str | None,
    admin_key: str | None,
) -> bool:
    """Check token and key without short-circuiting; fail closed if unset."""
    token_ok = hmac.compare_digest(
        _digest(_bearer_token(authorization)), _digest(credentials.token)
    )
    key_ok = hmac.compare_digest(
        _digest(admin_key or ""), _digest(credentials.key)
    )
    configured = bool(credentials.token) and bool(credentials.key)
    return configured & token_ok & key_ok


def _error(status: int, code: str, message: str, headers=None) -> JSONResponse:
    error: dict[str, object] = {"code": code, "message": message}
    if status != 500:
        error["details"] = None
    return JSONResponse(status_code=status, content={"error": error}, headers=headers)


class ReconciliationChecks(BaseModel):
    model_config = ConfigDict(extra="forbid")
    currencies_balanced: bool
    transactions_valid: bool
    wallet_balances_match: bool
    entry_currencies_match: bool


class ReconciliationResult(BaseModel):
    ok: bool
    checks: ReconciliationChecks
    mismatches: list[dict[str, object]]


class LedgerEntryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int
    txn_id: str
    wallet_id: str
    type: str
    direction: str
    amount_minor: int
    currency: str
    created_at: str


class TransactionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    type: str
    description: str | None
    reverses_txn_id: str | None
    created_at: str
    entries: list[LedgerEntryResponse]


def _credentials(request: Request) -> AdminCredentials:
    configured = getattr(request.app.state, "admin_credentials", None)
    return configured if configured is not None else AdminCredentials.from_env()


def _read_snapshot(request: Request) -> ReadSnapshot:
    configured = getattr(request.app.state, "read_snapshot", None)
    if configured is not None:
        return configured
    path = Path(os.environ.get("DATABASE_PATH", "data/ledger.sqlite3"))
    return lambda: sqlite_read_snapshot(path)


def _write_transaction(request: Request) -> WriteTransaction:
    configured = getattr(request.app.state, "write_transaction", None)
    if configured is not None:
        return configured
    path = Path(os.environ.get("DATABASE_PATH", "data/ledger.sqlite3"))
    return lambda: sqlite_write_transaction(path)


def _post_transaction(request: Request) -> PostTransaction:
    configured = getattr(request.app.state, "post_transaction", None)
    return configured if configured is not None else default_post_transaction


def _run_idempotent(request: Request) -> RunIdempotent:
    configured = getattr(request.app.state, "run_idempotent", None)
    return configured if configured is not None else default_run_idempotent


def _validate_idempotency_key(raw_key: str | None) -> str | JSONResponse:
    if raw_key is None or not raw_key.strip():
        return _error(
            400,
            "IDEMPOTENCY_KEY_MISSING",
            "Idempotency-Key header is required.",
        )
    if _IDEMPOTENCY_KEY_RE.fullmatch(raw_key) is None:
        return _error(
            422,
            "VALIDATION_ERROR",
            "Idempotency-Key header is invalid.",
        )
    return raw_key


def _validate_uuid4(raw_id: str) -> UUID | JSONResponse:
    if _UUID4_RE.fullmatch(raw_id) is None:
        return _error(
            422,
            "VALIDATION_ERROR",
            "Transaction ID must be a valid UUID v4.",
        )
    return UUID(raw_id)


def _parse_reverse_body(raw_body: bytes) -> dict[str, object] | JSONResponse:
    if len(raw_body) > MAX_BODY_BYTES:
        return _error(
            413,
            "PAYLOAD_TOO_LARGE",
            "Request body exceeds 16 KiB.",
        )
    if not raw_body.strip():
        return {}
    try:
        parsed = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error(422, "VALIDATION_ERROR", "Request validation failed.")
    if not isinstance(parsed, dict) or parsed != {}:
        return _error(422, "VALIDATION_ERROR", "Request validation failed.")
    return parsed


def _resolve_admin_user_id(
    conn: sqlite3.Connection, credentials: AdminCredentials
) -> UUID:
    token_hash = hashlib.sha256(credentials.token.encode("utf-8")).hexdigest()
    row = conn.execute(
        "SELECT id FROM users WHERE token_hash = ?", (token_hash,)
    ).fetchone()
    if row is not None:
        try:
            return UUID(row[0])
        except ValueError:
            pass
    return DEFAULT_ADMIN_USER_ID


@router.get(
    "/admin/reconcile",
    response_model=ReconciliationResult,
    tags=["admin"],
    responses={
        401: {"description": "Missing or invalid bearer token, or wrong admin key."},
        500: {"description": "The ledger could not be read; details are not exposed."},
        503: {"description": "SQLite could not acquire a lock within its busy timeout."},
    },
)
def reconcile_ledger(request: Request) -> ReconciliationResult | JSONResponse:
    """Run all four read-only checks on one snapshot; mismatches still return 200."""
    if not is_admin(
        _credentials(request),
        request.headers.get("authorization"),
        request.headers.get("x-admin-key"),
    ):
        return _error(
            401,
            "UNAUTHENTICATED",
            "Authentication is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        with _read_snapshot(request)() as conn:
            report = reconcile(conn)
    # The HTTP boundary must not expose SQL, paths or exception text (NFR-SEC-7).
    except Exception as error:  # noqa: BLE001
        sqlite_code = getattr(error, "sqlite_errorcode", 0) or 0
        if (
            isinstance(error, sqlite3.OperationalError)
            and sqlite_code & 0xFF == sqlite3.SQLITE_BUSY
        ):
            return _error(
                503, "DATABASE_BUSY", "Database is busy. Try again later."
            )
        return _error(500, "INTERNAL_ERROR", "An internal error occurred.")
    return ReconciliationResult.model_validate(report.as_dict())


@router.post(
    "/transactions/{id}/reverse",
    response_model=TransactionResponse,
    status_code=201,
    tags=["admin"],
    responses={
        400: {"description": "Idempotency-Key missing or blank."},
        401: {"description": "Missing or invalid bearer token, or wrong admin key."},
        404: {"description": "Transaction does not exist."},
        409: {"description": "Transaction was already reversed."},
        413: {"description": "Request body exceeds 16 KiB."},
        422: {"description": "Validation or business rule rejects the reversal."},
        500: {"description": "Unexpected failure; details are not exposed."},
        503: {"description": "SQLite could not acquire a lock within its busy timeout."},
    },
)
async def reverse_ledger_transaction(
    request: Request,
    txn_id: str = PathParam(alias="id"),
) -> JSONResponse:
    """Reverse an eligible DEPOSIT or TRANSFER once with admin auth and idempotency."""
    creds = _credentials(request)
    if not is_admin(
        creds,
        request.headers.get("authorization"),
        request.headers.get("x-admin-key"),
    ):
        return _error(
            401,
            "UNAUTHENTICATED",
            "Authentication is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    key_or_err = _validate_idempotency_key(request.headers.get("idempotency-key"))
    if isinstance(key_or_err, JSONResponse):
        return key_or_err

    parsed_id_or_err = _validate_uuid4(txn_id)
    if isinstance(parsed_id_or_err, JSONResponse):
        return parsed_id_or_err

    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > MAX_BODY_BYTES:
                return _error(
                    413, "PAYLOAD_TOO_LARGE", "Request body exceeds 16 KiB."
                )
        except ValueError:
            return _error(422, "VALIDATION_ERROR", "Request validation failed.")

    body_or_err = _parse_reverse_body(await request.body())
    if isinstance(body_or_err, JSONResponse):
        return body_or_err

    write_tx = _write_transaction(request)
    post_tx = _post_transaction(request)
    run_idem = _run_idempotent(request)

    def _execute() -> OperationResult:
        with write_tx() as conn:
            admin_user_id = _resolve_admin_user_id(conn, creds)
            idem_req = IdempotencyRequest(
                user_id=admin_user_id,
                scope="REVERSAL",
                key=key_or_err,
                target_id=parsed_id_or_err,
                body=body_or_err,
            )

            def operation() -> OperationResult:
                rev_id, tx_body = reverse_transaction(
                    conn, parsed_id_or_err, post_tx
                )
                return OperationResult(
                    status_code=201, body=tx_body, txn_id=rev_id
                )

            return run_idem(conn, idem_req, operation)

    try:
        result = await run_in_threadpool(_execute)
    except ReversalError as error:
        return _error(error.status, error.code, error.message)
    except Exception as error:  # noqa: BLE001
        mapped = map_posting_error(error)
        if mapped is not None:
            return _error(mapped.status, mapped.code, mapped.message)
        sqlite_code = getattr(error, "sqlite_errorcode", 0) or 0
        if (
            isinstance(error, sqlite3.OperationalError)
            and sqlite_code & 0xFF == sqlite3.SQLITE_BUSY
        ):
            return _error(
                503, "DATABASE_BUSY", "Database is busy. Try again later."
            )
        return _error(500, "INTERNAL_ERROR", "An internal error occurred.")

    headers = {"Idempotent-Replayed": "true"} if result.replayed else None
    return JSONResponse(
        status_code=result.status_code,
        content=dict(result.body),
        headers=headers,
    )
