---
title: "Client retries and uncertain outcomes"
type: research
date: "2026-11-28"
author: "P. Pranav Sai (B), AI-assisted"
category: resources
requirements: [FR-2.4, FR-2.7, FR-2.9, NFR-SEC-7]
tags: [b10, idempotency, retries, client, ui]
source: "RFC 9110 section 9.2.2 (Idempotent Methods); IETF httpapi draft 'The Idempotency-Key HTTP Header Field'; Amazon Builders' Library, 'Making retries safe with idempotent APIs' and 'Timeouts, retries, and backoff with jitter'"
---

# Client retries and uncertain outcomes (AI-assisted)

**Question.** A client sends a transfer and the connection drops before the
answer arrives. Did the money move? What should the client, the command-line
tool and the web page do next?

**What the sources say.**
- *POST is not idempotent.* RFC 9110 defines idempotent methods as those where
  repeating the request has the same intended effect as sending it once. PUT,
  DELETE and the safe methods qualify; POST does not. A plain retry of
  `POST /transfers` could therefore move money twice.
- *Idempotency keys.* The IETF httpapi draft adds an `Idempotency-Key` request
  header so a POST can be made safe to repeat. The client generates a unique
  key per operation and sends the same key on every retry of that operation.
  The server remembers the key with its result, and rejects the same key with
  a different request.
- *Ambiguous failures.* The Amazon Builders' Library articles make the same
  point from the service side. After a timeout, the caller cannot tell "failed
  before" from "succeeded but the reply was lost". Retrying is only safe when
  the API is idempotent through a caller-supplied token. Unbounded or
  synchronized automatic retries can overload a struggling service.

**What it means for us.**
- *Three outcomes, not two.* Each response falls into one of three classes:
  - *done:* a 2xx response
  - *rejected:* a 4xx response, where the server stored nothing (FR-2.9) and
    the fix is to change the request
  - *uncertain:* a timeout, a lost connection, a 5xx or an unreadable reply,
    where only a resend with the *same key and body* is safe
- *New key per operation.* A key is created once per user intent, not per
  attempt. Reusing it with a changed body is a client bug, and the server
  answers `422 IDEMPOTENCY_CONFLICT` (FR-2.8).
- *No automatic retries.* For a course-scale API with one SQLite writer, the
  person decides when to resend. This avoids retry storms against a busy
  database (`503 DATABASE_BUSY`).
- *The client.* [[projects/2026-11-27-b09-api-client]] returns the key with
  every result so a caller can resend with it, and never retries on its own.
- *The web page.* [[projects/2026-11-27-b05-deposit-transfer-ui]] goes further:
  after an uncertain outcome the main button stays locked until the user
  resends with the same key or discards the operation. A nervous second click
  therefore cannot start a second transfer. A successful resend shows a
  **Replayed** badge.
- *Secrets.* Keys are not secrets and may be shown. Bearer tokens never appear
  in the client's output, errors or URLs (NFR-SEC-7).

**PRs informed.**
- KiritoReborn/Financial-Ledger-Digital-Wallet-API#51 (B09)
- KiritoReborn/Financial-Ledger-Digital-Wallet-API#55 (B05)

Related: [[resources/idempotency-keys-and-request-fingerprints]], [[projects/2026-11-25-b03-transfers]].
