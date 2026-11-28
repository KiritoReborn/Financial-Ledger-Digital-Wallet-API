# 0004 · Preserve integer balances through display

Status: implemented. Requirements: EI-UI-2 and EI-UI-8.

Wallet responses encode signed 64-bit minor units as JSON integers. Dividing an already rounded JavaScript Number by 100 loses cents for large values and applies the wrong scale to JPY.

The client reads the source digits when a balance exceeds the safe integer range. The shared formatter places the decimal point according to the backend currency table. This keeps the wire contract and makes the dashboard and deposit wallet selector agree. Browsers without source-digit support can display safe integers and report an error for unsafe balances.

Evidence: [balance research and boundary examples](../../brain/inbox/exact-wallet-balance-display.md), [dashboard integration](https://github.com/KiritoReborn/Financial-Ledger-Digital-Wallet-API/pull/58).
