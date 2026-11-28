---
title: "FR-2 idempotency walkthrough for the Stage 4 review"
date: "2026-11-28"
author: "P. Pranav Sai (B), AI-assisted"
category: projects
type: demo
tags: [member-b, b10, demo, idempotency, traceability]
requirements: [FR-2.4, FR-2.5, FR-2.6, FR-2.7, FR-2.8, FR-2.9, FR-2.10]
source: "docs/adr/0002-idempotency-fingerprint-and-replay.md, backend/app/services/idempotency.py, backend/tests at main 9e7b330"
---

# FR-2 idempotency walkthrough for the Stage 4 review (AI-assisted)

A requirement-to-test trace for the live review, about ten minutes long. Line
numbers are as of main at `9e7b330`. If they move, the function and test names
stay the same.

## 1. Why: the research

Open [[resources/idempotency-keys-and-request-fingerprints]]. After a timeout,
a client cannot tell whether its POST committed. A retry must therefore be
recognised by a client key, and a reused key must be checked against a
fingerprint of the request.

For the race between two same-key requests, open
[[resources/sqlite-begin-immediate-and-same-key-races]]: the write lock has to
be taken *before* the key lookup.

## 2. Decision: ADR 0002

Open `docs/adr/0002-idempotency-fingerprint-and-replay.md` and point to its
four decisions:
- the key is scoped by user, operation and key
- the fingerprint is SHA-256 over the operation, the URL target and canonical
  JSON (FR-2.6)
- the key row is stored in the same `BEGIN IMMEDIATE` transaction as the
  posting (FR-2.9)
- concurrent duplicates wait on the write lock and then replay (FR-2.10)

## 3. Code

| Requirement | Where | What to point at |
| --- | --- | --- |
| FR-2.4 key required and valid | `backend/app/services/idempotency.py:58` `parse_idempotency_key` | Missing or blank gives 400 `IDEMPOTENCY_KEY_MISSING`; a bad format gives 422, and the key is never echoed |
| FR-2.6 fingerprint | `idempotency.py:76` `canonical_json`, `:81` `request_fingerprint` | Sorted keys, no whitespace, newline-joined parts, SHA-256 |
| FR-2.5 and FR-2.7 replay | `idempotency.py:117-130` | Look up `(user_id, scope, key)`, then return the stored status and body with `replayed=True` |
| FR-2.8 conflict | `idempotency.py:124-129` | A different fingerprint gives 422 `IDEMPOTENCY_CONFLICT` |
| FR-2.9 store only success, same transaction | `idempotency.py:132-155` | Run the operation, refuse non-2xx results, insert the key on the caller's connection |
| FR-2.10 serialization | `backend/app/database.py:41` and `db/migrations/001_initial_schema.sql:77` | `BEGIN IMMEDIATE` for writes; `PRIMARY KEY (user_id, scope, key)` as the second guard |
| Used by the endpoints | `backend/app/api/deposit.py:153`, `backend/app/api/transfers.py:87` | Both routes call the one shared `run_idempotent` |

## 4. Tests

| Requirement | Test |
| --- | --- |
| FR-2.4 | `backend/tests/test_idempotency.py:102` `test_missing_or_blank_key_is_400`, `:111` `test_invalid_key_is_422_and_not_echoed` |
| FR-2.6 | `test_idempotency.py:126` `test_fingerprint_is_sha256_of_scope_target_and_canonical_body`, `:134` `test_fingerprint_ignores_key_order` |
| FR-2.7 | `test_idempotency.py:200` `test_same_request_replays_stored_response_without_new_transaction` |
| FR-2.8 | `test_idempotency.py:217` `test_reused_key_with_different_request_conflicts_and_changes_nothing` |
| FR-2.9 | `test_idempotency.py:247` `test_failed_operation_stores_no_key_and_same_key_can_retry` |
| FR-2.10 | `backend/tests/test_idempotency_concurrency.py:123` (two threads), `:231` (two processes) |
| End to end | `backend/tests/test_exactly_once_http.py:125` (50 competing transfers), `:175` (same-key race over HTTP), `:270` (replay survives a restart), `:343` (failure after posting rolls back the key) |

Run them live from the repository root:

```bash
python -m pytest -q backend/tests/test_idempotency.py
python -m pytest -q backend/tests/test_idempotency_concurrency.py -k "two_concurrent or two_processes"
python -m pytest -q backend/tests/test_exactly_once_http.py -k "fifty or survives or failure_after"
```

## 5. Show it working

Do these on a disposable database.
1. *Skill.* Run the simulate-transfer skill. Step 5 replays a transfer with
   the same key, and the sender is debited once
   ([[projects/2026-11-27-b06-simulate-transfer]]).
2. *Web UI.* Make a deposit, then press **Send again with same key**. The
   **Replayed** badge appears with the same transaction ID, and the balance
   does not change ([[projects/2026-11-27-b05-deposit-transfer-ui]]).
3. *Vault.* Ask the vault a question and show the cited answer:
   `python skills/brain-query/scripts/brain_query.py "How are idempotency keys fingerprinted?"`
   ([[projects/2026-11-27-b07-brain-query]]).

## 6. Traceability

`docs/traceability.csv` lists FR-2.4 to FR-2.10 against B01, B01b, B02, B03,
B04 and B09, each with its issue, PR, test and brain note.

Related: [[projects/2026-11-28-b10-member-b-review]], [[log]].
