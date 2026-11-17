-- Migration 002: Enforce append-only immutability on transactions and ledger_entries (FR-4.1)

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

CREATE TRIGGER IF NOT EXISTS prevent_ledger_entries_update
BEFORE UPDATE ON ledger_entries
BEGIN
    SELECT RAISE(ABORT, 'FR-4.1 violation: ledger_entries table is immutable and cannot be updated');
END;

CREATE TRIGGER IF NOT EXISTS prevent_ledger_entries_delete
BEFORE DELETE ON ledger_entries
BEGIN
    SELECT RAISE(ABORT, 'FR-4.1 violation: ledger_entries table is immutable and cannot be deleted');
END;
