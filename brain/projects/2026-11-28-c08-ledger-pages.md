---
title: "C08 wallet history and concurrency screens"
author: "Codex (AI-assisted implementation record for Member C)"
date: "2026-11-28"
category: projects
tags: [frontend, history, concurrency]
requirements: [EI-UI-5, EI-UI-4, FR-3.6, FR-3.3]
---

# C08 wallet history and concurrency screens

After sign-in, **History** lists the user's wallets. Choose a wallet to
see the type, direction, amount and timestamp of each entry and load its
older entries. The page passes the server's exclusive cursor through without
rounding SQLite's 64-bit IDs.

**Concurrency demo** sends two simulated transfers from the selected wallet.
Each operation keeps its own key. If a result is uncertain, **Send again with
same key** sends only the uncertain operation and reports a replay when the
server returns one. Definite results stay visible. Use funded test wallets
of the same currency and an amount between half and all of the sender's
balance to demonstrate one successful and one rejected transfer.

Run `npm --prefix frontend test` and `npm --prefix frontend run build`. Live
history depends on the C06 API working in the same deployment. C08 uses
the H07 session and API client and the B05 amount and retry functions.

All 41 frontend tests passed. A run through Vite's proxy and a disposable
live API loaded 20 history entries and then one older entry. Two concurrent
transfers produced one posting and one insufficient-funds rejection. The
next history load showed the debit first, and the sender balance was exact.
The local Vite build passed using cached React Router 7.11.0 because the
lockfile's 7.18.7 release was unavailable in the sandbox cache.

[H07 shell issue](https://github.com/KiritoReborn/Financial-Ledger-Digital-Wallet-API/issues/48) ·
[Final SRS](../../SRS.pdf#page=4).
