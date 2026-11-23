# Working on the ledger

Use Python 3.11 and follow the root README for setup. Keep secrets in the local environment and use temporary SQLite files for tests.

Start a feature branch from current main for each work-package issue. Link the issue, SRS requirement IDs, relevant brain note and test commands in the PR.

## AI-assisted work

Record the work in the brain log and review the diff before requesting review.

Review every PR. For routine changes, the author may review the diff, record the review and test results in the PR, and merge once the required CI checks pass. A and C can request cross-review during early handover. Migration, posting, idempotency and reversal changes require two approvals. After formal M0, changes to the frozen transaction, posting or idempotency signatures require approval from the other three members.
