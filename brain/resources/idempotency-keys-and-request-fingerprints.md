---
title: Idempotency Keys and Request Fingerprints
type: research
date: "2026-11-25"
author: "P. Pranav Sai (B), AI-assisted"
category: resources
requirements: [FR-2.4, FR-2.5, FR-2.6, FR-2.7, FR-2.8, FR-2.9, FR-2.10]
tags: [b01, idempotency, sqlite]
source: "Final SRS section 4.2; IETF httpapi Idempotency-Key header draft; SQLite transaction documentation; Python 3.11 json documentation"
---

# Idempotency Keys and Request Fingerprints (AI-assisted)

- An idempotency key is a client-chosen value sent in a header, so a retry of the same operation is recognized instead of being executed again. The IETF httpapi working group's Idempotency-Key header draft describes the same pattern: the server remembers the key with the result, and rejects reuse of a key for a different request. [IETF draft](https://datatracker.ietf.org/doc/draft-ietf-httpapi-idempotency-key-header/)
- A key alone cannot tell a true retry from a mistake. The server needs a fingerprint of the request. Our SRS fixes it as SHA-256 over the operation, the URL target and the body as JSON with sorted keys and no whitespace (FR-2.6).
- Python's `json.dumps(value, sort_keys=True, separators=(",", ":"))` gives that canonical form. `allow_nan=False` rejects `NaN` and `Infinity`, which are not valid JSON. [Python 3.11 json](https://docs.python.org/3.11/library/json.html)
- Storing the key in the same database transaction as the money movement keeps them consistent: both commit or neither does. Storing it separately can leave a key with no transaction, or a transaction with no key.
- In SQLite, `BEGIN IMMEDIATE` takes the write lock at the start of the transaction, so two requests with the same key run one after the other. The second sees the first's committed key and replays it. [SQLite transaction control](https://www.sqlite.org/lang_transaction.html)

Related: [[resources/sqlite-migration-transactions]], [[projects/2026-11-25-b01-idempotency]].
Decision: `docs/adr/0002-idempotency-fingerprint-and-replay.md`.
