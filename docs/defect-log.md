# Defect log

Defects found by testing, one row each, with the test that shows the problem
and the owner who fixes it (TQ-8). Started by Member B during B04.

| ID | Found | Found by | Area and owner | Defect | Regression test | Status |
|---|---|---|---|---|---|---|
| DEF-001 | 2026-11-26 | B04 full local run (`python -m pytest -q backend/tests tests`) | `backend/tests/test_reversal.py` (D02, Member D) | `test_reverse_deposit_mirrors_entries_using_c03_fake` runs `UPDATE wallets SET balance_minor = 10_000`. SQLite accepts `_` digit separators only from 3.46. The official Windows Python 3.11.9 ships SQLite 3.45.1, so the test fails there with `unrecognized token: "10_000"`, while CI on Ubuntu passes. | The test itself fails on SQLite 3.45. Fix: use `10000` or a bound parameter. | Open, reported to the owner |

The B04 exactly-once suite (`backend/tests/test_exactly_once_http.py`) found
no defects in deposit, transfer or idempotency behaviour.
