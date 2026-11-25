"""D02 reversal service on a caller-owned BEGIN IMMEDIATE transaction (FR-4.2..FR-4.5)."""

import sqlite3
from datetime import UTC
from uuid import UUID

from ..contracts import Currency, OperationResult, PostingRequest, PostTransaction
from ..http import ApiError
from ..posting import LedgerPoster

_REVERSIBLE_TYPES = frozenset({"DEPOSIT", "TRANSFER"})

poster = LedgerPoster()


def _extract_mirrored_wallets(
    entries: list[tuple[str, str, int, str]],
) -> tuple[UUID, UUID, int, Currency]:
    if len(entries) != 2:
        raise ApiError(422, "NOT_REVERSIBLE", "Transaction cannot be reversed.")
    by_dir = {direction: (wallet_id, amt, cur) for wallet_id, direction, amt, cur in entries}
    if "DEBIT" not in by_dir or "CREDIT" not in by_dir:
        raise ApiError(422, "NOT_REVERSIBLE", "Transaction cannot be reversed.")
    orig_debit_wallet, debit_amt, debit_cur = by_dir["DEBIT"]
    orig_credit_wallet, credit_amt, credit_cur = by_dir["CREDIT"]
    if (
        debit_amt != credit_amt
        or debit_amt <= 0
        or debit_cur != credit_cur
        or orig_debit_wallet == orig_credit_wallet
    ):
        raise ApiError(422, "NOT_REVERSIBLE", "Transaction cannot be reversed.")
    try:
        debit_wallet_id = UUID(orig_credit_wallet)
        credit_wallet_id = UUID(orig_debit_wallet)
    except ValueError as error:
        raise ApiError(422, "NOT_REVERSIBLE", "Transaction cannot be reversed.") from error
    return debit_wallet_id, credit_wallet_id, debit_amt, debit_cur  # type: ignore[return-value]


def _transaction_body(
    conn: sqlite3.Connection,
    reversal_txn_id: UUID,
    original_txn_id: UUID,
    debit_wallet_id: UUID,
    credit_wallet_id: UUID,
    amount_minor: int,
    currency: Currency,
    description: str | None,
    created_at_iso: str,
) -> dict[str, object]:
    """Build the OpenAPI Transaction object from persisted rows or a C03 stub."""
    txn = conn.execute(
        "SELECT id, type, description, reverses_txn_id, created_at FROM transactions WHERE id = ?",
        (str(reversal_txn_id),),
    ).fetchone()
    entries = conn.execute(
        "SELECT id, txn_id, wallet_id, direction, amount_minor, currency, created_at "
        "FROM ledger_entries WHERE txn_id = ? ORDER BY id ASC",
        (str(reversal_txn_id),),
    ).fetchall()
    if txn is not None and len(entries) == 2:
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

    # C03 FakePostTransaction returns PostedTransaction without writing SQL rows.
    return {
        "id": str(reversal_txn_id),
        "type": "REVERSAL",
        "description": description,
        "reverses_txn_id": str(original_txn_id),
        "created_at": created_at_iso,
        "entries": [
            {
                "id": 1,
                "txn_id": str(reversal_txn_id),
                "wallet_id": str(debit_wallet_id),
                "type": "REVERSAL",
                "direction": "DEBIT",
                "amount_minor": amount_minor,
                "currency": currency,
                "created_at": created_at_iso,
            },
            {
                "id": 2,
                "txn_id": str(reversal_txn_id),
                "wallet_id": str(credit_wallet_id),
                "type": "REVERSAL",
                "direction": "CREDIT",
                "amount_minor": amount_minor,
                "currency": currency,
                "created_at": created_at_iso,
            },
        ],
    }


def reverse_transaction(
    conn: sqlite3.Connection,
    txn_id: UUID,
    *,
    post_transaction: PostTransaction = poster,
    description: str | None = None,
) -> OperationResult:
    """Validate eligibility and post a mirrored REVERSAL inside caller transaction."""
    if not conn.in_transaction:
        raise RuntimeError("Reversal requires a caller-owned active write transaction.")
    if not isinstance(txn_id, UUID) or txn_id.version != 4:
        raise ApiError(422, "VALIDATION_ERROR", "Transaction ID must be a valid UUID v4.")

    original = conn.execute(
        "SELECT id, type FROM transactions WHERE id = ?", (str(txn_id),)
    ).fetchone()
    if original is None:
        raise ApiError(404, "NOT_FOUND", "Transaction not found.")
    if original[1] not in _REVERSIBLE_TYPES:
        raise ApiError(422, "NOT_REVERSIBLE", "A reversal cannot itself be reversed.")

    if conn.execute(
        "SELECT 1 FROM transactions WHERE reverses_txn_id = ?", (str(txn_id),)
    ).fetchone():
        raise ApiError(409, "ALREADY_REVERSED", "Transaction was already reversed.")

    entries = conn.execute(
        "SELECT wallet_id, direction, amount_minor, currency "
        "FROM ledger_entries WHERE txn_id = ? ORDER BY id ASC",
        (str(txn_id),),
    ).fetchall()
    debit_wallet_id, credit_wallet_id, amount_minor, currency = _extract_mirrored_wallets(entries)

    wallet_row = conn.execute(
        "SELECT balance_minor, is_system FROM wallets WHERE id = ?",
        (str(debit_wallet_id),),
    ).fetchone()
    if wallet_row is None:
        raise ApiError(404, "NOT_FOUND", "Wallet not found.")
    balance_minor, is_system = wallet_row
    if is_system == 0 and balance_minor < amount_minor:
        raise ApiError(
            422, "INSUFFICIENT_FUNDS", "Insufficient funds to reverse transaction."
        )

    request = PostingRequest(
        "REVERSAL",
        debit_wallet_id,
        credit_wallet_id,
        amount_minor,
        currency,
        description,
        txn_id,
    )
    try:
        posted = post_transaction(conn, request)
    except sqlite3.IntegrityError as error:
        if "reverses_txn_id" in str(error):
            raise ApiError(
                409, "ALREADY_REVERSED", "Transaction was already reversed."
            ) from error
        raise

    created_at_iso = posted.created_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    body = _transaction_body(
        conn,
        posted.txn_id,
        txn_id,
        debit_wallet_id,
        credit_wallet_id,
        amount_minor,
        currency,
        description,
        created_at_iso,
    )
    return OperationResult(201, body, posted.txn_id)
