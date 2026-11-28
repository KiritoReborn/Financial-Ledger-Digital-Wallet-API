---
title: "Why the stored digest cannot sign in"
type: research
author: "Harshith (Member A)"
date: "2026-11-28"
category: "inbox"
tags: ["auth", "sqlite"]
requirements: ["FR-1.2"]
source: "backend/app/auth.py, issue_user_token and authenticated_user_id; backend/tests/test_wallet_creation.py"
---

# Why the stored digest cannot sign in

Registration returns a random token from `secrets.token_urlsafe(32)`. SQLite gets its SHA-256 hex digest. Authentication hashes the presented token before looking it up. Pasting a digest from the table therefore looks for a digest of that digest.

The wallet authentication test exercises that distinction on wallet list, detail and creation. Each request returns 401 and the owner's original wallet is still there. Hashing protects the stored copy. Anyone who obtains the original bearer token can still present it. See [[projects/fr-1-user-registration]] and [PR #60](https://github.com/KiritoReborn/Financial-Ledger-Digital-Wallet-API/pull/60).
