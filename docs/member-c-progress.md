# Member C implementation sequence

Ownership follows the revised work-distribution PDF. Requirement details come
from the final 14-page SRS; older details are identified explicitly. These are
work sessions and review units, not fabricated calendar-day progress.

| Package | Points | Deliverable | Verification and remaining work |
| --- | ---: | --- | --- |
| C01 | 3 | API framework, health, CORS, errors, IDs and body limit | Merged through #9 and #11. Startup uses the shared SQLite provider. |
| C02 | 4 | OpenAPI 3.x and Prism for all 11 operations | Merged through #11 with passing contract and mock checks. Issue #14 tracks team agreement on DTOs and the history cursor. |
| C03 | 4 | Posting/idempotency/transaction contracts, Clock, IdProvider and fakes | Merged through #11. Issue #12 tracks team agreement for formal M0. |
| C04 | 8 | Balanced posting for deposits, transfers and reversals | Merged in #19 with 288 passing Python tests and four passing GitHub checks. Issue #16 tracks downstream integration. [Verification record](../brain/projects/2026-11-20-c04-posting.md). |
| C05 | 3 | Failure injection, rollback and process recovery | The 291-test suite and four GitHub checks passed. Posting review is pending in [PR #27](https://github.com/harshith-raj-06/Financial-Ledger-Digital-Wallet-API/pull/27). |
| C06 | 3 | Transfer details and paginated wallet history | Both endpoints passed a local integration run with the shared SQLite provider and Member A's bearer resolver. Default routing awaits the shared auth branch. |
| C07 | 4 | Concurrent transfer and performance harness | The 50-writer acceptance case passed using the shared SQLite provider. The full HTTP run needs Member B's live endpoints. |
| C08 | 3 | Wallet history and concurrency demo pages | Both pages passed the Prism browser preview. Integration needs the shared React shell and live API. |
| C09 | 2 | Traceability matrix and posting ADR | Updated the requirements-to-evidence [matrix](traceability.csv). The [posting ADR](adr/0001-posting-transaction-ownership.md) records the proposed transaction ownership. |
| C10 | 2 | Five authored research notes through brain-ingest | Five AI-assisted drafts are prepared for human review and the H06 intake workflow. |

The 36-point budget comes from pages 5 and 7 of the November 18 revised
work-distribution plan. C01–C05 and C09 meet their own implementation acceptance
criteria, for 24 of 36 points (67%). C06–C08 and C10 still need integration or
authorship evidence. Formal M0 is a separate team decision.

Each feature gets its own branch and reviewed PR, focused tests, a comparison
with current main, a CI result and a linked brain note. Dependent PRs stay based
on their predecessor until it merges; then retarget/rebase and rerun CI. Only
merge after the required human review. No handover gate is marked complete
while its schema/provider or integration checks are missing.
