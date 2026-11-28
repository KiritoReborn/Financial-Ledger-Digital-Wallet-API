"""Transfer and wallet reads composed with the shared auth and database providers."""

import sqlite3
from collections.abc import Callable
from contextlib import contextmanager
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Query, Security
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..contracts import Transactions
from ..history import History, HistoryError, Transfer, get_transfer, list_wallet_history
from ..http import ApiError
from .errors import database_error

UserResolver = Callable[[sqlite3.Connection, str | None], str | None]
BearerCredentials = Annotated[
    HTTPAuthorizationCredentials | None,
    Security(HTTPBearer(scheme_name="bearerAuth", auto_error=False)),
]
HISTORY_ERRORS = {"NOT_FOUND": 404, "FORBIDDEN": 403, "VALIDATION_ERROR": 422}
READ_RESPONSES = {
    401: {"description": "Missing or invalid bearer token."},
    403: {"description": "The caller cannot access this record."},
    404: {"description": "The transfer or wallet does not exist."},
    500: {"description": "The ledger could not be read."},
    503: {"description": "SQLite could not acquire a read lock."},
}


def create_history_router(
    *,
    resolve_user: UserResolver,
    transactions: Transactions,
) -> APIRouter:
    """Resolve the caller and read ledger data on the same SQLite snapshot."""
    router = APIRouter()

    @contextmanager
    def read_as_user(credentials: HTTPAuthorizationCredentials | None):
        if credentials is None:
            raise HTTPException(401, headers={"WWW-Authenticate": "Bearer"})
        authorization = f"{credentials.scheme} {credentials.credentials}"
        with transactions.transaction(write=False) as connection:
            user_id = resolve_user(connection, authorization)
            if user_id is None:
                raise HTTPException(401, headers={"WWW-Authenticate": "Bearer"})
            try:
                yield connection, UUID(user_id)
            except HistoryError as error:
                raise ApiError(HISTORY_ERRORS[error.code], error.code, error.message) from error

    @router.get(
        "/transfers/{id}",
        operation_id="getTransfer",
        tags=["transfers"],
        response_model=Transfer,
        responses=READ_RESPONSES,
    )
    def transfer_details(
        transfer_id: Annotated[str, Path(alias="id")],
        credentials: BearerCredentials,
    ) -> Transfer | JSONResponse:
        try:
            with read_as_user(credentials) as (connection, user_id):
                return get_transfer(connection, user_id=user_id, transfer_id=transfer_id)
        except sqlite3.Error as error:
            return database_error(error)

    @router.get(
        "/wallets/{id}/transactions",
        operation_id="walletHistory",
        tags=["wallets"],
        response_model=History,
        responses=READ_RESPONSES,
    )
    def wallet_transactions(
        wallet_id: Annotated[str, Path(alias="id")],
        credentials: BearerCredentials,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        before_id: Annotated[int | None, Query(ge=1, le=2**63 - 1)] = None,
    ) -> History | JSONResponse:
        try:
            with read_as_user(credentials) as (connection, user_id):
                return list_wallet_history(
                    connection, user_id=user_id, wallet_id=wallet_id, limit=limit, before_id=before_id
                )
        except sqlite3.Error as error:
            return database_error(error)

    return router
