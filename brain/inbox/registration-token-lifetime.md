---
title: "Where the registration token lives"
type: research
author: "Harshith (Member A)"
date: "2026-11-28"
category: "inbox"
tags: ["registration", "browser"]
requirements: ["EI-UI-1"]
source: "SRS.pdf, EI-UI-1; frontend/src/Register.jsx and frontend/src/main.jsx"
---

# Where the registration token lives

The registration response is the one chance to copy the issued token. The form holds it in component state. Following the sign-in link leaves that view, so the save warning and copy button belong on the registration page.

A pasted token is checked with the wallet API before being saved in session storage. Reloading the tab retains the session. Signing out removes its key. A successful copy places the token on the user's clipboard, which sign-out does not clear. [[projects/fr-1-user-registration]] records the server side of this flow. [PR #58](https://github.com/KiritoReborn/Financial-Ledger-Digital-Wallet-API/pull/58).
