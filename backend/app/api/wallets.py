"""Create a wallet for the authenticated user (FR-1.3)."""

import sqlite3
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
from pydantic import BaseModel, ConfigDict, UUID4

from ..auth import authenticated_user_id
from ..contracts import Currency, UtcClock, UuidIds
from ..http import ApiError, error_response
from .errors import database_error

bearer = HTTPBearer(scheme_name="bearerAuth", auto_error=False)
router = APIRouter(dependencies=[Depends(bearer)])


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


def _owner(conn: sqlite3.Connection, request: Request) -> str:
    owner = authenticated_user_id(conn, request.headers.get("authorization"))
    if owner is None:
        raise ApiError(401, "UNAUTHENTICATED", "Authentication is required.")
    return owner


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
) -> Wallet | JSONResponse:
    try:
        with request.app.state.database.transaction() as conn:
            owner = _owner(conn, request)
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


class WalletList(BaseModel):
    wallets: list[Wallet]


_COLUMNS = "id, user_id, currency, balance_minor, is_system, created_at"


@router.get("/wallets", operation_id="listWallets", response_model=WalletList, tags=["wallets"])
def list_wallets(request: Request) -> WalletList | JSONResponse:
    try:
        with request.app.state.database.transaction(write=False) as conn:
            owner = _owner(conn, request)
            if request.query_params:
                raise ApiError(422, "VALIDATION_ERROR", "Wallet listing takes no parameters.")
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM wallets WHERE user_id = ? ORDER BY currency", (owner,)
            )
            return WalletList(wallets=[Wallet(**dict(row)) for row in rows])
    except sqlite3.Error as error:
        return database_error(error)


@router.get("/wallets/{id}", operation_id="getWallet", response_model=Wallet, tags=["wallets"])
def get_wallet(id: UUID4, request: Request) -> Wallet | JSONResponse:
    try:
        with request.app.state.database.transaction(write=False) as conn:
            owner = _owner(conn, request)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM wallets WHERE id = ?", (str(id),)
            ).fetchone()
            if row is None:
                raise ApiError(404, "NOT_FOUND", "Wallet not found.")
            if row["user_id"] != owner:
                raise ApiError(403, "FORBIDDEN", "Access is forbidden.")
            return Wallet(**dict(row))
    except sqlite3.Error as error:
        return database_error(error)
