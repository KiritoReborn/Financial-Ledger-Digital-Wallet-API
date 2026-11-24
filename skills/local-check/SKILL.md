---
name: local-check
description: Verify a local Financial Ledger & Digital Wallet API setup by installing dependencies, linting and building the backend, running pytest, starting the FastAPI server against an isolated SQLite database, calling GET /health, and reporting a pass/fail summary per step without logging secrets.
---

# Local Check (`local-check`)

Run a repeatable end-to-end verification of a local developer environment for the
**Financial Ledger & Digital Wallet API** (`SK-5`, `SK-6`, `UC-10`, `DI-1`).

## Secret-Safety Rules (`SK-6`, `NFR-SEC-7`)

- **Never display, echo, log, or store secrets or credentials.** Do not print
  `ADMIN_TOKEN`, `ADMIN_KEY`, bearer tokens, `.env` contents, or full `env` /
  `printenv` output at any point during execution or in the final report.
- `GET /health` is unauthenticated (`EI-SW-1`), so this check requires **no**
  tokens or admin keys.
- Any other skill that calls authenticated endpoints must inject credentials
  exclusively from environment variables via `scripts/api_client.py` (`SK-6`).
- Report only high-level status codes, test counts, and sanitized error codes —
  never include raw secrets, Authorization headers, or sensitive file paths.

## Prerequisites

- Run from the repository root.
- Python 3.11+ available (`python3 --version`).
- SQLite 3.35+ (bundled with standard Python 3.11+).

## Step-by-Step Procedure

Execute the steps in order and record `PASS` or `FAIL` for each step. Always
run **Step 6 (Cleanup)** even if an earlier step fails.

### Step 1 — Install Dependencies

Create (or reuse) a virtual environment and install the backend package with its
development dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

- **Pass condition:** Exit code `0`; `pytest`, `ruff`, `fastapi`, and `uvicorn`
  are importable from `.venv`.

### Step 2 — Build & Lint (`CI-1`, `CI-2`)

Lint the repository and build the backend distribution into a temporary folder
so no build artifacts remain in the working tree:

```bash
python -m ruff check .
python -m ruff check backend
TMP_DIST="$(mktemp -d)"
python -m build --outdir "$TMP_DIST"
rm -rf "$TMP_DIST"
```

- **Pass condition:** Both `ruff` checks report `All checks passed!` and
  `python -m build` exits `0`.

### Step 3 — Run Test Suite (`TST-1`)

Run the backend and root test suites on isolated temporary SQLite databases:

```bash
python -m pytest -q backend/tests tests
```

- **Pass condition:** Exit code `0` with `0` failures. Record the total passed
  test count in the summary.

### Step 4 — Prepare Isolated Database & Start FastAPI Server (`DI-1`, `EI-CM-1`)

Set nonempty `ADMIN_TOKEN` and `ADMIN_KEY` in the process environment before startup.
Apply migrations to a disposable temporary SQLite file and launch the FastAPI
application on localhost (default port `8000`, configurable via `PORT`):

```bash
TMP_DIR="$(mktemp -d)"
TMP_DB="$TMP_DIR/local-check.sqlite3"
PORT="${PORT:-8000}"

python -m db.migrate "$TMP_DB"
DATABASE_PATH="$TMP_DB" python -m uvicorn app.main:create_app \
  --factory --host 127.0.0.1 --port "$PORT" \
  > "$TMP_DIR/server.log" 2>&1 &
SERVER_PID=$!
```

Wait briefly (up to 5 seconds) for `127.0.0.1:$PORT` to accept connections and
confirm `kill -0 "$SERVER_PID"` succeeds.

- **Pass condition:** Migrations exit `0` and the Uvicorn server process stays
  running and listening on `127.0.0.1:$PORT`.

### Step 5 — Call `GET /health` (`EI-SW-1`)

Send an unauthenticated request to `/health` without passing any credentials:

```bash
curl --silent --show-error --max-time 5 \
  --write-out "\nHTTP_STATUS:%{http_code}\n" \
  "http://127.0.0.1:${PORT}/health"
```

- **Pass condition:** `HTTP_STATUS:200` and JSON body `{"status":"ok"}`.
- **On failure:** Report only the HTTP status code and the sanitized error code
  (e.g. `503 DATABASE_BUSY` or `500 INTERNAL_ERROR`), never raw environment
  variables or secrets.

### Step 6 — Cleanup

Stop the temporary server process and remove the temporary directory:

```bash
kill "$SERVER_PID" 2>/dev/null || true
wait "$SERVER_PID" 2>/dev/null || true
rm -rf "$TMP_DIR"
```

## Output Format

Report results in a concise Pass/Fail summary table containing no secrets or
credentials:

| Step | Check | Result | Notes |
| --- | --- | --- | --- |
| 1 | Install dependencies (`pip install -e ".[dev]"`) | PASS / FAIL | e.g. Python 3.11, venv active |
| 2 | Lint & build (`ruff check`, `python -m build`) | PASS / FAIL | e.g. 0 lint issues, wheel built |
| 3 | Test suite (`pytest backend/tests tests`) | PASS / FAIL | e.g. 108 passed |
| 4 | Start FastAPI server (`db.migrate` + `uvicorn`) | PASS / FAIL | e.g. listening on `127.0.0.1:8000` |
| 5 | Health check (`GET /health`) | PASS / FAIL | e.g. HTTP `200`, `{"status":"ok"}` |

**Overall:** `PASS` only if all 5 steps pass; otherwise `FAIL` with the first
failing step and a sanitized diagnostic note.

## Second Brain References (`SB-0`–`SB-7`)

- [[2026-11-19-c01-health]] — Read-only `GET /health` readiness adapter and sanitized error contract (`EI-SW-1`, `NFR-SEC-7`).
- [[h02-database-migration]] — Idempotent SQLite migration runner (`python -m db.migrate`, `DB-6`).
- [[constant-time-secret-comparison]] — Secret handling and non-logging requirements (`NFR-SEC-2`, `NFR-SEC-7`, `SK-6`).
- [[2026-11-20-d03-reconciliation]] — Backend test and Ruff verification baseline.
