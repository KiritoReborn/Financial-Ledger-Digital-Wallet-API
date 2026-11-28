# Member C implementation sequence

Ownership follows the revised work-distribution PDF. Requirements come
from the final 14-page SRS. Status reviewed on November 28 against GitHub
`main` at `2cf1502`.

| Package | Points | Deliverable | Verification and remaining work |
| --- | ---: | --- | --- |
| C01 | 3 | API framework, health, CORS, errors, IDs and body limit | Merged through #9 and #11. Startup uses the shared SQLite provider. |
| C02 | 4 | OpenAPI 3.x and Prism for all 11 operations | Merged through #11 with passing contract and mock checks. Issue #14 tracks team agreement on DTOs and the history cursor. |
| C03 | 4 | Posting/idempotency/transaction contracts, Clock, IdProvider and fakes | Merged through #11. Issue #12 tracks team agreement for formal M0. |
| C04 | 8 | Balanced posting for deposits, transfers and reversals | Merged in #19. The deposit (#35), transfer (#39) and reversal (#40) routes now use the shared posting engine. [Verification record](../brain/projects/2026-11-20-c04-posting.md). |
| C05 | 3 | Failure injection, rollback and process recovery | Merged in #27. The [HTTP suite](https://github.com/KiritoReborn/Financial-Ledger-Digital-Wallet-API/pull/44) verifies atomic rollback and replay through the live idempotency wrapper. |
| C06 | 3 | Transfer details and paginated wallet history | Implemented and verified on `raghu/history-and-concurrency-demo`. Live auth, ownership, pagination, replay and reversal passed. |
| C07 | 4 | Concurrent transfer and performance harness | Implemented and verified on `raghu/transfer-stress-verification`. Live HTTP reproduced the 33/17 split, exact balances and ledger integrity. |
| C08 | 3 | Wallet history and concurrency demo pages | Integrated into the shared shell on `raghu/history-and-concurrency-demo`. The History API must be included in the same release. |
| C09 | 2 | Traceability matrix and posting ADR | Updated the requirements-to-evidence [matrix](traceability.csv). The [posting ADR](adr/0001-posting-transaction-ownership.md) records the proposed transaction ownership. |
| C10 | 2 | Five authored research notes through brain-ingest | Five AI-assisted drafts are prepared for human review and the H06 intake workflow. |

The revised work plan assigns 36 points. The six packages already merged on
`main` account for 24 points. C06–C08 account for 10 additional points on feature
branches awaiting team review. C10's remaining two points require Member C
authorship evidence. Team agreement on the public API and frozen signatures is
tracked in issues #14 and #12.

Each feature gets its own branch and reviewed PR, focused tests, a comparison
with current main, a CI result and a linked brain note. Dependent PRs stay based
on their predecessor until it merges; then retarget/rebase and rerun CI. Only
merge after the required human review. No handover gate is marked complete
while its schema/provider or integration checks are missing.
