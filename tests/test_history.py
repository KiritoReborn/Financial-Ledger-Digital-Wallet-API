"""C06 reads on a migrated ledger with posted transactions."""

import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from uuid import UUID

import pytest

from db.migrate import apply_migrations

contracts = pytest.importorskip(
    "app.contracts", reason="Install backend or set PYTHONPATH=backend."
)
history = import_module("app.history")
token_digest = import_module("app.auth").token_digest
PostingRequest = contracts.PostingRequest
FixedClock = import_module("app.contracts.fakes").FixedClock
LedgerPoster = import_module("app.posting").LedgerPoster
HistoryError = history.HistoryError
get_transfer = history.get_transfer
list_wallet_history = history.list_wallet_history

SYSTEM, ALICE_WALLET, BOB_WALLET, EMPTY_WALLET, MISSING_ID = [
    UUID(f"00000000-0000-4000-8000-{number:012x}") for number in range(10, 15)
]
ALICE, BOB, CHARLIE = [UUID(f"00000000-0000-4000-8000-{number:012x}") for number in range(100, 103)]
STAMP = datetime(2026, 11, 19, tzinfo=UTC)


@dataclass(frozen=True)
class PostedLedger:
    path: Path
    deposit_id: UUID
    transfer_id: UUID


def post(path, request, *, stamp=STAMP):
    with closing(sqlite3.connect(path, isolation_level=None)) as writer, writer:
        writer.execute("PRAGMA foreign_keys = ON")
        writer.execute("BEGIN IMMEDIATE")
        return LedgerPoster(clock=FixedClock(stamp))(writer, request).txn_id


def deposit(path, wallet_id=ALICE_WALLET, *, stamp=STAMP):
    return post(path, PostingRequest("DEPOSIT", SYSTEM, wallet_id, 1000, "INR"), stamp=stamp)


def reverse(ledger):
    return post(
        ledger.path,
        PostingRequest(
            "REVERSAL", BOB_WALLET, ALICE_WALLET, 75, "INR", reverses_txn_id=ledger.transfer_id
        ),
    )


@contextmanager
def read(path):
    with closing(sqlite3.connect(path, isolation_level=None)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("BEGIN")
        yield connection


@pytest.fixture
def ledger(tmp_path):
    path = tmp_path / "history.sqlite3"
    with closing(sqlite3.connect(path, isolation_level=None)) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        apply_migrations(connection)
        connection.executemany(
            "INSERT INTO users (id, name, email, token_hash, created_at) VALUES (?, ?, ?, ?, ?)",
            [
                (
                    str(user), name, f"{name}@example.test", token_digest(f"{name}-test").hex(), "now"
                )
                for user, name in ((ALICE, "alice"), (BOB, "bob"), (CHARLIE, "charlie"))
            ],
        )
        connection.executemany(
            "INSERT INTO wallets (id, user_id, currency, is_system, created_at) VALUES (?, ?, ?, ?, ?)",
            [
                (str(SYSTEM), None, "INR", 1, "now"),
                (str(ALICE_WALLET), str(ALICE), "INR", 0, "now"),
                (str(BOB_WALLET), str(BOB), "INR", 0, "now"),
                (str(EMPTY_WALLET), str(ALICE), "USD", 0, "now"),
            ],
        )
    deposit_id = deposit(path)
    deposit(path, BOB_WALLET)
    transfer_id = post(
        path, PostingRequest("TRANSFER", ALICE_WALLET, BOB_WALLET, 75, "INR", "Dinner")
    )
    return PostedLedger(path, deposit_id, transfer_id)


@pytest.mark.parametrize("owner", [ALICE, BOB])
def test_both_participants_can_read_the_transfer(ledger, owner):
    with read(ledger.path) as connection:
        transfer = get_transfer(
            connection, user_id=owner, transfer_id=str(ledger.transfer_id).upper()
        )
        assert connection.in_transaction
    assert transfer == {
        "id": str(ledger.transfer_id),
        "type": "TRANSFER",
        "from_wallet_id": str(ALICE_WALLET),
        "to_wallet_id": str(BOB_WALLET),
        "amount_minor": 75,
        "currency": "INR",
        "description": "Dinner",
        "created_at": "2026-11-19T00:00:00Z",
    }


def test_nonparticipant_cannot_read_the_transfer(ledger):
    with read(ledger.path) as connection, pytest.raises(HistoryError) as failure:
        get_transfer(connection, user_id=CHARLIE, transfer_id=ledger.transfer_id)
    assert failure.value.code == "FORBIDDEN"
    assert str(ledger.transfer_id) not in failure.value.message


@pytest.mark.parametrize("target", ["missing", "deposit", "reversal"])
def test_non_transfer_ids_are_not_found(ledger, target):
    transfer_id = MISSING_ID if target == "missing" else ledger.deposit_id
    if target == "reversal":
        transfer_id = reverse(ledger)
    with read(ledger.path) as connection, pytest.raises(HistoryError) as failure:
        get_transfer(connection, user_id=ALICE, transfer_id=transfer_id)
    assert failure.value.code == "NOT_FOUND"


@pytest.mark.parametrize("value", ["malformed", ALICE_WALLET.hex, UUID(int=0), None])
def test_malformed_resource_ids_are_validation_errors(ledger, value):
    with read(ledger.path) as connection:
        for lookup, id_parameter in (
            (get_transfer, "transfer_id"),
            (list_wallet_history, "wallet_id"),
        ):
            with pytest.raises(HistoryError) as failure:
                lookup(connection, user_id=ALICE, **{id_parameter: value})
            assert failure.value.code == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    ("wallet_id", "code"),
    [(BOB_WALLET, "FORBIDDEN"), (SYSTEM, "FORBIDDEN"), (MISSING_ID, "NOT_FOUND")],
)
def test_history_requires_an_owned_wallet(ledger, wallet_id, code):
    with read(ledger.path) as connection, pytest.raises(HistoryError) as failure:
        list_wallet_history(connection, user_id=ALICE, wallet_id=wallet_id)
    assert failure.value.code == code


def test_history_entries_match_posted_records(ledger):
    reversal_id = reverse(ledger)
    with read(ledger.path) as connection:
        page = list_wallet_history(connection, user_id=ALICE, wallet_id=ALICE_WALLET)
        assert connection.in_transaction

    assert page == {
        "entries": [
            {
                "id": entry_id,
                "txn_id": str(txn_id),
                "wallet_id": str(ALICE_WALLET),
                "type": kind,
                "direction": direction,
                "amount_minor": amount,
                "currency": "INR",
                "created_at": "2026-11-19T00:00:00Z",
            }
            for entry_id, txn_id, kind, direction, amount in (
                (8, reversal_id, "REVERSAL", "CREDIT", 75),
                (5, ledger.transfer_id, "TRANSFER", "DEBIT", 75),
                (2, ledger.deposit_id, "DEPOSIT", "CREDIT", 1000),
            )
        ],
        "next_before_id": None,
    }


def test_empty_wallet_and_exhausted_cursor_return_terminal_pages(ledger):
    with read(ledger.path) as connection:
        empty_wallet = list_wallet_history(connection, user_id=ALICE, wallet_id=EMPTY_WALLET)
        exhausted = list_wallet_history(
            connection, user_id=ALICE, wallet_id=ALICE_WALLET, before_id=2
        )
    assert empty_wallet == exhausted == {"entries": [], "next_before_id": None}


def test_history_cursor_uses_entry_ids_and_excludes_intervening_posts(ledger):
    # A later post can have an older timestamp. The cursor follows entry IDs.
    deposit(ledger.path, stamp=datetime(2026, 11, 18, tzinfo=UTC))
    deposit(ledger.path)
    deposit(ledger.path)

    def page(before_id=None, *, limit=2):
        with read(ledger.path) as connection:
            return list_wallet_history(
                connection, user_id=ALICE, wallet_id=ALICE_WALLET, limit=limit, before_id=before_id
            )

    first = page()
    deposit(ledger.path)
    second = page(first["next_before_id"])
    terminal = page(second["next_before_id"], limit=1)
    fresh = page(limit=1)
    assert [entry["id"] for entry in first["entries"]] == [12, 10]
    assert first["next_before_id"] == 10
    assert [entry["id"] for entry in second["entries"]] == [8, 5]
    assert second["next_before_id"] == 5
    assert [entry["id"] for entry in terminal["entries"]] == [2]
    assert terminal["next_before_id"] is None
    assert [entry["id"] for entry in fresh["entries"]] == [14]
    assert fresh["next_before_id"] == 14


def test_history_uses_default_and_maximum_page_sizes(ledger):
    for _ in range(100):
        deposit(ledger.path)
    with read(ledger.path) as connection:
        first = list_wallet_history(connection, user_id=ALICE, wallet_id=ALICE_WALLET)
        max_page = list_wallet_history(
            connection, user_id=ALICE, wallet_id=ALICE_WALLET, limit=100, before_id=2**63 - 1
        )
    assert len(first["entries"]) == 20
    assert first["next_before_id"] == 168
    assert len(max_page["entries"]) == 100
    assert max_page["next_before_id"] == 8


@pytest.mark.parametrize(
    ("parameter", "value"),
    [("limit", value) for value in (0, -1, 101, True, 20.0, "20", None)]
    + [("before_id", value) for value in (0, -1, True, 1.0, "1", 2**63)],
)
def test_invalid_pagination_is_a_validation_error(ledger, parameter, value):
    with read(ledger.path) as connection, pytest.raises(HistoryError) as failure:
        list_wallet_history(connection, user_id=ALICE, wallet_id=ALICE_WALLET, **{parameter: value})
    assert failure.value.code == "VALIDATION_ERROR"


def test_read_services_require_an_active_caller_transaction(ledger):
    with closing(sqlite3.connect(ledger.path, isolation_level=None)) as connection:
        with pytest.raises(RuntimeError, match="active read transaction"):
            get_transfer(connection, user_id=ALICE, transfer_id=ledger.transfer_id)
        with pytest.raises(RuntimeError, match="active read transaction"):
            list_wallet_history(connection, user_id=ALICE, wallet_id=ALICE_WALLET)


@pytest.fixture
def history_client(ledger, monkeypatch, api_environment):
    TestClient = pytest.importorskip("fastapi.testclient").TestClient
    main = import_module("app.main")
    resolve_user = import_module("app.auth").authenticated_user_id
    database_class = import_module("app.database").SqliteDatabase
    transaction = database_class.transaction
    opened_reads = []

    def track_transaction(database, *, write=True):
        assert write is False
        opened_reads.append(database.path)
        return transaction(database, write=write)

    def track_resolver(connection, authorization):
        assert connection.in_transaction
        assert connection.execute("PRAGMA query_only").fetchone() == (1,)
        return resolve_user(connection, authorization)

    monkeypatch.setenv("DATABASE_PATH", str(ledger.path))
    monkeypatch.setattr(main, "authenticated_user_id", track_resolver)
    app = main.create_app()
    with TestClient(app) as client:
        monkeypatch.setattr(database_class, "transaction", track_transaction)
        yield client, opened_reads


def test_transfer_http_returns_the_posted_transfer_to_the_receiver(history_client, ledger):
    client, opened_reads = history_client
    response = client.get(
        f"/transfers/{ledger.transfer_id}", headers={"Authorization": "Bearer bob-test"}
    )
    assert response.status_code == 200
    assert response.json()["id"] == str(ledger.transfer_id)
    assert response.json()["to_wallet_id"] == str(BOB_WALLET)
    assert UUID(response.headers["X-Request-ID"]).version == 4
    assert len(opened_reads) == 1


@pytest.mark.parametrize(
    "path", [f"/wallets/{ALICE_WALLET}/transactions", f"/transfers/{MISSING_ID}"]
)
def test_history_routes_require_authentication_before_opening_a_snapshot(history_client, path):
    client, opened_reads = history_client
    response = client.get(path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert opened_reads == []


def test_invalid_bearer_is_rejected_on_the_same_read_snapshot(history_client, ledger):
    client, opened_reads = history_client
    response = client.get(
        f"/transfers/{ledger.transfer_id}", headers={"Authorization": "Bearer unknown-test"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert opened_reads == [ledger.path]


def test_wallet_history_http_uses_the_returned_cursor(history_client, ledger):
    client, _ = history_client
    path = f"/wallets/{ALICE_WALLET}/transactions"
    headers = {"Authorization": "Bearer alice-test"}
    first = client.get(path, params={"limit": 1}, headers=headers)
    assert first.status_code == 200
    page = first.json()
    assert [entry["txn_id"] for entry in page["entries"]] == [str(ledger.transfer_id)]

    second = client.get(path, params={"before_id": page["next_before_id"]}, headers=headers)
    assert second.status_code == 200
    assert [entry["txn_id"] for entry in second.json()["entries"]] == [str(ledger.deposit_id)]
    assert second.json()["next_before_id"] is None


@pytest.mark.parametrize(
    ("path", "status", "code"),
    [
        (f"/wallets/{BOB_WALLET}/transactions", 403, "FORBIDDEN"),
        (f"/transfers/{MISSING_ID}", 404, "NOT_FOUND"),
        ("/transfers/not-a-uuid", 422, "VALIDATION_ERROR"),
        (f"/wallets/{ALICE_WALLET}/transactions?limit=101", 422, "VALIDATION_ERROR"),
    ],
)
def test_history_http_uses_shared_error_envelopes(history_client, path, status, code):
    client, _ = history_client
    response = client.get(path, headers={"Authorization": "Bearer alice-test"})
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
