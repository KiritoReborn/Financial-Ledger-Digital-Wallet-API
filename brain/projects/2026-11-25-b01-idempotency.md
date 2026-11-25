---
title: "B01 run_idempotent core"
date: "2026-11-25"
author: "P. Pranav Sai (B), AI-assisted"
category: projects
type: ai-session
tags: [member-b, b01, idempotency, sqlite]
requirements: [FR-2.4, FR-2.5, FR-2.6, FR-2.7, FR-2.8, FR-2.9, TQ-1, TQ-4]
source: "Final SRS section 4.2, C03 contracts, revised work distribution page 8"
---

# B01 run_idempotent core (AI-assisted)

**Goal.** Replace the C03 `FakeRunIdempotent` stub with a real wrapper that
validates the `Idempotency-Key` header, fingerprints the request and replays or
rejects a reused key, on the caller's `BEGIN IMMEDIATE` transaction.

**What was built.** `backend/app/services/idempotency.py` provides
`parse_idempotency_key` (400 `IDEMPOTENCY_KEY_MISSING` for missing or blank, 422
`VALIDATION_ERROR` for a bad charset or length), `request_fingerprint` (SHA-256
of scope, target and canonical JSON) and `SqliteRunIdempotent`, which satisfies
the C03 `RunIdempotent` protocol. It never commits. The design is recorded in
`docs/adr/0002-idempotency-fingerprint-and-replay.md`, based on
[[resources/idempotency-keys-and-request-fingerprints]].

**Evidence.** `backend/tests/test_idempotency.py` has 35 tests. They run on a
real migrated, file-backed SQLite database through the shared `SqliteDatabase`
provider, and use C04's `LedgerPoster` to make real postings. They cover header
validation, fingerprint stability and sensitivity, replay without a new
transaction, conflict with no state change, scoping by user and operation,
rollback after a failure leaving no key (and a retry with the same key
succeeding), and refusal to store failed or non-JSON results.

**What worked.** The C03 contract and the H03 provider were enough to build and
test this without any HTTP route, and without changing another member's file.

**What to watch.** Callers must pass JSON-ready request and response bodies, so
the first response and every replay are the same JSON. The concurrency proof
with two connections (FR-2.10) is the next stage, B01b. The deposit endpoint
(B02) needs Member A's system wallets (H05) for an end-to-end run.

Related: [[projects/2026-11-19-c03-contracts]], [[projects/2026-11-20-c04-posting]], [[log]].
