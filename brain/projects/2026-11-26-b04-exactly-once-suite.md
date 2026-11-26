---
title: "B04 exactly-once and negative suite over HTTP"
date: "2026-11-26"
author: "P. Pranav Sai (B), AI-assisted"
category: projects
type: ai-session
tags: [member-b, b04, idempotency, concurrency, testing]
requirements: [FR-2.4, FR-2.7, FR-2.8, FR-2.9, FR-2.10, TQ-3, TQ-4, TQ-5, TQ-8]
source: "Final SRS sections 3.2 and 5, revised work distribution page 8, C04 50-writer run"
---

# B04 exactly-once and negative suite over HTTP (AI-assisted)

**Goal.** Prove end to end over HTTP that deposits and transfers happen exactly
once, that races never overdraw a wallet, and that every rejection leaves the
ledger unchanged (TQ-3, TQ-4).

**What was built.** `backend/tests/test_exactly_once_http.py` has 30 tests. Each
uses a fresh temporary SQLite file (TQ-5) and the real `POST /users`,
`POST /wallets`, deposit and `POST /transfers` routes. Concurrent cases release
all threads together through a barrier. Each request opens its own connection
and `BEGIN IMMEDIATE` transaction, as under a real server.

**Evidence.**
- 50 competing transfers of 3,000 from a wallet holding 100,000: 33 commit,
  17 get `INSUFFICIENT_FUNDS`, the sender keeps 1,000, the receiver holds 99,000,
  68 entries, and reconcile and `PRAGMA integrity_check` pass. This repeats the
  service-level run from [[projects/2026-11-20-c04-posting]] over HTTP.
- The 17 rejected keys were stored nowhere, so each succeeds once the sender is
  funded again.
- 2 and 10 concurrent same-key transfers, and 10 same-key deposits, post once.
  One response says `Idempotent-Replayed: false`, the rest `true`, and all bodies
  match.
- Concurrent same-key requests with two different bodies: only the first body to
  commit posts; every request with the other body gets `IDEMPOTENCY_CONFLICT`.
- 20 concurrent transfers with different keys lose no update.
- A replay matches the original status, body and content type, still succeeds
  after the balance is spent, and survives an application restart.
- Reordered JSON keys and extra whitespace replay; keys are case-sensitive.
- A conflict reveals nothing about the stored response, and another user's
  token with the same key and body gets 403, not a replay.
- A failure after the ledger rows are written returns 500 and rolls back the
  entries, balances and key; the same key then succeeds.
- A held write lock past the busy timeout gives 503 `DATABASE_BUSY` and stores
  nothing.
- Errors come in a fixed order on both endpoints: 401, then 400 or 422 for the
  key, then 403 or 404. No error response carries `Idempotent-Replayed`.

The file passed five repeated runs.

**Defects.** The suite found none in deposit, transfer or idempotency
behaviour. It started `docs/defect-log.md`.

Related: [[projects/2026-11-25-b03-transfers]], [[projects/2026-11-25-b01b-idempotency-concurrency]], [[log]].
