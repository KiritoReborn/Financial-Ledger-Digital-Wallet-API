# 0003 · Store the digest of the registration token

Status: implemented. Requirements: FR-1.2 and EI-UI-1.

Registration must give the user a reusable bearer credential. Storing the issued token verbatim would make a database copy sufficient to sign in. The API issues a random token once, indexes its SHA-256 digest and applies the same digest operation during lookup. This decision relies on server-generated, high-entropy tokens.

The UI gives the user one opportunity to save the issued token. A later sign-in validates it before placing it in tab session storage. Losing the original token prevents signing in with its database value. Presenting a stored digest is a regression case on all three wallet routes.

Evidence: [digest lookup](../../brain/inbox/bearer-token-digests.md), [token lifetime](../../brain/inbox/registration-token-lifetime.md), [dashboard PR](https://github.com/KiritoReborn/Financial-Ledger-Digital-Wallet-API/pull/58), [validation PR](https://github.com/KiritoReborn/Financial-Ledger-Digital-Wallet-API/pull/60).
