---
title: "C07 live transfer stress check"
author: "Member C"
date: "2026-11-26"
category: projects
tags: [transfers, concurrency, sqlite, performance]
requirements: [FR-3.3, NFR-PERF-1]
---

# C07 live transfer stress check (AI-assisted)

The runner registers two users and creates a wallet for each through the
local API. It deposits 100,000 minor units and releases 50 HTTP transfer
requests of 3,000 minor units together, each with its own idempotency key.
It checks the exact response counts and reads both ending balances from
the API.

Run against a disposable local ledger.

```sh
python scripts/check_transfer_stress.py --port 8000
```

The reference workload passed three runs on Windows with Python 3.11.14,
SQLite 3.50.4, and Uvicorn running on loopback. Each run returned 33 HTTP 201
responses and 17 HTTP 422 `INSUFFICIENT_FUNDS` responses. There were no 500 or
503 responses. The sender kept 1,000 minor units and the receiver got 99,000.
Direct read-only checks found 33 posted transfers, 68 entries including the
opening deposit, 33 transfer replay keys, and a passing integrity check.

Batch times were 0.89–1.74 seconds, with p95 transfer latency of 809–1,457 ms.
These timings describe the local runs.

Rechecked on November 28 on rewritten main `1ec69e1` with Python 3.11.14 and
SQLite 3.50.4. The same 33/17 split and 1,000/99,000 balances held. The isolated
SQLite file contained 33 transfer rows and 68 entries including the deposit.
`PRAGMA integrity_check` returned `ok`.

[HTTP runner](../../scripts/check_transfer_stress.py) ·
[Runner tests](../../tests/test_transfer_stress.py) ·
[B03 transfer PR](https://github.com/KiritoReborn/Financial-Ledger-Digital-Wallet-API/pull/39) ·
[B04 exactly-once PR](https://github.com/KiritoReborn/Financial-Ledger-Digital-Wallet-API/pull/44).
