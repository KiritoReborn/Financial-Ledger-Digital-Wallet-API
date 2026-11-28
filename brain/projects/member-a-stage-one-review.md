---
title: "Stage 1 review for Member A"
author: "Harshith (Member A)"
date: "2026-11-28"
category: "projects"
tags: ["second-brain", "review"]
requirements: ["DB-1", "DB-6", "FR-1.2", "EI-UI-1", "EI-UI-8"]
source: "SRS.pdf, sections 3 and 6; Member A research and implementation PRs"
---

# Stage 1 review for Member A

| Research note | What the review checked |
| --- | --- |
| [[resources/sqlite-schema-constraints]] | The schema enforces integer storage and one clearing wallet per currency. [PR #18](https://github.com/KiritoReborn/Financial-Ledger-Digital-Wallet-API/pull/18) |
| [[resources/sqlite-migration-transactions]] | A failed script rolls back with its version record. The migration tests cover retry and concurrent startup. [PR #18](https://github.com/KiritoReborn/Financial-Ledger-Digital-Wallet-API/pull/18) |
| [[inbox/bearer-token-digests]] | Presenting the stored digest fails on wallet reads and writes. [PR #60](https://github.com/KiritoReborn/Financial-Ledger-Digital-Wallet-API/pull/60) |
| [[inbox/registration-token-lifetime]] | Registration shows the token once. The sign-in view validates the pasted token before retaining it for the tab. [PR #58](https://github.com/KiritoReborn/Financial-Ledger-Digital-Wallet-API/pull/58) |
| [[inbox/exact-wallet-balance-display]] | The int64 maximum survives JSON decoding and formats correctly in USD. [PR #58](https://github.com/KiritoReborn/Financial-Ledger-Digital-Wallet-API/pull/58) |

The [token-storage decision](../../docs/adr/0003-registration-token-storage.md) records where the credential lives. The [balance-display decision](../../docs/adr/0004-wallet-balance-display.md) records the browser precision limit and the fallback for browsers that cannot recover the original digits.

Reviewed against main at `35b9e45`. The schema, migration, registration, token and wallet suites passed 83 cases. The frontend suite passed 55. The browser registration and wallet walkthrough is recorded in [PR #58](https://github.com/KiritoReborn/Financial-Ledger-Digital-Wallet-API/pull/58). These checks cover Member A's contribution to the Stage 1 review; team sign-off is separate.

## Final package check

| Area | Evidence on the final branch |
| --- | --- |
| Repository setup and CI | Both CI workflows passed on main at `ece0abe`, including the package build and wheel smoke test. Corrected the CODEOWNERS path for the authentication module. |
| Database migrations and SQLite connections | Migration and provider tests cover reruns, rollback, per-connection settings and startup. See [[resources/sqlite-migration-transactions]] and [[inbox/transaction-ownership]]. |
| Registration, authentication and wallets | Registration, token lookup, admin bootstrap, wallet ownership and system-wallet restart behavior are covered in [[projects/fr-1-user-registration]] and [[projects/fr-1-wallets]]. |
| Source intake and frontend navigation | The intake skill and vault validator pass. The router, tab session and shared API client are documented in [[projects/wallet-ui-handover]]. |
| Wallet dashboard and request validation | The dashboard uses the shared currency precision and passes its wallet ID to the deposit page. [[projects/wallet-validation-handover]] records the negative cases and their expected HTTP responses. |
| Second brain and decision records | The five research notes above are indexed in the vault. Both decision records link to their supporting research. |

Final local verification passed on Python 3.11 with 649 tests, plus Ruff, vault validation, 55 frontend tests and the production frontend build.
