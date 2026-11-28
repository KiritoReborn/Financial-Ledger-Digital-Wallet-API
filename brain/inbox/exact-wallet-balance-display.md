---
title: "Keeping the last digit of a wallet balance"
type: research
author: "Harshith (Member A)"
date: "2026-11-28"
category: "inbox"
tags: ["wallets", "currency"]
requirements: ["EI-UI-2", "EI-UI-8"]
source: "SRS.pdf, EI-UI-8; frontend/src/api.js; frontend/tests/balances.test.js"
---

# Keeping the last digit of a wallet balance

A SQLite balance can reach 9223372036854775807 minor units. A JavaScript Number can round that value during JSON parsing, before a formatter ever sees it. The API client uses the original numeric text for unsafe balances and converts it to BigInt. If the browser cannot supply that text, the client reports an error.

The dashboard inserts the decimal point using the shared currency exponent. The upper bound displays as 92233720368547758.07 USD. The same formatter displays −1 minor INR as -0.01 and 501 minor JPY as 501. The regression starts with a JSON response, so it catches rounding at either step. [[projects/fr-1-wallets]] · [PR #58](https://github.com/KiritoReborn/Financial-Ledger-Digital-Wallet-API/pull/58).
