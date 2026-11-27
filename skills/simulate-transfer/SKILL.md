---
name: simulate-transfer
description: Run one end-to-end simulation against a running Financial Ledger API - register two users with INR wallets, deposit opening balances, transfer with an Idempotency-Key, replay it, send two concurrent transfers, reconcile, and report final balances in a pass/fail table without displaying any token or admin secret.
---

# Simulate Transfer (`simulate-transfer`)

Exercise the money paths of a running **Financial Ledger & Digital Wallet API**
in one repeatable run, and prove that a replayed transfer never moves money
twice (`SK-6`, `FR-1.6`, `FR-1.7`, `FR-2.4`, `FR-2.7`, `FR-2.10`, `FR-4.2`).

## Secret-Safety Rules (`SK-6`, `NFR-SEC-7`)

- **Never display, echo, log or store secrets.** Do not print `ADMIN_TOKEN`,
  `ADMIN_KEY`, user bearer tokens, `.env` contents or `env` output, in the run
  or in the report.
- The script calls the API only through `scripts/api_client.py`. It reads
  credentials from environment variables, sends them only in request headers,
  and never includes them in output or errors.
- The two simulated users are registered fresh for each run. Their tokens stay
  in memory and are discarded when the script exits.
- Report only step results, HTTP status and error codes, wallet balances and
  the run ID.

## Prerequisites

- Run from the repository root with the backend installed (`pip install -e ".[dev]"`).
- The API is running, for example as in the `local-check` skill, on a
  **disposable** database. The run adds two users and their transactions.
- `API_BASE_URL` points at it (default `http://127.0.0.1:8000`). Plain HTTP is
  accepted only for localhost.
- `ADMIN_TOKEN` and `ADMIN_KEY` are set in the environment, with the same
  values the server started with, for the reconcile step.

## Procedure

Run the script once:

```bash
python skills/simulate-transfer/scripts/simulate_transfer.py
```

Add `--json` for a machine-readable report. The exit code is `0` only when all
eight steps pass. The script stops at the first failing step, because each step
depends on the ones before it.

| Step | What it does | Pass condition |
| --- | --- | --- |
| 1 | `GET /health` | `200` and `{"status": "ok"}` |
| 2 | Register two users and create an INR wallet each | Both succeed |
| 3 | Deposit 10,000 and 5,000 minor units, then read the balances | Balances are exactly 10,000 and 5,000 |
| 4 | Transfer 1,500 from the first user to the second with a new `Idempotency-Key` | `201`, `Idempotent-Replayed: false` |
| 5 | Send the same transfer again with the same key | Replayed, identical body, the sender debited only once |
| 6 | Two concurrent transfers: 2,000 one way and 700 the other, different keys | Both `201`, neither replayed |
| 7 | `GET /admin/reconcile` | `ok` is `true` |
| 8 | Read both final balances | First user 7,200 and second user 7,800 |

On a failure, the row names the step and shows only the sanitized status and
error code, such as `422 INSUFFICIENT_FUNDS` or `401 UNAUTHENTICATED`, or a
client message such as `Reconcile needs ADMIN_TOKEN and ADMIN_KEY.`

## Output Format

The script prints the report itself:

| Step | Check | Result | Notes |
| --- | --- | --- | --- |
| 1 | Health | PASS | HTTP 200 |
| 2 | Two users with INR wallets | PASS | run 1a2b3c4d |
| ... | ... | ... | ... |
| 8 | Final balances | PASS | match the transfers |

It is followed by the opening, expected and final balance of each user, and
`**Overall:** PASS` or `FAIL`.

## Second Brain References (`SB-0`–`SB-7`)

- [[2026-11-27-b09-api-client]] covers the secure client this skill calls and its secret rules.
- [[2026-11-25-b03-transfers]] covers transfer rules and error codes.
- [[2026-11-25-b02-deposit]] covers the deposit endpoint used for opening balances.
- [[2026-11-26-b04-exactly-once-suite]] covers the exactly-once and concurrency evidence this run demonstrates live.
