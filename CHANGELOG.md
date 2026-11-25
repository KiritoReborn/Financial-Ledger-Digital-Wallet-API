# Changelog

All notable changes to the **Financial Ledger & Digital Wallet API** are documented
in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
(`VC-5`).

## [Unreleased]

### Added

- **Database schema & immutability (`H02`, `H03`, `D01`):**
  - Six-table SQLite schema (`users`, `wallets`, `transactions`, `ledger_entries`,
    `idempotency_keys`, `schema_migrations`) in `db/migrations/001_initial_schema.sql`
    with `DB-3` currency-consistency insert trigger.
  - Append-only `BEFORE UPDATE` and `BEFORE DELETE` triggers on `transactions`
    and `ledger_entries` in `db/migrations/002_immutability_triggers.sql` (`FR-4.1`),
    verified against real migrations on WAL file-backed SQLite.
  - Idempotent migration runner (`db/migrate.py`) and shared `SqliteDatabase`
    provider (`backend/app/database.py`) enforcing `WAL`, `foreign_keys=ON`,
    `synchronous=FULL`, `timeout=5.0`, and caller-owned `BEGIN IMMEDIATE` writes.
- **API shell, contracts, and double-entry posting (`C01`–`C05`):**
  - FastAPI application factory (`backend/app/main.py`), `GET /health`, strict
    CORS policy, 16 KiB POST body limit, `X-Request-ID` correlation, and
    sanitized error envelopes (`NFR-SEC-7`).
  - OpenAPI 3.x specification (`docs/api/openapi.yaml`), Prism mock smoke script
    (`scripts/check_api_mock.py`), provisional C03 service contracts and fakes
    (`backend/app/contracts/`), and C04 `LedgerPoster` (`backend/app/posting.py`)
    with rollback and crash-recovery tests.
- **Registration, wallets, idempotency, deposits, and transfers (`H04`, `H05`, `B01`–`B03`):**
  - `POST /users` registration with one-time random bearer tokens (SHA-256 hash
    storage) and `ADMIN_ID` startup bootstrap (`FR-1.1`, `FR-1.2`, `FR-1.9`).
  - `POST /wallets`, `GET /wallets`, `GET /wallets/{id}`, and system-wallet
    initialization across `INR`, `USD`, and `JPY` (`FR-1.3`–`FR-1.8`).
  - `SqliteRunIdempotent` (`backend/app/services/idempotency.py`) with canonical
    request fingerprinting (`FR-2.4`–`FR-2.10`), `POST /wallets/{id}/deposit`,
    and `POST /transfers`.
- **Administrative reconciliation, reversals, security, and CI (`D02`–`D04`, `D06`–`D09`):**
  - `GET /admin/reconcile` single-snapshot read-only reconciliation
    (`backend/app/services/reconciliation.py`) with exact Python-integer
    cumulative totals (`FR-5.1`–`FR-5.4`).
  - `POST /transactions/{id}/reverse` mirrored reversal service and endpoint
    (`backend/app/services/reversal.py`, `backend/app/api/admin.py`, `FR-4.2`–`FR-4.5`).
  - Admin security, concurrent race/replay, error sanitization, and SQLite
    tamper-detection suite (`tests/test_admin_security.py`).
  - Agent Skills `skills/local-check/SKILL.md` (`SK-5`) and
    `skills/brain-refine/SKILL.md` (`SK-3`), plus CI documentation/secret
    validator (`scripts/validate_repo_docs.py`, `.github/workflows/ci.yml`).
  - Admin operations and security guide (`docs/admin-security.md`).

### Changed

- Consolidated Python packaging into root `pyproject.toml` so `pip install -e ".[dev]"`
  and `python -m build` bundle both `app` and `db` migrations cleanly.
- Expanded `README.md` with 10-minute setup instructions (`DI-1`) and required
  `SAF-1` / `CA-3` safety notices.

### Security

- Enforced constant-time (`hmac.compare_digest` over SHA-256 digests) checks
  for both admin bearer token and `X-Admin-Key`, fail-closed startup when
  `ADMIN_TOKEN` or `ADMIN_KEY` is unset, and `NFR-SEC-7` error sanitization.

---

## Release Tag Preparation Checklist (`VC-5`)

1. Confirm all work-package PRs and `docs/traceability.csv` entries are merged on `main`.
2. Verify `python scripts/validate_repo_docs.py`, `pytest -q backend/tests tests`,
   `ruff check .`, and `ruff check backend` pass on `main`.
3. Update `[Unreleased]` to the release version heading (for example, `[0.1.0]`
   or `[1.0.0]`) with the release date, then create an annotated tag (`git tag -a v<version> -m "Release v<version>"`).
