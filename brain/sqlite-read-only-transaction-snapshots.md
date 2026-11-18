---
title: "Read-Only Transaction Snapshots (BEGIN DEFERRED) for Ledger Reconciliation"
author: "Gangavarapu Jaswant (D)"
date: "2026-11-18"
category: "resources"
tags: ["sqlite", "wal", "transactions", "reconciliation", "snapshot-isolation"]
requirements: ["FR-5.1", "FR-5.2", "FR-5.3", "FR-5.4", "FR-3.1", "EI-SW-3", "C-1", "BR-8"]
source: "https://www.sqlite.org/lang_transaction.html"
---

# Read-Only Transaction Snapshots (`BEGIN DEFERRED`) for Ledger Reconciliation

## Context & Requirements

`GET /admin/reconcile` (`FR-5.1`–`FR-5.4`) verifies ledger integrity without modifying any database state:

- **FR-5.4**: Reconciliation must not modify data and must run all checks sequentially on one connection inside a single read transaction so every check observes the exact same snapshot.
- **EI-SW-3 & C-1**: Each request opens one SQLite connection configured with `journal_mode=WAL`, `foreign_keys=ON`, `busy_timeout=5000`, and `synchronous=FULL`.
- **FR-3.1**: Concurrent financial writes (`deposit`, `transfer`, `reversal`) serialize via `BEGIN IMMEDIATE`.

## Why Separate Autocommit Queries Fail

In autocommit mode, each `SELECT` opens and closes its own implicit read transaction. If a concurrent `POST /transfers` or `POST /transactions/{id}/reverse` commits between two reconciliation queries:

1. Check `(a)` could observe the ledger *before* the new transaction commits.
2. Check `(c)` could observe updated `wallets.balance_minor` values *after* the commit, or partial cross-table state relative to earlier checks.

This skew would trigger false-positive reconciliation mismatches (`ok = false`) even though every committed write transaction was atomic.

## Snapshot Isolation in WAL Mode (`BEGIN DEFERRED`)

In SQLite WAL mode (`C-1`), `BEGIN DEFERRED` (or `BEGIN`) starts a transaction without immediately acquiring a database lock. On the first `SELECT` inside that transaction, SQLite records the WAL `end-mark` representing the latest committed frame at that instant:

- All subsequent `SELECT` queries on the same connection read from that pinned `end-mark` snapshot (`FR-5.4`).
- Concurrent writers using `BEGIN IMMEDIATE` (`FR-3.1`) append new frames to the WAL without being blocked by the reader and without altering the reader's pinned snapshot.
- Because reconciliation issues no write statements, the transaction never upgrades to a `RESERVED` or `EXCLUSIVE` lock and ends cleanly with `COMMIT` or `ROLLBACK`.

```python
conn.execute("BEGIN DEFERRED;")
try:
    # Run FR-5.2 checks (a), (b), (c), (d) sequentially on `conn`
    ...
finally:
    conn.rollback()  # Explicit read-only cleanup
```

## The Four Reconciliation Checks (`FR-5.2` & `FR-5.3`)

Inside the single `BEGIN DEFERRED` snapshot, reconciliation runs four checks (`BR-8`, `FR-5.2`) and returns `{ ok, checks, mismatches }` with HTTP `200` (`FR-5.3`, where `ok = false` if any mismatch is found):

- **(a) Currency balance conservation**: For every currency (including system wallets), total `DEBIT` amounts equal total `CREDIT` amounts.
- **(b) Double-entry transaction structure**: Every row in `transactions` owns exactly two `ledger_entries`—one `DEBIT` and one `CREDIT`—in a single currency.
- **(c) Cached balance consistency**: Every wallet's `balance_minor` equals `SUM(CREDIT) - SUM(DEBIT)` across its `ledger_entries`.
- **(d) Wallet-entry currency alignment**: Every `ledger_entries.currency` matches the `currency` of its referenced `wallets` row.

## Related Notes

- [[sqlite-immutability-triggers]]
- [[constant-time-secret-comparison]]
