---
title: "Financial Ledger second brain"
author: "P. Jaya Raghunandhan Reddy (C)"
date: "2026-11-19"
category: "projects"
tags: ["index", "progress"]
requirements: ["SB-1", "SB-5", "AI-3"]
source: "Final SRS section 6.3; existing team brain"
---

# Financial Ledger second brain (AI-assisted)

Open `brain/` as the Obsidian vault. Use `inbox/` for material to review, `projects/` for active work, `areas/` for ongoing responsibilities, `resources/` for references, and `archive/` for completed records.

## Database and authentication

- [[projects/h02-database-migration|H02 · Schema and migrations]]
- [[projects/h03-sqlite-provider|EI-SW-3 · SQLite connections per request]]
- [[projects/fr-1-user-registration|FR-1.1 and FR-1.2 · Registration and bearer tokens]]
- [[projects/fr-1-wallets|Wallet creation, ownership and system wallets]]

## Immutability, reversal, and reconciliation

- [[2026-11-20-d03-reconciliation|D03 · Read-only ledger reconciliation]]
- [[projects/2026-11-25-d02-reversal|D02 · Idempotent transaction reversals]]
- [[projects/2026-11-25-d04-d08-security-ci|D04 & D08 · Admin security and CI validators]]
- [[projects/2026-11-25-d10-reconciliation-review|D10 · Financial integrity and reconciliation review]]

The [[projects/2026-11-22-github-review|GitHub review]] tracks the open pull
requests, workflow failures and decisions awaiting the team. See [[log]] for
verification history and [[projects/README|project notes]] for feature details.

Existing team reference notes:
- [[sqlite-immutability-triggers]]
- [[constant-time-secret-comparison]]
- [[sqlite-read-only-transaction-snapshots]]
- [[resources/sqlite-schema-constraints|SQLite schema constraints]]
- [[resources/sqlite-migration-transactions|SQLite migration transactions]]
- [[resources/idempotency-keys-and-request-fingerprints|Idempotency keys and request fingerprints]]
- [[resources/sqlite-begin-immediate-and-same-key-races|SQLite BEGIN IMMEDIATE and same-key races]]
- [[resources/client-retries-and-uncertain-outcomes|Client retries and uncertain outcomes]]
- [[resources/bm25-search-for-cited-vault-answers|BM25 search for cited vault answers]]

## Inbox

- [[inbox/transaction-ownership|Transaction ownership in the API]]
