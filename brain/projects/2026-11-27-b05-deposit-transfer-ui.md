---
title: "B05 deposit and transfer screens"
date: "2026-11-27"
author: "P. Pranav Sai (B), AI-assisted"
category: projects
type: ai-session
tags: [member-b, b05, frontend, idempotency, ui]
requirements: [FR-1.4, FR-1.6, FR-1.7, FR-2.4, FR-2.7, FR-2.9, TQ-6]
source: "Revised work distribution page 8, PRANAV_PLAN Stage 9, docs/api/openapi.yaml"
---

# B05 deposit and transfer screens (AI-assisted)

**Goal.** Let a signed-in user deposit and transfer simulated funds from the
web UI without ever moving money twice by accident.

**What was built.**
- `frontend/src/MoneyPages.jsx`, with `DepositPage` and `TransferPage` on the
  shared shell's `/deposit` and `/transfers` routes, plus `money-pages.css`.
- `frontend/src/money.js` converts typed amounts to minor units with the shared
  currency exponents (INR 2, USD 2, JPY 0). It uses string and `BigInt`
  arithmetic, never floats, and rejects extra decimals, zero, signs, exponents
  and amounts over 10^12 minor units.
- `frontend/src/operation.js` gives each new operation a UUID v4 key and a
  frozen body. It sends one POST with a 10-second timeout and sorts the outcome
  into one of three kinds:
  - *done*, reading `Idempotent-Replayed`
  - *uncertain*: a timeout, a lost connection, a 5xx or an unreadable reply
  - *rejected*: any other API error
- The shared shell gained one import, and its two placeholder routes now render
  these pages.

**Decisions.**
- *Keys.* Every Deposit or Transfer click is a new operation with a new key.
  "Send again with same key" resends the exact stored operation, so a replay
  shows the **Replayed** badge and the same transaction.
- *Uncertain outcomes.* After one, the main button stays locked. The user can
  only resend with the same key or explicitly discard the operation, so a
  second click cannot create a second transfer.
- *Rejections.* These stored nothing, so no resend is offered. The user fixes
  the form and submits a new operation.
- *Retries.* The page never retries on its own, and buttons are disabled while
  a request is in flight.

**Evidence.**
- `frontend/tests/money.test.js` and `frontend/tests/operation.test.js` hold 36
  new tests. They cover:
  - conversions, including `0.29`, which floats get wrong
  - every rejected amount, and formatting round trips
  - one POST with the key header, and replay with the same key
  - a timeout that is uncertain and sends only once, and a lost connection
  - which error codes count as uncertain or as rejected
- `npm --prefix frontend test` passed 38 tests (2 existing), and
  `npm --prefix frontend run build` passed.
- *Browser check, 2026-11-27.* Run against uvicorn on a disposable database
  through the Vite proxy, with seeded test users:
  - `12.345` INR was refused on the page.
  - A 25.50 INR deposit posted, and its resend showed **Replayed** with the
    same transaction while the balance stayed at 1025.50.
  - An invalid wallet ID was refused on the page.
  - A 100.00 INR transfer posted.
  - 5000 INR gave `INSUFFICIENT_FUNDS` with no resend button.
  - With the API stopped, `NETWORK_ERROR` locked the Transfer button and offered
    only the resend and discard options.

  The console showed only the expected 422 and 500 responses.

Related: [[projects/2026-11-27-b09-api-client]], [[projects/2026-11-25-b03-transfers]],
[[projects/2026-11-25-b02-deposit]], [[log]].
