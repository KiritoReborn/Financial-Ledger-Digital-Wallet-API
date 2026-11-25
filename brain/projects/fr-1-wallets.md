---
title: Wallet creation and ownership
work_package: H05
date: 2026-11-25
requirements: [FR-1.3, FR-1.4, FR-1.5, FR-1.8, FR-1.9]
tags: [wallets, sqlite]
---

# Wallet creation and ownership

A bearer token identifies the owner for all three wallet routes. A second create for the same owner and currency returns 422. Listing filters by owner. Detail lookup returns 403 for a foreign wallet and 404 for an unknown ID.

Startup creates missing system wallets in the admin bootstrap transaction. Restarting preserves each existing wallet ID and balance, including negative clearing balances. The backend reads the currency exponents from the same JSON file imported by the frontend.

[Wallet tests](../../backend/tests/test_wallet_creation.py) · [[projects/fr-1-user-registration]] · [[projects/h03-sqlite-provider]]
