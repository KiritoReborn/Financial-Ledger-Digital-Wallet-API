"""B03 transfer endpoint: POST /transfers (SRS FR-1.7, FR-2.4 to FR-2.10).

One BEGIN IMMEDIATE transaction holds the whole request: authenticate the
bearer token, validate the Idempotency-Key, then let run_idempotent either
replay the stored response or post the transfer. The transaction context
commits on success and rolls back on any error, so a rejected transfer stores
no key and the client can retry once the cause is fixed.
"""

import sqlite3
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
from pydantic import UUID4, BaseModel, ConfigDict, Field

from ..auth import authenticated_user_id
from ..contracts import Currency, IdempotencyRequest
from ..http import ApiError
from ..services.idempotency import (
    idempotency_key_openapi,
    parse_idempotency_key,
    run_idempotent,
)
from ..services.transfers import TransferInput, post_transfer
from .errors import database_error

bearer = HTTPBearer(scheme_name="bearerAuth", auto_error=False)
router = APIRouter(dependencies=[Depends(bearer)])

# JSON carries UUIDs as strings, so only the amount needs strict integer parsing.
WalletId = Annotated[UUID4, Field(strict=False)]


class TransferRequest(BaseModel):
    """Integer minor units only: strict mode rejects 10.5, "100" and true (TQ-6)."""

    model_config = ConfigDict(extra="forbid", strict=True)
    from_wallet_id: WalletId
    to_wallet_id: WalletId
    amount_minor: Annotated[int, Field(ge=1, le=10**12)]
    currency: Currency
    description: Annotated[str | None, Field(max_length=200)] = None


def _authenticate(conn: sqlite3.Connection, request: Request) -> UUID:
    user_id = authenticated_user_id(conn, request.headers.get("authorization"))
    if user_id is None:
        raise ApiError(401, "UNAUTHENTICATED", "Authentication is required.")
    return UUID(user_id)


@router.post(
    "/transfers",
    status_code=201,
    operation_id="createTransfer",
    tags=["transfers"],
    summary="Transfer simulated funds idempotently",
    openapi_extra=idempotency_key_openapi(),
    responses={
        400: {"description": "Idempotency-Key is missing or blank."},
        401: {"description": "Missing or invalid bearer token."},
        403: {"description": "The sender wallet belongs to another user."},
        404: {"description": "The sender or receiver wallet does not exist."},
        422: {
            "description": "Invalid request, same wallet, currency mismatch, insufficient "
            "funds, or the key was reused for another request."
        },
        503: {"description": "SQLite could not acquire the write lock within its busy timeout."},
    },
)
def create_transfer(body: TransferRequest, request: Request) -> JSONResponse:
    """Move simulated funds from the caller's wallet to another user's wallet.

    Both wallets must hold the request currency. Requires an Idempotency-Key.
    Repeating a request with the same key and body returns the stored response
    with Idempotent-Replayed: true.
    """
    request_body = body.model_dump(mode="json")
    transfer = TransferInput(**body.model_dump())
    try:
        with request.app.state.database.transaction() as conn:
            user_id = _authenticate(conn, request)
            key = parse_idempotency_key(request.headers.get("idempotency-key"))
            result = run_idempotent(
                conn,
                IdempotencyRequest(user_id, "TRANSFER", key, None, request_body),
                lambda: post_transfer(conn, user_id, transfer),
            )
    except sqlite3.Error as error:
        return database_error(error)
    return JSONResponse(
        status_code=result.status_code,
        content=dict(result.body),
        headers={"Idempotent-Replayed": "true" if result.replayed else "false"},
    )
