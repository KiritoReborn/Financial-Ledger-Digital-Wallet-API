---
title: "B01b concurrent same-key requests and rollback"
date: "2026-11-25"
author: "P. Pranav Sai (B), AI-assisted"
category: projects
type: ai-session
tags: [member-b, b01, idempotency, concurrency, sqlite]
requirements: [FR-2.9, FR-2.10, FR-3.1, TQ-2, TQ-4, TQ-5]
source: "Issue #32, final SRS section 4.2, ADR 0002"
---

# B01b concurrent same-key requests and rollback (AI-assisted)

**Goal.** Prove the last B01 acceptance point, "concurrent same key posts once"
(FR-2.10), and that a failed operation leaves no key behind (FR-2.9), using
separate connections the way concurrent HTTP requests will.

**What was tested.** `backend/tests/test_idempotency_concurrency.py` has 7 tests on
a fresh WAL SQLite file per test, through the shared `SqliteDatabase` provider and
C04's `LedgerPoster`:

- Two threads with the same key, started together: one transaction, one key, and
  the second request gets the first one's response marked as a replay.
- Ten threads with the same key: one transaction and nine replays.
- Ten threads with different keys: ten transactions and a final balance of 1000,
  so no update was lost.
- Same key with different amounts at the same time: one succeeds, the other gets
  422 `IDEMPOTENCY_CONFLICT`.
- A request that fails while holding the lock: the waiting request with the same
  key finds no key and posts once itself.
- A failure after posting rolls back the ledger rows, the balance and the key (TQ-2).
- Two separate OS processes with the same key: one transaction, one replay.

**What worked.** No code change was needed. `BEGIN IMMEDIATE` in the H03 provider
makes the second request wait for the write lock, as [ADR 0002](../../docs/adr/0002-idempotency-fingerprint-and-replay.md)
predicted. The suite was run five times in a row without a failure.

**What to watch.** The tests hold the lock for at most 0.3 s, well under the
5000 ms busy timeout. A holder longer than the timeout gives 503 `DATABASE_BUSY`
(FR-3.4), which is Member C's area.

Related: [[projects/2026-11-25-b01-idempotency]], [[resources/idempotency-keys-and-request-fingerprints]], [[log]].
