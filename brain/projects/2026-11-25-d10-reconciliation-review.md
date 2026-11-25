---
title: "D10 financial integrity, reversal, and reconciliation review"
author: "Gangavarapu Jaswant (D)"
date: "2026-11-25"
category: "projects"
tags: ["reconciliation", "reversal", "immutability", "review", "security"]
requirements:
  - "FR-4.1"
  - "FR-4.2"
  - "FR-4.3"
  - "FR-4.4"
  - "FR-4.5"
  - "FR-5.1"
  - "FR-5.2"
  - "FR-5.3"
  - "FR-5.4"
  - "NFR-SEC-2"
  - "NFR-SEC-7"
  - "CA-3"
source: "Final SRS FR-4.1 to FR-5.4; revised work plan D10"
---

# D10 financial integrity, reversal, and reconciliation review

End-to-end architecture and risk review across Member D's backend integrity
deliverables (`D01`, `D02`, `D03`, `D04`, `D09`) and their integration with
shared database, posting, auth, and idempotency modules.

## Code & Documentation Reviewed

- `db/migrations/002_immutability_triggers.sql` (`FR-4.1` triggers) and
  `tests/test_immutability_triggers.py` (`D01`)
- `backend/app/services/reconciliation.py` (`reconcile`, `sqlite_read_snapshot`)
  and `backend/tests/test_reconciliation.py` (`D03`)
- `backend/app/services/reversal.py` (`reverse_transaction`) and
  `backend/tests/test_reversal.py` (`D02`)
- `backend/app/api/admin.py` (`GET /admin/reconcile`,
  `POST /transactions/{id}/reverse`) and `tests/test_admin_security.py` (`D04`)
- `backend/app/posting.py` (`LedgerPoster`),
  `backend/app/services/idempotency.py` (`run_idempotent`), and
  `docs/admin-security.md` (`D09`)

## Design Decisions & Mitigated Risks

1. **Exact Python-integer accumulation in reconciliation (`FR-5.2`, `NFR-PREC-1`):**
   Cumulative lifetime debit and credit totals can exceed SQLite's signed
   64-bit integer range even when every individual transaction (`<= 10^12`) and
   wallet balance fits cleanly. Following PR #24, `_currencies_balanced` and
   `_wallet_balances_match` accumulate amounts in Python arbitrary-precision
   integers inside the single read transaction, eliminating overflow false
   positives. See [[2026-11-20-d03-reconciliation]].
2. **Single `BEGIN DEFERRED` read snapshot (`FR-5.4`):**
   Opening one read-only connection (`mode=ro`, `PRAGMA query_only = ON`) with
   `BEGIN DEFERRED` pins the WAL `end-mark` on the first `SELECT`. Concurrent
   writes (`BEGIN IMMEDIATE`) neither block reconciliation nor create
   cross-check skew across checks `(a)`–`(d)`. See
   [[sqlite-read-only-transaction-snapshots]].
3. **Caller-owned write transactions with zero internal commits (`FR-3.1`, `NFR-REL-1`):**
   `reverse_transaction` requires an active `BEGIN IMMEDIATE` transaction from
   `SqliteDatabase.transaction()`, delegates entry insertion and conditional
   debit updates to `LedgerPoster`, and runs inside `run_idempotent`
   (`scope="REVERSAL"`). Any `INSUFFICIENT_FUNDS`, `ALREADY_REVERSED`, or
   injected mid-operation failure rolls back the entire transaction—including
   the idempotency row—so clients can retry safely with the same key (`FR-2.9`).
   See [[projects/2026-11-25-d02-reversal]] and [[projects/2026-11-20-c04-posting]].
4. **Constant-time dual-credential admin boundary (`FR-1.9`, `NFR-SEC-2`, `NFR-SEC-7`):**
   Both `ADMIN_TOKEN` (hashed with SHA-256) and `X-Admin-Key` (never stored in
   SQLite) are compared via `hmac.compare_digest` without short-circuiting,
   backed by `authenticated_user_id == ADMIN_ID` in SQLite. Failures return
   uniform `401` / `500` / `503` envelopes without leaking SQL, paths, or
   secrets. See [[constant-time-secret-comparison]] and
   [[projects/2026-11-25-d04-d08-security-ci]].
5. **Database-enforced append-only boundary (`FR-4.1`, `CA-3`):**
   Migration 002 triggers prevent SQL `UPDATE` and `DELETE` on `transactions`
   and `ledger_entries` while allowing `wallets.balance_minor` updates and
   preserving `DB-3` currency consistency. Per `CA-3`, documentation explicitly
   states the ledger is database-enforced append-only rather than
   tamper-evident against direct filesystem edits. See
   [[sqlite-immutability-triggers]].

## Remaining Follow-Up Outside Backend Scope

- `D05` Admin React UI page remains to be connected once the `H07` Vite/React
  shell is merged on `main`.
