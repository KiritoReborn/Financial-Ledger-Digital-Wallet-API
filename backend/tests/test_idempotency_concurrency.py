"""B01b concurrent same-key requests and rollback on real WAL SQLite (FR-2.9, FR-2.10, TQ-2, TQ-4).

Each request uses its own connection from the shared SqliteDatabase provider,
exactly as concurrent HTTP requests will. BEGIN IMMEDIATE serializes them, so a
second request with the same key waits for the first to commit, then replays.
"""

import multiprocessing
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from app.contracts import IdempotencyRequest, OperationResult, PostingRequest
from app.contracts.fakes import FixedClock
from app.database import SqliteDatabase
from app.http import ApiError
from app.posting import LedgerPoster
from app.services.idempotency import SqliteRunIdempotent

STAMP = datetime(2026, 11, 25, tzinfo=UTC)
ALICE = UUID("00000000-0000-4000-8000-000000000301")
SYSTEM_INR = UUID("00000000-0000-4000-8000-000000000401")
ALICE_INR = UUID("00000000-0000-4000-8000-000000000402")
HOLD_SECONDS = 0.3  # How long the first request keeps the write lock after posting.


def seed(path: Path) -> SqliteDatabase:
    database = SqliteDatabase(path)
    database.initialize()
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO users (id, name, email, token_hash, created_at) "
            "VALUES (?, 'Alice', 'alice@example.test', 'hash-alice', 'now')",
            (str(ALICE),),
        )
        conn.executemany(
            "INSERT INTO wallets (id, user_id, currency, balance_minor, is_system, created_at) "
            "VALUES (?, ?, 'INR', 0, ?, 'now')",
            [(str(SYSTEM_INR), None, 1), (str(ALICE_INR), str(ALICE), 0)],
        )
    return database


@pytest.fixture
def database(tmp_path):
    return seed(tmp_path / "concurrency.sqlite3")


def request(key="same-key", amount=100):
    return IdempotencyRequest(ALICE, "DEPOSIT", key, ALICE_INR, {"amount_minor": amount})


def deposit_once(
    database: SqliteDatabase,
    idempotency_request: IdempotencyRequest,
    *,
    hold: float = 0.0,
    fail: bool = False,
    holding: threading.Event | None = None,
):
    """One complete request: own connection, BEGIN IMMEDIATE, run_idempotent, commit.

    `holding` is set once this request has posted and holds the write lock.
    """
    calls = 0
    with database.transaction() as conn:

        def operation() -> OperationResult:
            nonlocal calls
            calls += 1
            amount = idempotency_request.body["amount_minor"]
            posted = LedgerPoster(clock=FixedClock(STAMP))(
                conn, PostingRequest("DEPOSIT", SYSTEM_INR, ALICE_INR, amount, "INR")
            )
            if holding is not None:
                holding.set()
            time.sleep(hold)  # Keep the write lock so the other request must wait.
            if fail:
                raise RuntimeError("Injected failure after posting.")
            body = {"id": str(posted.txn_id), "type": "DEPOSIT", "amount_minor": amount}
            return OperationResult(201, body, posted.txn_id)

        result = SqliteRunIdempotent(clock=FixedClock(STAMP))(conn, idempotency_request, operation)
    return result, calls


def run_together(*jobs):
    """Start every job at the same moment on its own thread; return (results, errors)."""
    barrier = threading.Barrier(len(jobs))
    results, errors = [None] * len(jobs), [None] * len(jobs)

    def worker(index, job):
        barrier.wait()
        try:
            results[index] = job()
        except Exception as error:  # noqa: BLE001 - collected and asserted by the test.
            errors[index] = error

    threads = [threading.Thread(target=worker, args=item) for item in enumerate(jobs)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive(), "A concurrent request did not finish."
    return results, errors


def ledger_counts(database):
    with database.transaction(write=False) as conn:
        return {
            "transactions": conn.execute("SELECT count(*) FROM transactions").fetchone()[0],
            "entries": conn.execute("SELECT count(*) FROM ledger_entries").fetchone()[0],
            "keys": conn.execute("SELECT count(*) FROM idempotency_keys").fetchone()[0],
            "balance": conn.execute(
                "SELECT balance_minor FROM wallets WHERE id = ?", (str(ALICE_INR),)
            ).fetchone()[0],
        }


def test_two_concurrent_same_key_requests_post_exactly_once(database):
    results, errors = run_together(
        lambda: deposit_once(database, request(), hold=HOLD_SECONDS),
        lambda: deposit_once(database, request(), hold=HOLD_SECONDS),
    )

    assert errors == [None, None]
    outcomes = sorted(results, key=lambda item: item[0].replayed)
    (first, first_calls), (replay, replay_calls) = outcomes
    assert (first.replayed, replay.replayed) == (False, True)
    assert (first_calls, replay_calls) == (1, 0)
    assert (replay.status_code, dict(replay.body), replay.txn_id) == (
        first.status_code,
        dict(first.body),
        first.txn_id,
    )
    assert ledger_counts(database) == {"transactions": 1, "entries": 2, "keys": 1, "balance": 100}


def test_ten_concurrent_same_key_requests_create_one_transaction(database):
    results, errors = run_together(
        *[lambda: deposit_once(database, request(), hold=0.05) for _ in range(10)]
    )

    assert errors == [None] * 10
    assert sum(calls for _, calls in results) == 1
    assert sorted(result.replayed for result, _ in results) == [False] + [True] * 9
    assert len({result.txn_id for result, _ in results}) == 1
    assert ledger_counts(database) == {"transactions": 1, "entries": 2, "keys": 1, "balance": 100}


def test_concurrent_different_keys_all_post_without_lost_updates(database):
    results, errors = run_together(
        *[lambda key=f"key-{n}": deposit_once(database, request(key=key)) for n in range(10)]
    )

    assert errors == [None] * 10
    assert all(not result.replayed for result, _ in results)
    assert ledger_counts(database) == {
        "transactions": 10,
        "entries": 20,
        "keys": 10,
        "balance": 1000,
    }


def test_concurrent_same_key_with_different_body_conflicts(database):
    results, errors = run_together(
        lambda: deposit_once(database, request(amount=100), hold=HOLD_SECONDS),
        lambda: deposit_once(database, request(amount=500), hold=HOLD_SECONDS),
    )

    succeeded = [result for result in results if result is not None]
    rejected = [error for error in errors if error is not None]
    assert len(succeeded) == 1 and len(rejected) == 1
    assert isinstance(rejected[0], ApiError)
    assert (rejected[0].status, rejected[0].code) == (422, "IDEMPOTENCY_CONFLICT")
    amount = succeeded[0][0].body["amount_minor"]
    assert ledger_counts(database) == {
        "transactions": 1,
        "entries": 2,
        "keys": 1,
        "balance": amount,
    }


def test_waiting_same_key_request_runs_after_the_first_one_rolls_back(database):
    """FR-2.9 + FR-2.10: a failed holder stores no key, so the waiter posts instead."""
    first_has_lock = threading.Event()
    outcome = {}

    def failing_first():
        try:
            deposit_once(database, request(), hold=HOLD_SECONDS, fail=True, holding=first_has_lock)
        except RuntimeError as error:
            outcome["first"] = error

    first = threading.Thread(target=failing_first)
    first.start()
    assert first_has_lock.wait(timeout=10)
    # The first request has posted and holds the write lock, so this one must wait.
    second, second_calls = deposit_once(database, request())
    first.join(timeout=30)

    assert "Injected failure" in str(outcome["first"])
    assert (second.replayed, second_calls) == (False, 1)
    assert ledger_counts(database) == {"transactions": 1, "entries": 2, "keys": 1, "balance": 100}


def test_failure_mid_operation_rolls_back_ledger_balance_and_key(database):
    """TQ-2: the posting already ran when the failure happens; nothing of it may survive."""
    before = ledger_counts(database)

    with pytest.raises(RuntimeError, match="Injected failure"):
        deposit_once(database, request(), fail=True)

    assert ledger_counts(database) == before
    result, calls = deposit_once(database, request())
    assert (result.replayed, calls) == (False, 1)
    assert ledger_counts(database)["balance"] == 100


def _process_worker(path: str, start, results):
    start.wait(timeout=30)
    result, calls = deposit_once(SqliteDatabase(Path(path)), request(), hold=HOLD_SECONDS)
    results.put((result.replayed, calls, str(result.txn_id)))


def test_two_processes_with_same_key_post_exactly_once(tmp_path):
    """Same as the thread test, but with separate OS processes sharing the database file."""
    path = tmp_path / "processes.sqlite3"
    database = seed(path)
    context = multiprocessing.get_context("spawn")
    start, results = context.Event(), context.Queue()
    processes = [
        context.Process(target=_process_worker, args=(str(path), start, results))
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    start.set()
    outcomes = sorted(results.get(timeout=60) for _ in processes)
    for process in processes:
        process.join(timeout=30)
        assert process.exitcode == 0

    assert [(replayed, calls) for replayed, calls, _ in outcomes] == [(False, 1), (True, 0)]
    assert outcomes[0][2] == outcomes[1][2]
    assert ledger_counts(database) == {"transactions": 1, "entries": 2, "keys": 1, "balance": 100}
