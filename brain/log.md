---
title: "Second brain run log"
author: "P. Jaya Raghunandhan Reddy (C)"
date: "2026-11-19"
category: "projects"
tags: ["log", "progress"]
requirements: ["SB-1", "SB-5", "AI-3"]
source: "User-directed incremental C01 work"
---

# Second brain run log (AI-assisted)

| Date | Owner | Actual work | Evidence |
| --- | --- | --- | --- |
| 2026-11-19 | C | Verified synced main and all remote branches; started one health increment using existing project work. | [[2026-11-19-c01-health]] |
| 2026-11-19 | C | Removed obsolete setup branch locally and on GitHub, preserved a local archive tag, and verified remote deletion. Health publication remains blocked by network/integration permissions. | [[2026-11-19-c01-health]] |
| 2026-11-19 | A | Recorded the published Migration 001 schema and its supporting research in the vault. | [[projects/h02-database-migration]], [[resources/sqlite-schema-constraints]] |
| 2026-11-20 | A | Committed the H02 runner and tests, integrated current main, and verified 78 tests plus Ruff. A fresh SQLite file recorded migrations 1 and 2 once each across two CLI runs. | [[projects/h02-database-migration]] |
| 2026-11-20 | A | Completed the H01 repository setup, corrected the clean-clone commands, and documented review and ownership rules. | [Contributor guide](../AGENTS.md), [setup](../README.md) |
| 2026-11-20 | A | Moved migration setup into startup. Tested a second boot against the same file and checked that the user row survived. | [[projects/h03-sqlite-provider]] |
| 2026-11-23 | A | Integrated reconciliation with the startup factory. Verified a real C04 deposit and rollback, plus 113 passing tests. | [[projects/h03-sqlite-provider]] |
| 2026-11-23 | A | Updated the routine PR workflow to allow author review and merge after both required checks pass. | [Contributor guide](../AGENTS.md) |
| 2026-11-19 | C | Added configured frontend-origin policy and 28 CORS cases on raghu/api-cors; opened PR #10 over health PR #9. All 44 local tests and both GitHub CI workflows passed. Human review pending. | [[2026-11-19-c01-cors]] |
| 2026-11-19 | C | Added shared API error handling, generated request IDs, safe structured request logs and the C01 body limit. All 80 local tests passed; publication and CI recorded in the linked note. | [[2026-11-19-c01-request-safety]] |
| 2026-11-19 | C | Added C03 provisional provider/service protocols and deterministic fakes under issue #12. All 95 local tests passed; transaction ownership and replay/failure cases covered. | [[2026-11-19-c03-contracts]] |
| 2026-11-19 | C | Added the C02 OpenAPI proposal and static Prism fixtures under issue #14; 125 local tests passed, two full-validator cases await CI. | [[2026-11-19-c02-api-contract]] |
| 2026-11-24 | C | Recorded merged C01–C04 evidence, linked the C05 recovery PR, and scored Member C progress from the revised 36-point work plan. | [Traceability matrix](../docs/traceability.csv), [Member C progress](../docs/member-c-progress.md) |
| 2026-11-20 | C | Tested posting against the merged migrations. All 241 Python tests passed. A separate 50-writer run produced 33 transfers and 17 insufficient-funds rejections. | [[projects/2026-11-20-c04-posting]] |
| 2026-11-22 | C | Reconciled C01–C03 branch history, corrected validation and mock setup, and reviewed the new provider and reconciliation PRs. | [[projects/2026-11-22-github-review]] |
| 2026-11-24 | C | Synchronized PR #11 with the merged SQLite provider. Startup migrations, health, and reconciliation work alongside the existing CORS and request safeguards. The combined branch passed 235 tests and Ruff. | [[projects/h03-sqlite-provider]] |
| 2026-11-24 | C | Prepared C05 for review with rollback and process-recovery tests against the migrated SQLite database. All 291 tests and Ruff passed. | [[projects/2026-11-24-c05-recovery]] |
| 2026-11-25 | D | Hardened D01 immutability trigger tests against real Migration 001/002 on WAL file-backed SQLite, adding wallet balance mutability and DB-3 currency mismatch coverage. | [[sqlite-immutability-triggers]] |
| 2026-11-25 | B | Added the B01 run_idempotent core: Idempotency-Key validation, SHA-256 request fingerprint, replay and conflict on the caller's BEGIN IMMEDIATE transaction, recorded in ADR 0002. 35 new tests on real migrated SQLite; all 345 tests and Ruff passed. | [[projects/2026-11-25-b01-idempotency]], [[resources/idempotency-keys-and-request-fingerprints]] |
| 2026-11-25 | B | Added B01b concurrency and rollback tests: same-key requests from 2 and 10 threads and from 2 processes post once, different keys lose no update, and a failed holder leaves no key. 7 new tests, run five times; all 352 tests and Ruff passed. | [[projects/2026-11-25-b01b-idempotency-concurrency]] |
| 2026-11-25 | B | Added the B02 deposit endpoint POST /wallets/{id}/deposit with authentication, ownership, strict integer amounts and idempotent replay. 35 new HTTP tests on migrated SQLite. | [[projects/2026-11-25-b02-deposit]] |
| 2026-11-25 | B | Added the B03 transfer endpoint POST /transfers with sender ownership, same-currency and funds checks through C04 posting, strict request validation and idempotent replay. 56 new HTTP tests on migrated SQLite; all 448 tests and Ruff passed. | [[projects/2026-11-25-b03-transfers]] |
| 2026-11-26 | B | Added the B04 exactly-once suite over HTTP: 50 competing transfers commit 33 and reject 17 leaving 1,000, same-key races post once, replays survive restart, failures after posting roll back the key, and errors follow a fixed order. 30 new tests, run five times; found no defects. | [[projects/2026-11-26-b04-exactly-once-suite]] |
| 2026-11-28 | C | Rechecked C07 against rewritten main using a disposable live API. Of 50 competing requests, 33 posted and 17 reported insufficient funds. Final balances, ledger row counts and SQLite integrity passed. | [[projects/2026-11-26-c07-http-stress]] |
| 2026-11-26 | B | Added the B08 OpenAPI drift check for the deposit and transfer routes against docs/api/openapi.yaml. It found the deposit and transfer routes missing the Idempotency-Key header and deposit bearer auth, fixed as DEF-001. 23 new tests; Ruff passed. | [[projects/2026-11-26-b08-openapi-drift]] |
| 2026-11-27 | B | Added the B09 API client scripts/api_client.py and docs/deposit-transfer.md. The client reads secrets only from the environment, keeps them out of URLs, bodies, errors, repr and output, refuses plain HTTP off localhost, and gives every deposit and transfer a UUID key to retry with. 30 new tests and a live uvicorn run; Ruff passed. | [[projects/2026-11-27-b09-api-client]] |
| 2026-11-27 | B | Added the B06 simulate-transfer skill: two fresh users, deposits, a keyed transfer, a replay that moves nothing, two concurrent transfers, reconcile and final balances through scripts/api_client.py. 14 new tests; a live uvicorn evaluation run passed all eight steps with no secret in any output. | [[projects/2026-11-27-b06-simulate-transfer]] |
| 2026-11-27 | B | Added the B05 deposit and transfer screens: minor-unit conversion by currency exponent, a new Idempotency-Key per operation, Send again with same key, a Replayed badge, and a locked submit after an uncertain outcome. 36 new frontend tests; checked in the browser against the real API. | [[projects/2026-11-27-b05-deposit-transfer-ui]] |
| 2026-11-27 | B | Added the B07 brain-query skill: BM25 search over the vault that answers only with sentences from notes, each cited as a wikilink, plus cited ADR and SRS drafts. 14 new tests; a seven-question evaluation run is recorded in skills/brain-query/evaluation.md. | [[projects/2026-11-27-b07-brain-query]] |
| 2026-11-25 | D | Implemented D02 reversal service and idempotent POST /transactions/{id}/reverse wired to B01 run_idempotent, C04 LedgerPoster, H03 SqliteDatabase, and H04 ADMIN_ID. Added 16 unit, e2e, concurrency race/replay, and auth tests; verified full suite and Ruff. | [[projects/2026-11-25-d02-reversal]] |
| 2026-11-25 | D | Added D04 admin security and SQLite tamper-detection suite (20 tests), D06 local-check failure-path test coverage, and D08 CI skill/brain validator wired into ci.yml with negative tests. | [[projects/2026-11-25-d04-d08-security-ci]] |
| 2026-11-25 | D | Added D07 brain-refine skill and validation tests, D09 admin security guide and CHANGELOG.md, and D10 financial integrity review note with brain/index.md links. | [[projects/2026-11-25-d10-reconciliation-review]] |

This log records development and verification sessions.

### 2026-11-23 · FR-1.2 bearer tokens

Registration can issue a random token and store its SHA-256 digest in the column from [[projects/h02-database-migration]]. The lookup test uses two users and checks that presenting a stored digest fails. The admin route shares the header parser and keeps its separate key check.

The registration endpoint and admin bootstrap passed the HTTP and restart tests. Concurrent registrations produced a single user, and rotating the admin token preserved the admin ID. See [[projects/fr-1-user-registration]].

2026-11-24 · Integrated registration with the shared HTTP handlers on main. Ruff and all 305 tests passed with the combined API and posting suites.

2026-11-24 · FR-1.3. Added wallet creation locally using the bearer lookup from [[projects/fr-1-user-registration]] and the write transaction from [[projects/h03-sqlite-provider]]. Two concurrent requests for the same owner and currency produced one 201 and one 422. All 308 tests passed.

2026-11-25 · Completed [[projects/fr-1-wallets]]. Verified owner-only reads, foreign and unknown IDs, system-wallet recovery across restarts, and deposit compatibility.

2026-11-26 · Ran brain-ingest on SRS §2.1 and captured the caller-owned SQLite transaction boundary in [[inbox/transaction-ownership]]. The inbox entry is ready for filing with brain-refine.

2026-11-27 · H07. Added the React routes and shared Prism client. In Chrome, signing in opened the fixture wallet list, reloading kept the tab session, the wallet link opened history, and signing out cleared the token. The client tests and production build passed. [Frontend setup](../frontend/README.md)

2026-11-27 · H08 (EI-UI-1/2/7/8). Registration shows the token once. In Chrome against a temporary SQLite database, an invalid token was rejected, the issued token opened an empty dashboard, and a new INR wallet still showed 0.00 after reload. Its deposit link carried the wallet ID. Three frontend tests and the production build passed, including an int64 balance formatting check.
