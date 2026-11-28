---
title: "Wallet validation at the HTTP boundary"
author: "Harshith (Member A)"
date: "2026-11-28"
category: "projects"
tags: ["auth", "wallets"]
requirements: ["FR-1.2", "FR-1.3"]
source: "backend/tests/test_wallet_creation.py; README.md"
---

# Wallet validation at the HTTP boundary

A rejected create must leave the wallet list unchanged. The regression submits a balance, system flag and wallet ID separately, checks the list is still empty, then creates a valid wallet with a zero balance.

The credential cases start with a real user and wallet. A wrong scheme, an empty bearer credential and the stored token digest all return 401 on list, detail and create. A valid owner can still read the original wallet. Ownership checks using another valid user are covered in [[projects/fr-1-wallets]].

Run `python -m pytest -q backend/tests/test_registration.py backend/tests/test_user_tokens.py backend/tests/test_wallet_creation.py`. The integrated H09 branch passed all 21 cases. [PR #60](https://github.com/KiritoReborn/Financial-Ledger-Digital-Wallet-API/pull/60)
