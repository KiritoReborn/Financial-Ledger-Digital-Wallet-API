# Wallet UI

Use Node 24.19 for the shared Prism mock. From the repository root, start each server in its own terminal.

```sh
npm --prefix tools/api-mock ci
npm --prefix tools/api-mock start
```

```sh
npm --prefix frontend ci
npm --prefix frontend run dev
```

Open the local URL printed by Vite. Sign in with a disposable token for Prism. The wallets page requests the fixture list through the Vite proxy. For the running backend, set `LEDGER_API_TARGET=http://127.0.0.1:8000` when starting Vite and use a registered user's token.

Feature screens use `src/api.js`. Pass a JSON body, method, headers and optional abort signal. For public or admin calls set `authenticated: false` and pass any required admin headers from memory. The result includes response headers for replay detection. Sign-out clears the user token from the current tab.

Run `npm --prefix frontend test` and `npm --prefix frontend run build`. Serving the production build requires SPA fallback to index.html and a reverse proxy from /api to the backend.
