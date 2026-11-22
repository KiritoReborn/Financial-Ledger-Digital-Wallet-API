# C02 API contract and mock

`openapi.yaml` describes all 11 operations in the final 14-page SRS. It is an
OpenAPI 3.0.3 proposal, version 0.1.0-provisional, pending A/B/D review.
It documents their routes without implementing their services.

## Run the mock

Use Node.js 24.19.0 to match CI. The locked Prism dependencies require Node.js
24.18.0 or newer. Run these commands from the repository root.

```sh
npm --prefix tools/api-mock ci --ignore-scripts --no-audit --no-fund
npm --prefix tools/api-mock start
```

In another terminal:

```sh
python scripts/check_api_mock.py
```

The mock listens only on `127.0.0.1:4010`; the real API uses port 8000.
The smoke check uses obvious example credentials and exercises every route,
request/response headers and a declared 422 response via `Prefer: code=422`.
Prism returns static examples: it neither authenticates real users nor stores
money, implements idempotency or performs reconciliation. Its own malformed
request errors are Prism errors; use the declared fixtures to preview the
application's error envelope. A static request ID is a fixture, not the real
server's per-request generation behavior.

## Contract decisions requiring review

- Resource IDs use UUID v4. History entry IDs and `before_id` are proposed as
  positive SQLite integers, matching A's actual migration 001 and the SRS ER
  figure's auto-generated entry key. The SRS's general UUID convention creates
  an ambiguity: A/B/D must agree on this exception before freezing the contract.
  No migration is changed here.
- DTO envelopes not explicitly fixed by the SRS are proposals. In particular,
  history returns `entries` and `next_before_id`; registration returns its token
  once; reconciliation returns `ok`, `checks` and `mismatches`.
- Strict integer money (1 through 10^12), supported currencies, UUID v4 shape,
  unknown-field rejection, ownership/auth errors and financial idempotency
  headers are documented. The supplemental 16 KiB body limit is identified in
  C01 traceability; runtime middleware already tests it.

## Validation

Install `backend[dev]`, then run `python -m pytest -q backend/tests tests`.
Tests check path/method coverage, the OpenAPI document, schemas and examples,
money boundaries, unknown fields, UUID/currency validation and history limits.
The real health route is compared with FastAPI's generated schema. Full
implementation drift enforcement remains B08-owned after routes exist.
CI installs Prism and its dependencies from `tools/api-mock/package-lock.json`,
starts the mock, and runs the HTTP smoke check.
