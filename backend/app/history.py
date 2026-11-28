"""Read posted ledger data on a caller-owned SQLite read transaction."""

import re
import sqlite3
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from typing_extensions import TypedDict

from app.contracts import Currency, Operation

_UUID4_ID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", re.IGNORECASE
)
_MAX_ENTRY_ID = 2**63 - 1


@dataclass
class HistoryError(Exception):
    """Expected read rejection with a fixed, public-safe message."""

    code: Literal["VALIDATION_ERROR", "FORBIDDEN", "NOT_FOUND"]
    message: str


class Transfer(TypedDict):
    id: str
    type: Literal["TRANSFER"]
    from_wallet_id: str
    to_wallet_id: str
    amount_minor: int
    currency: Currency
    description: str | None
    created_at: str


class Entry(TypedDict):
    id: int
    txn_id: str
    wallet_id: str
    type: Operation
    direction: Literal["DEBIT", "CREDIT"]
    amount_minor: int
    currency: Currency
    created_at: str


class History(TypedDict):
    entries: list[Entry]
    next_before_id: int | None


def _require_read_transaction(connection: sqlite3.Connection) -> None:
    if not connection.in_transaction:
        raise RuntimeError("Ledger reads require a caller-owned active read transaction.")


def _resource_id(value: UUID | str) -> str:
    if isinstance(value, UUID):
        value = str(value)
    if not isinstance(value, str) or not _UUID4_ID.fullmatch(value):
        raise HistoryError("VALIDATION_ERROR", "Resource ID must be a UUID v4.")
    return value.lower()


def get_transfer(
    connection: sqlite3.Connection, *, user_id: UUID, transfer_id: UUID | str
) -> Transfer:
    """Return a posted transfer to either participant's verified user ID."""
    _require_read_transaction(connection)
    transaction_id = _resource_id(transfer_id)
    transaction = connection.execute(
        "SELECT description, created_at FROM transactions WHERE id = ? AND type = 'TRANSFER'",
        (transaction_id,),
    ).fetchone()
    if transaction is None:
        raise HistoryError("NOT_FOUND", "Transfer not found.")

    legs = connection.execute(
        """
        SELECT entry.direction, entry.wallet_id, wallet.user_id, entry.amount_minor, entry.currency
        FROM ledger_entries AS entry
        JOIN wallets AS wallet ON wallet.id = entry.wallet_id
        WHERE entry.txn_id = ?
        ORDER BY entry.direction DESC
        LIMIT 3
        """,
        (transaction_id,),
    ).fetchall()
    if len(legs) != 2 or legs[0][0] != "DEBIT" or legs[1][0] != "CREDIT":
        raise RuntimeError("Stored transfer has invalid ledger entries.")
    _, sender_wallet, sender_owner, amount_minor, currency = legs[0]
    _, receiver_wallet, receiver_owner, credit_amount, credit_currency = legs[1]
    if str(user_id) not in (sender_owner, receiver_owner):
        raise HistoryError("FORBIDDEN", "Access is forbidden.")
    if sender_wallet == receiver_wallet or (amount_minor, currency) != (credit_amount, credit_currency):
        raise RuntimeError("Stored transfer has unbalanced ledger entries.")

    description, created_at = transaction
    return {
        "id": transaction_id,
        "type": "TRANSFER",
        "from_wallet_id": sender_wallet,
        "to_wallet_id": receiver_wallet,
        "amount_minor": amount_minor,
        "currency": currency,
        "description": description,
        "created_at": created_at,
    }


def list_wallet_history(
    connection: sqlite3.Connection,
    *,
    user_id: UUID,
    wallet_id: UUID | str,
    limit: int = 20,
    before_id: int | None = None,
) -> History:
    """Return one page of entries for the verified owner of the wallet."""
    _require_read_transaction(connection)
    wallet_key = _resource_id(wallet_id)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise HistoryError("VALIDATION_ERROR", "Limit must be an integer from 1 through 100.")
    if before_id is not None and (
        type(before_id) is not int or not 1 <= before_id <= _MAX_ENTRY_ID
    ):
        raise HistoryError("VALIDATION_ERROR", "Before ID must be a positive 64-bit integer.")

    wallet = connection.execute(
        "SELECT user_id FROM wallets WHERE id = ?", (wallet_key,)
    ).fetchone()
    if wallet is None:
        raise HistoryError("NOT_FOUND", "Wallet not found.")
    if wallet[0] != str(user_id):
        raise HistoryError("FORBIDDEN", "Access is forbidden.")

    # Use the same indexed range for the first page and exclusive cursor pages.
    upper_id = _MAX_ENTRY_ID if before_id is None else before_id - 1
    rows = connection.execute(
        """
        SELECT entry.id, entry.txn_id, txn.type, entry.direction,
               entry.amount_minor, entry.currency, entry.created_at
        FROM ledger_entries AS entry
        JOIN transactions AS txn ON txn.id = entry.txn_id
        WHERE entry.wallet_id = ? AND entry.id <= ?
        ORDER BY entry.id DESC
        LIMIT ?
        """,
        (wallet_key, upper_id, limit + 1),
    ).fetchall()
    entries: list[Entry] = [
        {
            "id": entry_id,
            "txn_id": txn_id,
            "wallet_id": wallet_key,
            "type": kind,
            "direction": direction,
            "amount_minor": amount_minor,
            "currency": currency,
            "created_at": created_at,
        }
        for entry_id, txn_id, kind, direction, amount_minor, currency, created_at in rows[:limit]
    ]
    return {
        "entries": entries,
        "next_before_id": entries[-1]["id"] if len(rows) > limit else None,
    }
