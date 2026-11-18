---
title: "SQLite BEFORE UPDATE and DELETE Triggers for Append-Only Ledger Tables"
author: "Gangavarapu Jaswant (D)"
date: "2026-11-18"
category: "resources"
tags: ["sqlite", "triggers", "immutability", "audit-trail", "double-entry-ledger"]
requirements: ["FR-4.1", "FR-4.2", "FR-4.3", "BR-7", "CA-1", "CA-2", "CA-3"]
source: "https://www.sqlite.org/lang_createtrigger.html"
---

# SQLite BEFORE UPDATE and DELETE Triggers for Append-Only Ledger Tables

## Context & Requirements

The Financial Ledger & Digital Wallet API must preserve an immutable audit trail of every monetary event:

- **FR-4.1**: Triggers installed by migration 002 must reject every `UPDATE` and `DELETE` on `ledger_entries` and `transactions`, and the REST API exposes no endpoint that updates or deletes either table.
- **BR-7**: Ledger records are never changed or deleted; mistakes are corrected exclusively by reversal.
- **CA-1 & CA-2**: Every `ledger_entries` row records its transaction, wallet, direction, amount, currency, and server-assigned UTC ISO 8601 `created_at`; every `transactions` row records type, creation time, description, and (for reversals) `reverses_txn_id`. Records are retained for the life of the database without purging.
- **CA-3**: Documentation describes the ledger as **database-enforced append-only**, not tamper-evident.

## Mechanism (`RAISE(ABORT, ...)`)

In SQLite, `BEFORE UPDATE` and `BEFORE DELETE` triggers fire prior to any row modification. Calling `SELECT RAISE(ABORT, ...)` inside the trigger body raises `SQLITE_CONSTRAINT_TRIGGER` (surfaced in Python's `sqlite3` module as `sqlite3.IntegrityError`), cancels the current SQL statement, and leaves existing rows untouched.

Pattern implemented in [002_immutability_triggers.sql](file:///Users/jaswanth/Desktop/-/db/migrations/002_immutability_triggers.sql):

```sql
CREATE TRIGGER IF NOT EXISTS prevent_transactions_update
BEFORE UPDATE ON transactions
BEGIN
    SELECT RAISE(ABORT, 'FR-4.1 violation: transactions table is immutable and cannot be updated');
END;

CREATE TRIGGER IF NOT EXISTS prevent_transactions_delete
BEFORE DELETE ON transactions
BEGIN
    SELECT RAISE(ABORT, 'FR-4.1 violation: transactions table is immutable and cannot be deleted');
END;
```

Equivalent `BEFORE UPDATE` and `BEFORE DELETE` triggers (`prevent_ledger_entries_update` and `prevent_ledger_entries_delete`) protect `ledger_entries`. `IF NOT EXISTS` keeps migration 002 idempotent (`DB-6`).

## Error Correction via Reversals

Because `transactions` and `ledger_entries` reject updates and deletes (`FR-4.1`), errors are corrected only by appending a new `REVERSAL` transaction (`FR-4.2`, `FR-4.3`):

1. Only `TRANSFER` and `DEPOSIT` transactions can be reversed; reversing a `REVERSAL` returns `422 NOT_REVERSIBLE`.
2. Each original transaction can be reversed at most once, backed by a `UNIQUE` constraint on `transactions.reverses_txn_id` (second reversal returns `409 ALREADY_REVERSED`).
3. The reversal transaction inserts two mirroring `ledger_entries` with `DEBIT` and `CREDIT` swapped while keeping the original transaction and its entries intact.

## Scope & Limitations (`CA-3`)

SQLite triggers enforce append-only behavior only through normal SQL connections to the database. Because the database is a single local SQLite file (`C-1`), anyone with direct filesystem access could drop the triggers or insert a balanced, fabricated transaction that reconciliation cannot detect (`CA-3`).

## Related Notes

- [[constant-time-secret-comparison]]
- [[sqlite-read-only-transaction-snapshots]]
