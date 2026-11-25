# Admin Operations & Security Guide

Operational and security reference for the administrative endpoints and
ledger-integrity controls of the **Financial Ledger & Digital Wallet API**
(`FR-4.1`–`FR-5.4`, `NFR-SEC-1`, `NFR-SEC-2`, `NFR-SEC-7`, `SAF-1`, `CA-3`).

---

## 1. Safety & Compliance Disclaimers (`SAF-1`, `CA-3`)

- **Simulated funds only (`SAF-1`):** All balances and transfers represent
  simulated minor-unit integer values (`INR`, `USD`, `JPY`). This system must
  never hold, settle, or move real money.
- **Demonstration-level authentication (`SAF-1`):** Bearer tokens and
  `X-Admin-Key` exist to demonstrate API boundaries and constant-time checks;
  they are not production-grade authentication.
- **Database-enforced append-only, not tamper-evident (`CA-3`):** SQLite
  `BEFORE UPDATE` and `BEFORE DELETE` triggers (`db/migrations/002_immutability_triggers.sql`,
  `FR-4.1`) reject mutations to `transactions` and `ledger_entries` over SQL
  connections. The ledger does **not** maintain a cryptographic hash chain; an
  operator with direct filesystem access to the SQLite file could drop triggers
  or insert balanced rows that reconciliation cannot detect.

---

## 2. Admin Authentication & Startup Checks (`FR-1.9`, `NFR-SEC-2`, `BR-5`)

Administrative routes (`GET /admin/reconcile` and
`POST /transactions/{id}/reverse`) require **both**:

1. `Authorization: Bearer <admin-token>` — matched against the SHA-256 digest
   of `ADMIN_TOKEN` and verified against the reserved administrator user row
   (`ADMIN_ID` in `backend/app/auth.py`).
2. `X-Admin-Key: <admin-key>` — matched against the SHA-256 digest of
   `ADMIN_KEY` using `hmac.compare_digest` without short-circuiting.

Key operational rules:

- **Fail-closed startup (`FR-1.9`):** `create_app()`'s ASGI lifespan refuses to
  start with a `ValueError` if either `ADMIN_TOKEN` or `ADMIN_KEY` is missing or
  whitespace-only.
- **No database storage of `ADMIN_KEY` (`NFR-SEC-2`):** Only the SHA-256 hex
  digest of `ADMIN_TOKEN` is stored on the admin user row; `ADMIN_KEY` remains
  in process memory only.
- **Uniform `401 UNAUTHENTICATED` (`NFR-SEC-1`):** Missing, blank, non-admin, or
  mismatched credentials return the same `401` envelope with
  `WWW-Authenticate: Bearer` before opening or mutating ledger data.
- **No secret logging (`NFR-SEC-7`):** Error responses omit stack traces, SQL
  statements, filesystem paths, tokens, admin keys, and idempotency keys.

---

## 3. Read-Only Ledger Reconciliation (`GET /admin/reconcile`, `FR-5.1`–`FR-5.4`)

`GET /admin/reconcile` verifies four invariants sequentially inside a single
read-only SQLite snapshot (`mode=ro`, `PRAGMA query_only = ON`,
`BEGIN DEFERRED`, ending with `ROLLBACK`) so concurrent WAL writers neither
block nor skew intermediate results:

| Check | Invariant (`FR-5.2`) | Notes |
| --- | --- | --- |
| `currencies_balanced` | Total debits equal total credits per currency (including system wallets) | Accumulated in Python arbitrary-precision integers to avoid 64-bit SQLite `SUM` overflow |
| `transactions_valid` | Every transaction owns 2 entries (`1 DEBIT`, `1 CREDIT`) in one currency with equal amounts | Flags missing, one-sided, or unbalanced entries |
| `wallet_balances_match` | Each wallet's cached `balance_minor` equals `SUM(CREDIT) - SUM(DEBIT)` | Covers both user and system wallets |
| `entry_currencies_match` | Every `ledger_entries.currency` matches its wallet's `currency` | Backstops `DB-3` insert trigger |

Example invocation (reading credentials from environment variables):

```bash
curl --silent --show-error \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "X-Admin-Key: ${ADMIN_KEY}" \
  "http://127.0.0.1:${PORT:-8000}/admin/reconcile"
```

Completed runs always return HTTP `200` with `{ "ok", "checks", "mismatches" }`.
When tampering or corruption is detected, `ok` is `false` and each mismatch
identifies the failing check, affected currency/wallet/transaction ID, and
expected vs. actual values (`FR-5.3`).

---

## 4. Idempotent Transaction Reversals (`POST /transactions/{id}/reverse`, `FR-4.2`–`FR-4.5`)

Mistakes on posted `DEPOSIT` or `TRANSFER` transactions are corrected solely by
appending a `REVERSAL` transaction (`BR-7`), never by updating or deleting
existing rows.

- **Required headers:** `Authorization: Bearer <admin-token>`,
  `X-Admin-Key: <admin-key>`, and `Idempotency-Key` (`1..128` chars from
  `[A-Za-z0-9_.:-]`, scope `REVERSAL`).
- **Optional body:** Empty body or `{}` (`extra="forbid"`).
- **Invariants & errors:**
  - Missing/blank `Idempotency-Key` -> `400 IDEMPOTENCY_KEY_MISSING`
  - Malformed key, UUID, or unknown body field -> `422 VALIDATION_ERROR`
  - Unknown `{id}` -> `404 NOT_FOUND`
  - Reversing a `REVERSAL` -> `422 NOT_REVERSIBLE`
  - Already reversed (`UNIQUE` `reverses_txn_id` backstop) -> `409 ALREADY_REVERSED`
  - Reversal would drop a non-system wallet below `0` -> `422 INSUFFICIENT_FUNDS`
    (rolls back caller `BEGIN IMMEDIATE` transaction and stores no idempotency
    key so the client can retry with the same key once funded, `FR-2.9`, `FR-4.5`)
  - Replay with identical key and target -> `201` with `Idempotent-Replayed: true`
  - Reuse of same key on a different target -> `422 IDEMPOTENCY_CONFLICT`

---

## 5. Pre-Release Verification Checklist (`DI-1`, `VC-5`)

Before tagging a release:

1. Ensure `.env` is untracked and `.env.example` contains placeholder keys only.
2. Run repository docs/skill validation: `python scripts/validate_repo_docs.py`.
3. Run full test and lint suites: `pytest -q backend/tests tests`, `ruff check .`,
   and `ruff check backend`.
4. Verify package build and clean-install smoke test (`python -m build`,
   `local-check` workflow).
5. Confirm `GET /admin/reconcile` returns `{"ok": true, ...}` on a seeded demo
   database after deposit, transfer, and reversal flows.
