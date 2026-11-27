---
title: "Active project records"
author: "P. Jaya Raghunandhan Reddy (C)"
date: "2026-11-19"
category: "projects"
tags: ["index", "progress"]
requirements: ["SB-0", "SB-1", "SB-5", "AI-3"]
source: "Final SRS section 6.3"
---

# Active project records (AI-assisted)

- [[2026-11-19-c01-health]] - C01 health behavior, tests and session evidence.
- [[2026-11-19-c01-cors]] - configured frontend origin, preflight and browser-access checks.
- [[2026-11-19-c01-request-safety]] - bounded requests, request IDs and safe HTTP errors.
- [[2026-11-19-c02-api-contract]] - OpenAPI and Prism verification.
- [[2026-11-19-c03-contracts]] - service contracts and transaction fakes.
- [[2026-11-20-c04-posting]] - posting, reversals and ledger integrity tests.
- [[2026-11-22-github-review]] - pull requests, workflow findings and team decisions.
- [[2026-11-24-c05-recovery]] - rollback, replay-row atomicity and abrupt process exit checks.
- [[2026-11-25-b01-idempotency]] - B01 idempotency key validation, request fingerprint, replay and conflict.
- [[2026-11-25-b01b-idempotency-concurrency]] - B01b concurrent same-key requests, process-level race and rollback.
- [[2026-11-25-b02-deposit]] - B02 idempotent deposit endpoint, ownership checks and integer-only amounts.
- [[2026-11-25-b03-transfers]] - B03 idempotent transfer endpoint, sender ownership, currency and funds checks.
- [[2026-11-26-b04-exactly-once-suite]] - B04 exactly-once and negative suite over HTTP, 50 competing transfers.
- [[2026-11-26-b08-openapi-drift]] - B08 OpenAPI drift check between the FastAPI app and the contract.
- [[2026-11-27-b09-api-client]] - B09 secure API client and deposit/transfer guide.
- [[2026-11-27-b06-simulate-transfer]] - B06 simulate-transfer skill and its evaluation run.
- [[2026-11-27-b05-deposit-transfer-ui]] - B05 deposit and transfer screens with safe retries.

Each feature increment adds a progress note to the existing team brain. The
obsolete setup branch was removed; A still owns the full vault/ingest work.
