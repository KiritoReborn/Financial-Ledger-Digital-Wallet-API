---
title: "Member B stage review: design, testing and CI"
date: "2026-11-28"
author: "P. Pranav Sai (B), AI-assisted"
category: projects
type: review
tags: [member-b, b10, review, sb-2]
requirements: [SB-2, TQ-7, TQ-8, FR-2.4, FR-2.10]
source: "Member B PRs #31, #33, #35, #39, #44, #46, #51, #53, #55, #56; brain notes and logs for B01 to B09"
---

# Member B stage review: design, testing and CI (AI-assisted)

SB-2 review of Member B's work across the course stages, covering what worked,
what did not and what to change. All of it was AI-assisted and reviewed by
P. Pranav Sai.

## Stage 2: Design

**Delivered.**
- ADR 0002 on idempotency fingerprints and replay, with its research note
  [[resources/idempotency-keys-and-request-fingerprints]].
- The `run_idempotent` core ([[projects/2026-11-25-b01-idempotency]]).
- The brain-query skill ([[projects/2026-11-27-b07-brain-query]]).

**What worked.**
- Writing the research note and the ADR before the code fixed the hard
  choices early: what the fingerprint covers, and the key living in the same
  transaction as the posting. The deposit and transfer endpoints later reused
  the core unchanged.
- The caller-owned transaction rule from ADR 0001 kept idempotency small. One
  `BEGIN IMMEDIATE` covers the lookup, the posting and the key insert. See
  [[resources/sqlite-begin-immediate-and-same-key-races]].

**What did not.**
- brain-query was planned for Stage 2 but shipped last, after the endpoints.
- Its first evaluation record lived inside the vault, and later runs matched
  it. See [[resources/bm25-search-for-cited-vault-answers]].

**Change.** Build the design-stage skills alongside the first ADR, and keep
evaluation records outside `brain/` from the start.

## Stage 3: Testing and CI

**Delivered.**
- Unit, concurrency and HTTP exactly-once suites:
  [[projects/2026-11-25-b01b-idempotency-concurrency]] and
  [[projects/2026-11-26-b04-exactly-once-suite]].
- The OpenAPI drift check ([[projects/2026-11-26-b08-openapi-drift]]).
- The simulate-transfer skill and its evaluation run
  ([[projects/2026-11-27-b06-simulate-transfer]]).
- The defect log (`docs/defect-log.md`).

**What worked.**
- Tests at the HTTP level, on fresh temporary SQLite files, caught real
  problems:
  - The drift check found the deposit and transfer routes publishing neither
    the `Idempotency-Key` header nor, for deposit, bearer auth (DEF-001).
  - The 50-writer race repeated the service-level result over HTTP: 33
    commits, 17 rejections and 1,000 left.
- Checking docs against code paid off. A test comparing the simulate-transfer
  SKILL.md amounts with the script's constants caught a wrong final balance in
  the table before review.
- Live runs (uvicorn, the command-line client, the browser) showed secrets
  stayed out of every output and log, which unit tests alone could not show.

**What did not.**
- A follow-up commit pushed seconds after opening the B02 PR made the secret
  scanner's first run fail on a missing revision. It was a false alarm, and
  the re-run passed.
- Several idempotency PRs merged before the two approvals AGENTS.md asks for
  were recorded.
- Keyword ranking in brain-query is only partly reliable for broad questions
  (three of seven evaluation questions were partial).

**Change.**
- Put traceability links in before the first push, which later stages did.
- Ask for both reviews when opening an idempotency or posting PR.
- Keep the read-then-re-search step in the brain-query procedure.

## Stage 4: Review, preparation

[[projects/2026-11-28-b10-fr-2-walkthrough]] traces FR-2 from requirement to
passing test for the live review. It also lists the live runs to show: the
simulate-transfer skill, the Replayed badge in the web UI, and a brain-query
answer.

Related: [[log]], [[projects/README]].
