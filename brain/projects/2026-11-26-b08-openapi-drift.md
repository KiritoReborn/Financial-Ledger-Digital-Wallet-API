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

**Goal.** Fail CI when the deposit and transfer routes stop matching the
documented contract in `docs/api/openapi.yaml` (EI-SW-2).

**What was built.** `scripts/check_openapi_drift.py` compares the B-owned
operations in `CHECKED_OPERATIONS` (`POST /wallets/{id}/deposit` and
`POST /transfers`), as `create_app().openapi()` generates them, with the
contract. It reports:
- a checked operation missing from the app or the contract
- a different operationId or success status
- a status the app declares but the contract does not
- different security schemes
- missing, extra or differently required parameters
- request-body fields, required fields, unknown-field policy, types, enums and limits

It resolves `$ref`s, so a change to a shared schema such as `Amount` or
`Currency` is caught on both routes.

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
- *Scope.* Only Member B's routes are checked.
- *Header documentation.* `Idempotency-Key` is documented through
  `openapi_extra` rather than a FastAPI `Header` parameter. Requests without it
  still get 400 `IDEMPOTENCY_KEY_MISSING`, not FastAPI's generic 422.

**Evidence.** 23 tests:
- the CI gate and the command line
- one mutation of the contract per kind of drift, each checked to be caught,
  and new drift failing the command
- wording and extra contract-only statuses checked to be ignored
- real deposit and transfer responses validate against the contract's
  `Transaction` and `Transfer` schemas
- a missing key still gives 400

**Found.** DEF-001 in `docs/defect-log.md`, fixed here: the deposit and
transfer routes did not publish the `Idempotency-Key` header, and deposit did
not publish bearer auth.

Related: [[projects/2026-11-25-b02-deposit]], [[projects/2026-11-25-b03-transfers]],
[[projects/2026-11-19-c02-api-contract]], [[log]].
