# **Financial Ledger & Digital Wallet API**
## Prepared by:
  * Varanasi Harshith Raj
  * Potturu Pranav Sai
  * Jaya Raghunandhan Reddy
  * Gangavarapu Jaswant
## Project Scope:
 * This System is the backend of a digital wallet with a React frontend, build on a double-entry ledger. It addresses three problems: **balance updates that overwrite each other under concurrency**, **duplicate charges caused by network retries**, and **ledger records that can be silently altered**.

**In scope:** registration, wallets in several currencies, simulated deposits, idempotent transfers, safe concurrent balance changes, an append-only ledger with explicit reversals, an administrative reconciliation check, demonstration-level token authentication, the frontend, five agent skills, the second brain and CI.

**Out of scope:** real payments, currency conversion, notifications, KYC, multi-machine deployment, production-grade authentication and a tamper-evident hash chain. Deposits are simulated funding, not payments.

## Project Perspective:
 * This System is a new, self-contained product: one process, one machine, one SQLite database file, no external service.
