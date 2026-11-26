"""B02 simulated deposit: POST /wallets/{id}/deposit (SRS FR-1.6, FR-2.4 to FR-2.10).

One BEGIN IMMEDIATE transaction holds the whole request: authenticate the
bearer token, validate the Idempotency-Key, check wallet ownership, then let
run_idempotent either replay the stored response or post a DEPOSIT through the
C04 posting engine (debit the currency's system wallet, credit the caller's
wallet). The transaction context commits on success and rolls back on any
error, so a failed deposit stores no key and the client can retry.
"""

import sqlite3
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from ..auth import authenticated_user_id
from ..contracts import IdempotencyRequest, OperationResult, PostingRequest
from ..http import ApiError
from ..posting import LedgerPoster
from ..services.idempotency import (
    idempotency_key_openapi,
    parse_idempotency_key,
    run_idempotent,
)
from .errors import database_error

# Documents bearer auth in OpenAPI only; _authenticate still returns the 401 envelope.
bearer = HTTPBearer(scheme_name="bearerAuth", auto_error=False)
router = APIRouter(dependencies=[Depends(bearer)])
poster = LedgerPoster()


class DepositRequest(BaseModel):
    """Integer minor units only: strict mode rejects 10.5, "100" and true (TQ-6)."""

    model_config = ConfigDict(extra="forbid", strict=True)
    amount_minor: Annotated[int, Field(ge=1, le=10**12)]


def _authenticate(conn: sqlite3.Connection, request: Request) -> UUID:
    user_id = authenticated_user_id(conn, request.headers.get("authorization"))
    if user_id is None:
        raise ApiError(401, "UNAUTHENTICATED", "Authentication is required.")
    return UUID(user_id)


def _owned_wallet(conn: sqlite3.Connection, wallet_id: UUID, user_id: UUID) -> str:
    """Return the wallet currency; 404 for an unknown wallet, 403 for anyone else's (FR-1.5)."""
    wallet = conn.execute(
        "SELECT user_id, currency FROM wallets WHERE id = ?", (str(wallet_id),)
    ).fetchone()
    if wallet is None:
        raise ApiError(404, "NOT_FOUND", "Wallet not found.")
    if wallet[0] != str(user_id):
        raise ApiError(403, "FORBIDDEN", "Access is forbidden.")
    return wallet[1]


def _system_wallet(conn: sqlite3.Connection, currency: str) -> UUID:
    row = conn.execute(
        "SELECT id FROM wallets WHERE is_system = 1 AND currency = ?", (currency,)
    ).fetchone()
    if row is None:
        # Start-up creates one system wallet per currency (FR-1.9, Member A).
        raise RuntimeError("The system wallet for this currency is missing.")
    return UUID(row[0])


def _transaction_body(conn: sqlite3.Connection, txn_id: UUID) -> dict[str, object]:
    """Build the OpenAPI Transaction object, with its two entries, from the stored rows."""
    txn = conn.execute(
        "SELECT id, type, description, reverses_txn_id, created_at FROM transactions WHERE id = ?",
        (str(txn_id),),
    ).fetchone()
    entries = conn.execute(
        "SELECT id, txn_id, wallet_id, direction, amount_minor, currency, created_at "
        "FROM ledger_entries WHERE txn_id = ? ORDER BY id",
        (str(txn_id),),
    ).fetchall()
    return {
        "id": txn[0],
        "type": txn[1],
        "description": txn[2],
        "reverses_txn_id": txn[3],
        "created_at": txn[4],
        "entries": [
            {
                "id": entry[0],
                "txn_id": entry[1],
                "wallet_id": entry[2],
                "type": txn[1],
                "direction": entry[3],
                "amount_minor": entry[4],
                "currency": entry[5],
                "created_at": entry[6],
            }
            for entry in entries
        ],
    }


@router.post(
    "/wallets/{id}/deposit",
    status_code=201,
    operation_id="deposit",
    tags=["wallets"],
    summary="Add simulated funds idempotently",
    openapi_extra=idempotency_key_openapi(),
    responses={
        400: {"description": "Idempotency-Key is missing or blank."},
        401: {"description": "Missing or invalid bearer token."},
        403: {"description": "The wallet belongs to another user."},
        404: {"description": "The wallet does not exist."},
        422: {"description": "Invalid amount, key or ID, or the key was reused for another request."},
        503: {"description": "SQLite could not acquire the write lock within its busy timeout."},
    },
)
def deposit(
    # Named "id" in the URL, matching docs/api/openapi.yaml.
    wallet_id: Annotated[UUID, Path(alias="id")],
    body: DepositRequest,
    request: Request,
) -> JSONResponse:
    """Credit simulated funds to the caller's wallet from the system wallet of its currency.

    Requires an Idempotency-Key. Repeating a request with the same key and body
    returns the stored response with Idempotent-Replayed: true.
    """
    request_body = body.model_dump(mode="json")
    try:
        with request.app.state.database.transaction() as conn:
            user_id = _authenticate(conn, request)
            key = parse_idempotency_key(request.headers.get("idempotency-key"))
            currency = _owned_wallet(conn, wallet_id, user_id)

            def operation() -> OperationResult:
                posted = poster(
                    conn,
                    PostingRequest(
                        "DEPOSIT",
                        _system_wallet(conn, currency),
                        wallet_id,
                        body.amount_minor,
                        currency,
                    ),
                )
                return OperationResult(201, _transaction_body(conn, posted.txn_id), posted.txn_id)

            result = run_idempotent(
                conn,
                IdempotencyRequest(user_id, "DEPOSIT", key, wallet_id, request_body),
                operation,
            )
    except sqlite3.Error as error:
        return database_error(error)
    return JSONResponse(
        status_code=result.status_code,
        content=dict(result.body),
        headers={"Idempotent-Replayed": "true" if result.replayed else "false"},
    )
