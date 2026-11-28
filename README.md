# **Financial Ledger & Digital Wallet API**
## Prepared by:
  * Varanasi Harshith Raj
  * Potturu Pranav Sai
  * Jaya Raghunandhan Reddy
  * Gangavarapu Jaswanth
## Project Scope:
 * This System is the backend of a digital wallet with a React frontend, build on a double-entry ledger. It addresses three problems: **balance updates that overwrite each other under concurrency**, **duplicate charges caused by network retries**, and **ledger records that can be silently altered**.

**In scope:** registration, wallets in several currencies, simulated deposits, idempotent transfers, safe concurrent balance changes, an append-only ledger with explicit reversals, an administrative reconciliation check, demonstration-level token authentication, the frontend, five agent skills, the second brain and CI.

**Out of scope:** real payments, currency conversion, notifications, KYC, multi-machine deployment, production-grade authentication and a tamper-evident hash chain. Deposits are simulated funding, not payments.

## Project Perspective:
 * This System is a new, self-contained product: one process, one machine, one SQLite database file, no external service.

## Setup & Run (about 10 minutes) — DI-1

From a clean clone, run these commands in Bash with Python 3.11 and Git installed.

```bash
git clone https://github.com/harshith-raj-06/Financial-Ledger-Digital-Wallet-API.git
cd Financial-Ledger-Digital-Wallet-API
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
# Edit .env to supply your own admin credentials.
set -a
source .env
set +a
python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port "$PORT"
```

Startup creates the database at `DATABASE_PATH` and applies pending migrations. From a second terminal, run `curl http://127.0.0.1:8000/health` (adjust the port if changed). A healthy database returns `{"status":"ok"}`. To run the local checks, activate the same environment and run `ruff check .` and `python -m pytest -q backend/tests tests`.

## Important Notices

* **Simulated funds only (SAF-1):** Deposits are simulated funding, not payments. No real money is moved, and the system must not be connected to real payment services.
* **Demonstration-level authentication (SAF-1):** Token authentication exists to demonstrate the design. It is not production-grade and must not be used to protect real accounts or data.
* **Append-only, not tamper-evident (CA-3):** The ledger is *database-enforced append-only*: SQLite triggers reject every `UPDATE` and `DELETE` on `transactions` and `ledger_entries` (FR-4.1), and mistakes are fixed with explicit reversals. It is **not** a tamper-evident hash chain, so someone with direct access to the database file could alter it undetected.


## Registration and wallet validation

Register with `POST /users` using a name and email. Save the returned token when it is issued. Send it in the `Authorization: Bearer <token>` header for wallet requests. Keep the token out of URLs and logs.

Create a wallet with `POST /wallets` and a body such as `{"currency":"INR"}`. Each user can have one wallet per supported currency (INR, USD, JPY). The server assigns the owner and ID and starts the balance at zero. Use `GET /wallets` to list your wallets or `GET /wallets/{id}` to retrieve one.

| Request | Expected result |
| --- | --- |
| Register an email already in use | 409 |
| Use a missing or invalid bearer credential | 401 |
| Read another user's wallet with a valid token | 403 |
| Read an unknown wallet with a valid token and valid UUID | 404 |
| Request a duplicate currency, an unsupported currency, or provide a balance on creation | 422 |

Run the focused regression with `python -m pytest -q backend/tests/test_registration.py backend/tests/test_user_tokens.py backend/tests/test_wallet_creation.py`. Tests use temporary SQLite databases.
