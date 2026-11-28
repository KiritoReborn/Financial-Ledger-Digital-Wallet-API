---
title: "SQLite BEGIN IMMEDIATE and same-key races"
type: research
date: "2026-11-28"
author: "P. Pranav Sai (B), AI-assisted"
category: resources
requirements: [FR-2.10, FR-3.1, FR-3.4, NFR-REL-1]
tags: [b10, sqlite, concurrency, idempotency]
source: "SQLite documentation: Transactions (lang_transaction.html), Write-Ahead Logging (wal.html), sqlite3_busy_timeout (c3ref/busy_timeout.html); Python 3.11 sqlite3.connect timeout parameter"
---

# SQLite BEGIN IMMEDIATE and same-key races (AI-assisted)

**Question.** Two requests with the same `Idempotency-Key` arrive together.
Both look up the key, both find nothing, and both post: the payment happens
twice. How does SQLite stop that, and which transaction mode do we need
(FR-2.10)?

**What the sources say.**
- *DEFERRED.* A plain `BEGIN` starts a deferred transaction. It takes no lock
  until the first statement. A `SELECT` makes it a read transaction, and a
  later write tries to upgrade it. If another connection has already written,
  or is writing, the upgrade is impossible and the write fails with
  `SQLITE_BUSY` (SQLite, *Transactions*). In WAL mode, a reader whose snapshot
  is out of date cannot be fixed by waiting, so retrying that statement does
  not help.
- *IMMEDIATE.* `BEGIN IMMEDIATE` starts the write transaction at once, before
  any read. If another write transaction is active, `BEGIN IMMEDIATE` itself
  waits under the busy handler, then fails with `SQLITE_BUSY` if the wait runs
  out (SQLite, *Transactions*).
- *WAL.* Readers do not block the writer and the writer does not block
  readers, but there is only ever one writer at a time (SQLite, *Write-Ahead
  Logging*).
- *Busy timeout.* With a busy timeout set, a blocked connection sleeps and
  retries until the time runs out instead of failing at once. Python's
  `sqlite3.connect(timeout=...)` sets it, with a 5-second default
  (`sqlite3_busy_timeout`; Python `sqlite3` docs).

**What it means for us.**
- The key lookup and the posting must sit in one transaction that already
  holds the write lock *before* the lookup. With `BEGIN IMMEDIATE`, the second
  same-key request waits at `BEGIN` until the first commits. It then reads the
  committed key row and replays (FR-2.7, FR-2.10). With a deferred
  transaction, both could read "no key", and the loser would get `SQLITE_BUSY`
  or, without a key constraint, a second posting.
- The shared provider opens write transactions with `BEGIN IMMEDIATE` and a
  5-second busy timeout (H03). [[projects/2026-11-25-b01-idempotency]] runs the
  lookup and the insert on that caller-owned connection.
- `PRIMARY KEY (user_id, scope, key)` on `idempotency_keys` is a second guard.
  If a caller ever forgot `BEGIN IMMEDIATE`, the duplicate insert would fail
  and roll back the second posting.
- A wait longer than the timeout surfaces as `503 DATABASE_BUSY` with nothing
  stored. The client then resends with the same key. There is no
  application-level retry loop (FR-3.4).

**Evidence.**
- [[projects/2026-11-25-b01b-idempotency-concurrency]] proves one posting for
  2 and 10 threads and for 2 separate processes sharing a key.
- [[projects/2026-11-26-b04-exactly-once-suite]] repeats this over HTTP. It
  also shows that 50 competing transfers never overdraw a wallet, and that a
  write lock held past the timeout gives `503` and stores nothing.

**PRs informed.**
- KiritoReborn/Financial-Ledger-Digital-Wallet-API#33 (B01b)
- KiritoReborn/Financial-Ledger-Digital-Wallet-API#44 (B04)

Related: [[resources/idempotency-keys-and-request-fingerprints]], [[projects/h03-sqlite-provider]].
