---
title: "B06 simulate-transfer skill"
date: "2026-11-27"
author: "P. Pranav Sai (B), AI-assisted"
category: projects
type: ai-session
tags: [member-b, b06, skill, idempotency, concurrency]
requirements: [SK-6, FR-1.6, FR-1.7, FR-2.4, FR-2.7, FR-2.10, FR-4.2, TQ-7, NFR-SEC-7]
source: "Project statement skill steps, final SRS, revised work distribution page 8, PRANAV_PLAN Stage 8"
---

# B06 simulate-transfer skill (AI-assisted)

**Goal.** One repeatable, secret-safe run that shows the money paths working on
a live API: deposits, a keyed transfer, a replay that moves nothing, two
concurrent transfers, and a clean reconcile (course Stage 3 product skill).

**What was built.**
- `skills/simulate-transfer/SKILL.md`, in Agent Skills format. Its frontmatter
  name matches the folder, and it has a description, secret rules, an eight-step
  procedure with pass conditions, the output format, and brain citations.
- `skills/simulate-transfer/scripts/simulate_transfer.py`, which calls the API
  only through [[projects/2026-11-27-b09-api-client]]. Each run:
  - registers two fresh users with INR wallets
  - deposits 10,000 and 5,000
  - transfers 1,500 with a key, then replays it with the same key
  - runs 2,000 and 700 concurrently in opposite directions
  - reconciles, and checks the final balances are 7,200 and 7,800

  It prints a pass/fail table (or `--json`) and exits 0 only when all eight
  steps pass.

**Decisions.**
- *Stop early.* The run stops at the first failing step, since later steps
  depend on earlier ones. The failing row shows only the status and error code,
  or the client's message.
- *Fresh users.* Each run registers fresh users with a random run ID, so it can
  be repeated on the same database. The users' tokens stay in memory.
- *Real checks.* The replay step checks the sender was debited once, not only
  the `Idempotent-Replayed` header.

**Evidence.**
- `tests/test_simulate_transfer_skill.py` (6 tests, no backend needed) checks:
  - the frontmatter, the steps and the secret rules
  - that the brain citations exist
  - that the amounts in SKILL.md match the script's constants
- `backend/tests/test_simulate_transfer.py` (8 tests) runs the script against
  the real app. It covers:
  - a full pass, and two runs on one database
  - table and JSON output with no secrets
  - missing or wrong admin credentials failing at step 7
  - a replay that posts again failing at step 5
  - an unreachable API failing at step 1

**Skill evaluation run (TQ-7), 2026-11-27.** The script ran exactly as SKILL.md
describes, against uvicorn on a fresh temporary database (Python 3.11.9,
Windows).
- Table run and `--json` run: all eight steps PASS, exit code 0 both times.
- Final balances: first user 7,200 (expected 7,200), second user 7,800
  (expected 7,800). Reconcile reported `ok`.
- The server log recorded 34 requests. Neither the admin token, the admin key
  nor any `Bearer` value appeared in the output or the server log.

Related: [[projects/2026-11-25-b03-transfers]], [[projects/2026-11-26-b04-exactly-once-suite]], [[log]].
