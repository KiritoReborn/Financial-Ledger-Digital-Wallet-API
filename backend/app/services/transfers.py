"""B03 transfer rules on the caller's BEGIN IMMEDIATE transaction (SRS FR-1.5, FR-1.7).

The API layer authenticates the caller and runs this inside run_idempotent.
This module checks that the sender wallet belongs to the caller and that the
receiver exists, then posts one TRANSFER through the C04 posting engine. The
engine rejects currency mismatches, system wallets and insufficient funds, and
any rejection escapes so the caller's transaction rolls back.
"""

import sqlite3
from dataclasses import dataclass
from uuid import UUID

from ..contracts import Currency, OperationResult, PostingRequest
from ..http import ApiError
from ..posting import LedgerPoster

poster = LedgerPoster()


@dataclass(frozen=True)
class TransferInput:
    from_wallet_id: UUID
    to_wallet_id: UUID
    amount_minor: int
    currency: Currency
    description: str | None = None


def _check_wallets(conn: sqlite3.Connection, user_id: UUID, transfer: TransferInput) -> None:
    """404 for an unknown wallet, 403 when the sender is not the caller's (FR-1.5)."""
    sender = conn.execute(
        "SELECT user_id FROM wallets WHERE id = ?", (str(transfer.from_wallet_id),)
    ).fetchone()
    if sender is None:
        raise ApiError(404, "NOT_FOUND", "Wallet not found.")
    if sender[0] != str(user_id):
        raise ApiError(403, "FORBIDDEN", "Access is forbidden.")
    if transfer.from_wallet_id == transfer.to_wallet_id:
        raise ApiError(422, "VALIDATION_ERROR", "Wallets must differ.")
    receiver = conn.execute(
        "SELECT 1 FROM wallets WHERE id = ?", (str(transfer.to_wallet_id),)
    ).fetchone()
    if receiver is None:
        raise ApiError(404, "NOT_FOUND", "Wallet not found.")


def _transfer_body(conn: sqlite3.Connection, txn_id: UUID, transfer: TransferInput) -> dict[str, object]:
    """Build the OpenAPI Transfer object from the stored transaction row."""
    txn = conn.execute(
        "SELECT id, type, description, created_at FROM transactions WHERE id = ?",
        (str(txn_id),),
    ).fetchone()
    return {
        "id": txn[0],
        "type": txn[1],
        "from_wallet_id": str(transfer.from_wallet_id),
        "to_wallet_id": str(transfer.to_wallet_id),
        "amount_minor": transfer.amount_minor,
        "currency": transfer.currency,
        "description": txn[2],
        "created_at": txn[3],
    }


def post_transfer(
    conn: sqlite3.Connection, user_id: UUID, transfer: TransferInput
) -> OperationResult:
    """Move funds between two user wallets; the caller owns the transaction."""
    _check_wallets(conn, user_id, transfer)
    posted = poster(
        conn,
        PostingRequest(
            "TRANSFER",
            transfer.from_wallet_id,
            transfer.to_wallet_id,
            transfer.amount_minor,
            transfer.currency,
            transfer.description,
        ),
    )
    return OperationResult(201, _transfer_body(conn, posted.txn_id, transfer), posted.txn_id)
