"""D02 & D03 administrative endpoints: reversal and reconciliation.

Both GET /admin/reconcile (FR-5.1 to FR-5.4) and POST /transactions/{id}/reverse
(FR-4.2 to FR-4.5) require the admin bearer token and X-Admin-Key header
(NFR-SEC-2, BR-5). Both are compared in constant time and every auth failure
returns the same 401 UNAUTHENTICATED envelope before touching the database.
"""

import hmac
import os
import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi import Path as PathParam
from fastapi.responses import JSONResponse
from pydantic import UUID4, BaseModel, ConfigDict

from ..auth import ADMIN_ID, authenticated_user_id, bearer_token, token_digest
from ..contracts import IdempotencyRequest
from ..http import ApiError, error_response
from ..posting import PostingError
from ..services.idempotency import parse_idempotency_key, run_idempotent
from ..services.reconciliation import reconcile, sqlite_read_snapshot
from ..services.reversal import poster, reverse_transaction
from .errors import database_error

router = APIRouter()

ReadSnapshot = Callable[[], AbstractContextManager[sqlite3.Connection]]


@dataclass(frozen=True, repr=False)
class AdminCredentials:
    """Admin secrets from the environment; repr is hidden so they never reach logs."""

    token: str
    key: str

    @classmethod
    def from_env(cls) -> "AdminCredentials":
        return cls(token=os.environ.get("ADMIN_TOKEN", ""), key=os.environ.get("ADMIN_KEY", ""))

    def __repr__(self) -> str:
        return "AdminCredentials(<redacted>)"


def is_admin(
    credentials: AdminCredentials,
    authorization: str | None,
    admin_key: str | None,
) -> bool:
    """Check token and key without short-circuiting; fail closed if unconfigured."""
    token_ok = hmac.compare_digest(
        token_digest(bearer_token(authorization)),
        token_digest(credentials.token),
    )
    key_ok = hmac.compare_digest(token_digest(admin_key or ""), token_digest(credentials.key))
    configured = bool(credentials.token) and bool(credentials.key)
    return configured & token_ok & key_ok


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


class ReverseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


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
        return error_response(
            401,
            "UNAUTHENTICATED",
            "Authentication is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        with _read_snapshot(request)() as conn:
            if authenticated_user_id(conn, request.headers.get("authorization")) != ADMIN_ID:
                return error_response(
                    401,
                    "UNAUTHENTICATED",
                    "Authentication is required.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            report = reconcile(conn)
    # The HTTP boundary must not expose SQL, paths or exception text (NFR-SEC-7).
    except Exception as error:  # noqa: BLE001
        return database_error(error)
    return ReconciliationResult.model_validate(report.as_dict())


@router.post(
    "/transactions/{id}/reverse",
    status_code=201,
    operation_id="reverseTransaction",
    response_model=TransactionResponse,
    tags=["admin"],
    summary="Reverse an eligible transaction once",
    responses={
        400: {"description": "Idempotency-Key is missing or blank."},
        401: {"description": "Missing or invalid bearer token, or wrong admin key."},
        404: {"description": "Transaction does not exist."},
        409: {"description": "Transaction was already reversed."},
        413: {"description": "Request body exceeds 16 KiB."},
        422: {"description": "Validation or business rule rejects the reversal."},
        500: {"description": "Unexpected failure; details are not exposed."},
        503: {"description": "SQLite could not acquire a lock within its busy timeout."},
    },
)
def reverse_ledger_transaction(
    request: Request,
    txn_id: Annotated[UUID4, PathParam(alias="id")],
    body: ReverseRequest | None = None,
) -> JSONResponse:
    """Reverse an eligible DEPOSIT or TRANSFER once with admin auth and idempotency."""
    if not is_admin(
        _credentials(request),
        request.headers.get("authorization"),
        request.headers.get("x-admin-key"),
    ):
        return error_response(
            401,
            "UNAUTHENTICATED",
            "Authentication is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    key = parse_idempotency_key(request.headers.get("idempotency-key"))
    request_body = {} if body is None else body.model_dump(mode="json")
    write_tx = getattr(
        request.app.state, "write_transaction", request.app.state.database.transaction
    )
    post_tx = getattr(request.app.state, "post_transaction", poster)
    run_idem = getattr(request.app.state, "run_idempotent", run_idempotent)

    try:
        with write_tx() as conn:
            if authenticated_user_id(conn, request.headers.get("authorization")) != ADMIN_ID:
                return error_response(
                    401,
                    "UNAUTHENTICATED",
                    "Authentication is required.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            result = run_idem(
                conn,
                IdempotencyRequest(UUID(ADMIN_ID), "REVERSAL", key, txn_id, request_body),
                lambda: reverse_transaction(conn, txn_id, post_transaction=post_tx),
            )
    except (ApiError, PostingError):
        raise
    except Exception as error:  # noqa: BLE001
        return database_error(error)

    return JSONResponse(
        status_code=result.status_code,
        content=dict(result.body),
        headers={"Idempotent-Replayed": "true" if result.replayed else "false"},
    )
