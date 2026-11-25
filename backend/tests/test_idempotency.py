"""B01 run_idempotent on a real migrated, file-backed SQLite database (FR-2.4 to FR-2.9, TQ-1)."""

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from uuid import UUID

import pytest
from app.contracts import IdempotencyRequest, OperationResult, PostingRequest, RunIdempotent
from app.contracts.fakes import FixedClock
from app.database import SqliteDatabase
from app.http import ApiError
from app.posting import LedgerPoster
from app.services.idempotency import (
    SqliteRunIdempotent,
    parse_idempotency_key,
    request_fingerprint,
    run_idempotent,
)

STAMP = datetime(2026, 11, 25, tzinfo=UTC)
ALICE, BOB = (UUID(f"00000000-0000-4000-8000-0000000001{i:02d}") for i in (1, 2))
SYSTEM_INR, ALICE_INR, BOB_INR = (
    UUID(f"00000000-0000-4000-8000-0000000002{i:02d}") for i in (1, 2, 3)
)


@pytest.fixture
def database(tmp_path):
    database = SqliteDatabase(tmp_path / "idempotency.sqlite3")
    database.initialize()
    with database.transaction() as conn:
        for user in (ALICE, BOB):
            conn.execute(
                "INSERT INTO users (id, name, email, token_hash, created_at) "
                "VALUES (?, 'Example', ?, ?, 'now')",
                (str(user), f"{user}@example.test", f"hash-{user}"),
            )
        for wallet, owner in ((SYSTEM_INR, None), (ALICE_INR, ALICE), (BOB_INR, BOB)):
            conn.execute(
                "INSERT INTO wallets (id, user_id, currency, balance_minor, is_system, created_at) "
                "VALUES (?, ?, 'INR', 0, ?, 'now')",
                (str(wallet), None if owner is None else str(owner), int(owner is None)),
            )
    return database


@pytest.fixture
def wrapper():
    return SqliteRunIdempotent(clock=FixedClock(STAMP))


def deposit_request(*, user=ALICE, key="deposit-1", target=ALICE_INR, amount=100, scope="DEPOSIT"):
    return IdempotencyRequest(user, scope, key, target, {"amount_minor": amount})


class Deposit:
    """Operation that really posts, so tests can count transactions and balances."""

    def __init__(self, conn, *, wallet=ALICE_INR, amount=100, fail_after_posting=False):
        self.conn, self.wallet, self.amount = conn, wallet, amount
        self.fail_after_posting = fail_after_posting
        self.calls = 0

    def __call__(self) -> OperationResult:
        self.calls += 1
        posted = LedgerPoster(clock=FixedClock(STAMP))(
            self.conn,
            PostingRequest("DEPOSIT", SYSTEM_INR, self.wallet, self.amount, "INR"),
        )
        if self.fail_after_posting:
            raise RuntimeError("Injected failure after posting.")
        body = {"id": str(posted.txn_id), "type": "DEPOSIT", "amount_minor": self.amount}
        return OperationResult(201, body, posted.txn_id)


def run(database, wrapper, request, **operation_options):
    with database.transaction() as conn:
        operation = Deposit(conn, **operation_options)
        return wrapper(conn, request, operation), operation.calls


def state(database):
    with database.transaction(write=False) as conn:
        return [
            conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()
            for table in ("wallets", "transactions", "ledger_entries", "idempotency_keys")
        ]


def count(database, table):
    with database.transaction(write=False) as conn:
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


# FR-2.4: header validation


@pytest.mark.parametrize("value", [None, "", " ", "\t \t"])
def test_missing_or_blank_key_is_400(value):
    with pytest.raises(ApiError) as error:
        parse_idempotency_key(value)
    assert (error.value.status, error.value.code) == (400, "IDEMPOTENCY_KEY_MISSING")


@pytest.mark.parametrize(
    "value", ["a b", " key", "key\n", "a/b", "x" * 129, "clé", "key\x00", "a;b", "*"]
)
def test_invalid_key_is_422_and_not_echoed(value):
    with pytest.raises(ApiError) as error:
        parse_idempotency_key(value)
    assert (error.value.status, error.value.code) == (422, "VALIDATION_ERROR")
    assert value not in error.value.message


@pytest.mark.parametrize("value", ["a", "x" * 128, "A-z_0.9:Z", "550e8400-e29b-41d4-a716-446655440000"])
def test_valid_keys_are_returned_unchanged(value):
    assert parse_idempotency_key(value) == value


# FR-2.6 and TQ-1: request fingerprint


def test_fingerprint_is_sha256_of_scope_target_and_canonical_body():
    body = {"to_wallet_id": "b", "amount_minor": 100, "from_wallet_id": "a"}
    expected = hashlib.sha256(
        b'TRANSFER\n\n{"amount_minor":100,"from_wallet_id":"a","to_wallet_id":"b"}'
    ).hexdigest()
    assert request_fingerprint("TRANSFER", None, body) == expected


def test_fingerprint_ignores_key_order():
    first = {"a": 1, "b": {"y": 2, "x": [3, 4]}}
    second = json.loads('{"b": {"x": [3, 4], "y": 2}, "a": 1}')
    assert request_fingerprint("DEPOSIT", ALICE_INR, first) == request_fingerprint(
        "DEPOSIT", ALICE_INR, second
    )


@pytest.mark.parametrize(
    ("scope", "target", "body"),
    [
        ("TRANSFER", ALICE_INR, {"amount_minor": 100}),
        ("DEPOSIT", BOB_INR, {"amount_minor": 100}),
        ("DEPOSIT", ALICE_INR, {"amount_minor": 101}),
        ("DEPOSIT", ALICE_INR, {"amount_minor": "100"}),
        ("DEPOSIT", ALICE_INR, {"amount_minor": 100, "description": None}),
    ],
)
def test_fingerprint_changes_with_operation_target_or_body(scope, target, body):
    base = request_fingerprint("DEPOSIT", ALICE_INR, {"amount_minor": 100})
    assert request_fingerprint(scope, target, body) != base


def test_fingerprint_rejects_unknown_scope_and_non_json_values():
    with pytest.raises(ValueError):
        request_fingerprint("WITHDRAW", None, {})
    with pytest.raises(ValueError):
        request_fingerprint("DEPOSIT", None, {"amount_minor": float("nan")})


# FR-2.5, FR-2.7 to FR-2.9: replay wrapper


def test_implements_the_c03_protocol():
    assert isinstance(run_idempotent, RunIdempotent)
    assert isinstance(SqliteRunIdempotent(), RunIdempotent)


def test_requires_caller_owned_transaction(database, wrapper):
    with (
        closing(sqlite3.connect(database.path, isolation_level=None)) as conn,
        pytest.raises(RuntimeError, match="caller-owned"),
    ):
        wrapper(conn, deposit_request(), lambda: None)
    assert count(database, "idempotency_keys") == 0


def test_first_request_runs_operation_and_stores_response(database, wrapper):
    result, calls = run(database, wrapper, deposit_request())

    assert calls == 1
    assert (result.status_code, result.replayed) == (201, False)
    with database.transaction(write=False) as conn:
        row = conn.execute("SELECT * FROM idempotency_keys").fetchone()
    assert row == (
        str(ALICE),
        "DEPOSIT",
        "deposit-1",
        request_fingerprint("DEPOSIT", ALICE_INR, {"amount_minor": 100}),
        201,
        json.dumps(dict(result.body), sort_keys=True, separators=(",", ":")),
        str(result.txn_id),
        "2026-11-25T00:00:00Z",
    )


def test_same_request_replays_stored_response_without_new_transaction(database, wrapper):
    first, _ = run(database, wrapper, deposit_request())
    before = state(database)

    replay, calls = run(database, wrapper, deposit_request())

    assert calls == 0
    assert replay.replayed is True
    assert (replay.status_code, dict(replay.body), replay.txn_id) == (
        first.status_code,
        dict(first.body),
        first.txn_id,
    )
    assert state(database) == before
    assert count(database, "transactions") == 1


def test_reused_key_with_different_request_conflicts_and_changes_nothing(database, wrapper):
    run(database, wrapper, deposit_request(amount=100))
    before = state(database)

    with pytest.raises(ApiError) as error:
        run(database, wrapper, deposit_request(amount=999))

    assert (error.value.status, error.value.code) == (422, "IDEMPOTENCY_CONFLICT")
    assert state(database) == before


def test_reused_key_with_different_target_conflicts(database, wrapper):
    run(database, wrapper, deposit_request(target=ALICE_INR))
    with pytest.raises(ApiError) as error:
        run(database, wrapper, deposit_request(target=BOB_INR))
    assert error.value.code == "IDEMPOTENCY_CONFLICT"


def test_keys_are_scoped_by_user_and_operation(database, wrapper):
    run(database, wrapper, deposit_request(user=ALICE, key="shared"))
    _, other_user_calls = run(
        database, wrapper, deposit_request(user=BOB, key="shared", target=BOB_INR), wallet=BOB_INR
    )
    _, other_scope_calls = run(database, wrapper, deposit_request(key="shared", scope="TRANSFER"))

    assert (other_user_calls, other_scope_calls) == (1, 1)
    assert count(database, "idempotency_keys") == 3
    assert count(database, "transactions") == 3


def test_failed_operation_stores_no_key_and_same_key_can_retry(database, wrapper):
    before = state(database)

    with pytest.raises(RuntimeError, match="Injected failure"):
        run(database, wrapper, deposit_request(), fail_after_posting=True)

    assert state(database) == before
    result, calls = run(database, wrapper, deposit_request())
    assert (calls, result.replayed) == (1, False)
    assert count(database, "transactions") == 1


def test_invalid_key_is_rejected_before_the_operation_runs(database, wrapper):
    before = state(database)
    with pytest.raises(ApiError) as error:
        run(database, wrapper, deposit_request(key="not valid"))
    assert error.value.code == "VALIDATION_ERROR"
    assert state(database) == before


def test_unsuccessful_or_non_json_results_are_never_stored(database, wrapper):
    before = state(database)

    with pytest.raises(RuntimeError), database.transaction() as conn:
        wrapper(conn, deposit_request(), lambda: OperationResult(422, {}, ALICE_INR))
    with pytest.raises(TypeError), database.transaction() as conn:
        wrapper(conn, deposit_request(), lambda: OperationResult(201, {"id": ALICE_INR}, ALICE_INR))
    with pytest.raises(TypeError), database.transaction() as conn:
        wrapper(conn, deposit_request(), lambda: {"status": 201})

    assert state(database) == before
