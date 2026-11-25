"""Create a wallet for the authenticated user (FR-1.3)."""

import sqlite3
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict

from ..auth import authenticated_user_id
from ..contracts import Currency, UtcClock, UuidIds
from ..http import error_response
from .errors import database_error

router = APIRouter()
bearer = HTTPBearer(scheme_name="bearerAuth", auto_error=False)


class WalletRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    currency: Currency


class Wallet(BaseModel):
    id: UUID
    user_id: UUID
    currency: Currency
    balance_minor: int
    is_system: bool
    created_at: datetime


@router.post(
    "/wallets",
    status_code=201,
    response_model=Wallet,
    operation_id="createWallet",
    tags=["wallets"],
)
def create_wallet(
    body: WalletRequest,
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Wallet | JSONResponse:
    unauthorized = error_response(
        401,
        "UNAUTHENTICATED",
        "Authentication is required.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        return unauthorized
    try:
        with request.app.state.database.transaction() as conn:
            owner = authenticated_user_id(conn, request.headers.get("authorization"))
            if owner is None:
                return unauthorized
            wallet = Wallet(
                id=UuidIds().new_id(),
                user_id=UUID(owner),
                currency=body.currency,
                balance_minor=0,
                is_system=False,
                created_at=UtcClock().now(),
            )
            inserted = conn.execute(
                """INSERT INTO wallets (id, user_id, currency, created_at) VALUES (?, ?, ?, ?)
                   ON CONFLICT(user_id, currency) DO NOTHING""",
                (
                    str(wallet.id),
                    owner,
                    wallet.currency,
                    wallet.created_at.isoformat().replace("+00:00", "Z"),
                ),
            ).rowcount
    except sqlite3.Error as error:
        return database_error(error)
    if not inserted:
        return error_response(422, "VALIDATION_ERROR", "A wallet already exists for this currency.")
    return wallet
