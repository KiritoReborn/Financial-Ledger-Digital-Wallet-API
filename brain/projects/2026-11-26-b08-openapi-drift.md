---
title: "B08 OpenAPI drift check"
date: "2026-11-26"
author: "P. Pranav Sai (B), AI-assisted"
category: projects
type: ai-session
tags: [member-b, b08, openapi, contract, ci]
requirements: [EI-SW-2, TQ-8]
source: "docs/api/openapi.yaml, revised work distribution page 8, PRANAV_PLAN Stage 6"
---

# B08 OpenAPI drift check (AI-assisted)

**Goal.** Fail CI when the running FastAPI app stops matching the documented
contract in `docs/api/openapi.yaml` (EI-SW-2).

**What was built.** `scripts/check_openapi_drift.py` compares every operation in
`create_app().openapi()` with the contract. It reports:
- an undocumented operation
- a different operationId or success status
- a status the app declares but the contract does not
- different security schemes
- missing, extra or differently required parameters
- request-body fields, required fields, unknown-field policy, types, enums and limits

It resolves `$ref`s, so a change to a shared schema such as `Amount` or
`Currency` is caught on every route that uses it.

`backend/tests/test_openapi_drift.py` runs it in the existing `raghu-api.yml`
job, so no workflow edit was needed.

**Decisions.**
- *Approved differences* are listed in the script's docstring and ignored:
  - wording, examples and tags
  - FastAPI's generated 422 schema
  - statuses that only middleware or shared handlers return
  - response headers and bodies (checked at runtime instead)
  - `anyOf: [X, null]` for optional fields and bodies
  - Pydantic's `uuid4` format versus the contract's v4 pattern
- *Documented but unbuilt* operations (`GET /transfers/{id}`,
  `GET /wallets/{id}/transactions`) are listed as to-do, not failed.
- *`KNOWN_DRIFT`* holds divergence in other members' routes, each with its owner.
  The check fails on new drift and on a known entry that is no longer present,
  so the list can only shrink. Other members' files were not edited.
- *Header documentation.* `Idempotency-Key` is documented through
  `openapi_extra` rather than a FastAPI `Header` parameter. Requests without it
  still get 400 `IDEMPOTENCY_KEY_MISSING`, not FastAPI's generic 422.

**Evidence.** 24 tests:
- the CI gate and the command line
- one mutation of the contract per kind of drift, each checked to be caught
- wording, extra contract-only statuses and unbuilt operations checked to be ignored
- a fixed entry left in `KNOWN_DRIFT` fails, and new drift fails the command
- real deposit and transfer responses validate against the contract's
  `Transaction` and `Transfer` schemas
- a missing key still gives 400

**Found.**
- DEF-002 (mine, fixed here): the deposit and transfer routes did not publish
  the `Idempotency-Key` header, and deposit did not publish bearer auth.
- DEF-003 to DEF-005 in `docs/defect-log.md`: the operationIds, security and
  header on the health, reconcile and reverse routes. Reported to Members C and D.

Related: [[projects/2026-11-25-b02-deposit]], [[projects/2026-11-25-b03-transfers]],
[[projects/2026-11-19-c02-api-contract]], [[log]].
