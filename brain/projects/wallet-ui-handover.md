---
title: "From registration to a funded wallet"
author: "Harshith (Member A)"
date: "2026-11-28"
category: "projects"
tags: ["frontend", "wallets"]
requirements: ["EI-UI-1", "EI-UI-2", "EI-UI-8"]
source: "frontend/src/Register.jsx; frontend/src/Wallets.jsx; frontend/src/MoneyPages.jsx"
---

# From registration to a funded wallet

The shared router and Prism client landed in [PR #49](https://github.com/KiritoReborn/Financial-Ledger-Digital-Wallet-API/pull/49). The registration screen now shows the issued token once. Sign-in checks the pasted token against the wallet list before keeping it in the tab. See [[projects/fr-1-user-registration]] for what the API stores.

The dashboard reads the currency exponents used by the backend. Its deposit link carries the selected wallet ID into the deposit form. This matters when the user has two wallets and opens Deposit from the second one. The integrated build and 39 frontend tests passed in [PR #58](https://github.com/KiritoReborn/Financial-Ledger-Digital-Wallet-API/pull/58).

For the local flow, follow the [frontend setup](../../frontend/README.md) and use a disposable registered user.
