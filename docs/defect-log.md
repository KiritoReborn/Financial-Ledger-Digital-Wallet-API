# Defect log

Defects found by testing, one row each, with the test that shows the problem
and the fix (TQ-8). Started by Member B during B04.

| ID | Found | Found by | Area | Defect | Regression test | Status |
|---|---|---|---|---|---|---|
| DEF-001 | 2026-11-26 | B08 drift check (`scripts/check_openapi_drift.py`) | `backend/app/api/deposit.py`, `backend/app/api/transfers.py` (B02/B03) | The generated OpenAPI omitted the required `Idempotency-Key` header on both routes and bearer auth on the deposit route. Runtime behaviour was correct; only the published schema was wrong. | `backend/tests/test_openapi_drift.py::test_deposit_and_transfer_match_the_documented_contract` | Fixed in B08 |

The B04 exactly-once suite (`backend/tests/test_exactly_once_http.py`) found
no defects in deposit, transfer or idempotency behaviour.
