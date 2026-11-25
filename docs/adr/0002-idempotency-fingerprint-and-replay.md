---
status: proposed
date: 2026-11-25
---

# Idempotency keys are fingerprinted and stored in the posting transaction

A client that times out cannot tell whether its deposit or transfer committed,
so it must be able to send the same request again without being charged twice
(FR-2.4 to FR-2.10). The SRS requires one implementation, `run_idempotent`,
shared by deposits, transfers and reversals.

**Fingerprint.** A request is identified by the caller's user ID, the operation
scope and the client key. That triple is the primary key of `idempotency_keys`.
To spot a key reused for a different request, we store a SHA-256 fingerprint of
the operation name, the target ID from the URL (empty for transfers) and the
request body as JSON with sorted keys and no whitespace (FR-2.6). The three
parts are joined with newlines, which neither a scope nor a UUID can contain,
so two different requests cannot produce the same hashed text. Sorting the
keys means that field order in the client's JSON does not matter. A changed
amount, target or field gives a different fingerprint and `422
IDEMPOTENCY_CONFLICT` (FR-2.8).

**Same transaction.** The API opens one `BEGIN IMMEDIATE` transaction
([ADR 0001](0001-posting-transaction-ownership.md)) and passes its connection
to `run_idempotent`. The wrapper looks up the key, then either replays the
stored status and body with `Idempotent-Replayed: true` (FR-2.7), or runs the
operation and inserts the key row before the caller commits. The key and the
ledger rows therefore commit or roll back together. A failed operation leaves
no key, and the client can retry with the same key (FR-2.9).

**Concurrent duplicates.** `BEGIN IMMEDIATE` takes SQLite's write lock before
the lookup. A second request with the same key waits up to the 5000 ms busy
timeout, then reads the committed row and gets a replay instead of creating a
second transaction (FR-2.10). The table's primary key is a second guard: if a
caller ever forgot `BEGIN IMMEDIATE`, the duplicate insert fails and rolls
back. There is no application retry loop (FR-3.4).

**Alternatives rejected.** Hashing the raw request bytes would treat the same
JSON with different spacing or field order as a conflict. Recording the key in
its own transaction before posting would leave a stored key without a ledger
transaction after a crash, and the client could never retry. Only successful
(2xx) results are stored, because failures roll back.

Research: [[resources/idempotency-keys-and-request-fingerprints]].
Implementation: `backend/app/services/idempotency.py`.
Tests: `backend/tests/test_idempotency.py`.
