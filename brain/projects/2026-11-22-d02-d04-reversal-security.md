---
title: "D02 reversal service and D04 admin security suite"
author: "Gangavarapu Jaswant (D), AI-assisted"
date: "2026-11-22"
category: "projects"
tags: ["reversal", "admin", "security", "idempotency", "tamper-detection"]
requirements:
  - "FR-4.2"
  - "FR-4.3"
  - "FR-4.4"
  - "FR-4.5"
  - "NFR-SEC-1"
  - "NFR-SEC-2"
  - "NFR-SEC-7"
  - "BR-5"
  - "BR-6"
source: "Final SRS FR-4.2 to FR-4.5, NFR-SEC-7; work plan D02 and D04"
---

# D02 reversal service and D04 admin security suite

**What:** Added `backend/app/services/reversal.py` and `POST /transactions/{id}/reverse` in `backend/app/api/admin.py` (D02), plus `tests/test_admin_security.py` covering negative security, concurrency race/replay, error sanitization, and SQLite tamper-detection checks (D04).

**Contract alignment (C03/C04/B01):** `reverse_transaction` runs inside the caller-owned `BEGIN IMMEDIATE` transaction without starting, committing, or rolling back internally, mirrors original `DEBIT`/`CREDIT` entries through `PostTransaction`, and enforces `422 INSUFFICIENT_FUNDS`, `422 NOT_REVERSIBLE`, `404 NOT_FOUND`, and `409 ALREADY_REVERSED`. `POST /transactions/{id}/reverse` validates admin credentials first (`[[constant-time-secret-comparison]]`), validates `Idempotency-Key` (`400`/`422`) and UUID v4 path `{id}`, and wraps execution in `RunIdempotent` (`scope="REVERSAL"`).

**Fallback & handoff:** When C03/C04/B01 are not injected or merged, `reversal.py` provides C03-compatible contract doubles/defaults (`sqlite_write_transaction`, `default_post_transaction`, `default_run_idempotent`). Once B01 and C04 land on `main`, `create_app(...)` can inject `LedgerPoster` and `run_idempotent` directly.

**Evidence:** `backend/tests/test_reversal.py` (C03 contract fakes + WAL SQLite integration) and `tests/test_admin_security.py` (auth, concurrent double-reversal race & replay, `NFR-SEC-7` leak checks, and `[[2026-11-20-d03-reconciliation]]` tamper detection). See also `[[sqlite-immutability-triggers]]` and `[[sqlite-read-only-transaction-snapshots]]`.
