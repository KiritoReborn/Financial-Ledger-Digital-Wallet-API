# Member C implementation sequence

Ownership follows the revised work-distribution PDF. Requirement details come
from the final 14-page SRS; older details are identified explicitly. These are
work sessions and review units, not fabricated calendar-day progress.

| Package | Next deliverable | Dependency / status |
| --- | --- | --- |
| C01 | API framework, health, CORS, errors, IDs and body limit | Health PR #9 reached main. PR #11 targets main and includes CORS from #10. |
| C02 | Full OpenAPI 3.x contract and Prism mock | #15 merged into the C03 branch. Its contract and fixtures now reach main through #11. Issue #14 tracks team agreement on DTOs and the history cursor. |
| C03 | Transaction/posting/idempotency contracts, Clock/IdProvider and fakes | #13 merged into #11's branch. Issue #12 tracks A/B/D agreement on the signatures before the M0 freeze. |
| C04 | Balanced posting for deposit, transfer and reversal | Consume A's actual migration 001 and transaction provider; never commit inside posting. |
| C05 | Failure-injection, rollback and crash harness | Depends on C04 and shared transaction integration. |
| C06 | Owner-checked transfer reads and paginated history | Depends on A's auth/provider, stable schema and posting data. |
| C07 | Concurrency and performance harness | Service cases after C04; full HTTP reference run after B's transfer endpoint. |
| C08 | History/concurrency frontend pages | Depends on A's React router/client shell; mock against C02 first. |
| C09 | Traceability and posting ADR | Update with every PR; posting ADR after C03/C04 decisions. |
| C10 | Five research notes through brain-ingest | Requires A/H06 workflow; development session notes do not count as these research notes. |

Each feature gets its own branch and reviewed PR, focused tests, a comparison
with current main, a CI result and a linked brain note. Dependent PRs stay based
on their predecessor until it merges; then retarget/rebase and rerun CI. Only
merge after the required human review. No handover gate is marked complete
while its schema/provider or integration checks are missing.
