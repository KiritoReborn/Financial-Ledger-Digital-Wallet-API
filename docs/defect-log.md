# Defect log

Defects found by testing, one row each, with the test that shows the problem
and the owner who fixes it (TQ-8). Started by Member B during B04; B08 added the
OpenAPI drift findings.

| ID | Found | Found by | Area and owner | Defect | Regression test | Status |
|---|---|---|---|---|---|---|
| DEF-001 | 2026-11-26 | B04 full local run (`python -m pytest -q backend/tests tests`) | `backend/tests/test_reversal.py` (D02, Member D) | `test_reverse_deposit_mirrors_entries_using_c03_fake` runs `UPDATE wallets SET balance_minor = 10_000`. SQLite accepts `_` digit separators only from 3.46. The official Windows Python 3.11.9 ships SQLite 3.45.1, so the test fails there with `unrecognized token: "10_000"`, while CI on Ubuntu passes. | The test itself fails on SQLite 3.45. Fix: use `10000` or a bound parameter. | Open, reported to the owner |
| DEF-002 | 2026-11-26 | B08 drift check (`scripts/check_openapi_drift.py`) | `backend/app/api/deposit.py`, `backend/app/api/transfers.py` (B02/B03, Member B) | The generated OpenAPI omitted the required `Idempotency-Key` header on both routes and bearer auth on the deposit route. Runtime behaviour was correct; only the published schema was wrong. | `backend/tests/test_openapi_drift.py::test_app_matches_the_documented_contract` | Fixed in B08 |
| DEF-003 | 2026-11-26 | B08 drift check | `backend/app/api/health.py` (Member C) | `GET /health` has the generated operationId `health_health_get`; the contract says `health`. | Same test; listed in `KNOWN_DRIFT` until fixed | Open, reported to the owner |
| DEF-004 | 2026-11-26 | B08 drift check | `backend/app/api/admin.py` (Member D) | `GET /admin/reconcile` has the generated operationId `reconcile_ledger_admin_reconcile_get` (contract `reconcile`) and declares no security (contract `bearerAuth` and `adminKey`). | Same test; listed in `KNOWN_DRIFT` until fixed | Open, reported to the owner |
| DEF-005 | 2026-11-26 | B08 drift check | `backend/app/api/admin.py` (Member D) | `POST /transactions/{id}/reverse` declares neither its security (`bearerAuth` and `adminKey`) nor the required `Idempotency-Key` header in the generated OpenAPI. | Same test; listed in `KNOWN_DRIFT` until fixed | Open, reported to the owner |

The B04 exactly-once suite (`backend/tests/test_exactly_once_http.py`) found
no defects in deposit, transfer or idempotency behaviour.
