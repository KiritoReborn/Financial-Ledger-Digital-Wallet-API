# Deposits and transfers

How to add simulated funds to a wallet and move them between users, safely
repeatable with an `Idempotency-Key` (FR-1.6, FR-1.7, FR-2.4 to FR-2.10).
All amounts are **simulated** integer minor units: paise for INR, cents for
USD, whole yen for JPY. No real money is ever involved.

Every value below in angle brackets, such as `<token>` or `<wallet-id>`, is a
placeholder. Never paste a real token into a document, an issue, a commit or a
chat.

## 1. Set up the environment

Start the API as described in the root README, then set these variables in
your own shell only:

| Variable | Used for |
|---|---|
| `API_BASE_URL` | API address, default `http://127.0.0.1:8000` |
| `LEDGER_TOKEN` | Bearer token of the user making deposits and transfers |
| `ADMIN_TOKEN`, `ADMIN_KEY` | Only for `reconcile` |

```powershell
$env:API_BASE_URL = "http://127.0.0.1:8000"
$env:LEDGER_TOKEN = Get-Content .\alice.token
```

`scripts/api_client.py` reads only these variables and never prints, logs or
puts them in a URL. Tokens are sent only over HTTPS, or over plain HTTP to
`localhost`, `127.0.0.1` or `::1`.

## 2. Register and create a wallet

```powershell
python scripts/api_client.py register Alice alice@example.test --token-file .\alice.token
$env:LEDGER_TOKEN = Get-Content .\alice.token
python scripts/api_client.py create-wallet INR
python scripts/api_client.py wallets
```

`register` writes the token to a **new** file and prints `<written to ...>` in
its place. It refuses to overwrite an existing file. Keep token files out of
the repository.

## 3. Deposit

```powershell
python scripts/api_client.py deposit <wallet-id> 2500
```

`POST /wallets/{id}/deposit` with body `{"amount_minor": 2500}` credits your
own wallet from the system wallet of its currency. The response is `201` with
the transaction and both ledger entries.

## 4. Transfer

```powershell
python scripts/api_client.py transfer <from-wallet-id> <to-wallet-id> 100 INR --description "Lunch"
```

`POST /transfers` with body:

```json
{
  "from_wallet_id": "<from-wallet-id>",
  "to_wallet_id": "<to-wallet-id>",
  "amount_minor": 100,
  "currency": "INR",
  "description": "Lunch"
}
```

- The sender wallet must be yours. The receiver can be any user's wallet.
- Both wallets must hold the request currency.
- `description` is optional, at most 200 characters.

The response is `201` with the `Transfer`.

## 5. Idempotency keys and retries

Every deposit and transfer needs an `Idempotency-Key` header: 1 to 128
characters from `A-Z a-z 0-9 - _ . :`. The client generates a new UUID v4 for
each operation and prints it as `idempotency_key`.

| You send | You get |
|---|---|
| A new key | The operation runs once; `Idempotent-Replayed: false` |
| The same key and the same body | The stored response again; `Idempotent-Replayed: true`; no money moves |
| The same key and a different body | `422 IDEMPOTENCY_CONFLICT`; nothing changes |
| No key, or a blank one | `400 IDEMPOTENCY_KEY_MISSING` |

Keys belong to one user and one kind of operation, so your deposit key and your
transfer key never clash, and another user cannot reuse yours.

**After a timeout or a `5xx`, retry with the same key and the same body.** If
the first attempt succeeded, you get its stored response; if it failed, nothing
was stored and the retry runs normally. A rejected request (4xx) stores no key,
so you can fix the cause and send it again with the same key.

```powershell
python scripts/api_client.py transfer <from-wallet-id> <to-wallet-id> 100 INR --key <idempotency-key-from-first-attempt>
```

The client never retries on its own.

## 6. Errors

| Status | Code | Meaning |
|---|---|---|
| 400 | `IDEMPOTENCY_KEY_MISSING` | No key, or a blank one |
| 401 | `UNAUTHENTICATED` | Missing or wrong bearer token |
| 403 | `FORBIDDEN` | The wallet you send from, or deposit into, is not yours |
| 404 | `NOT_FOUND` | A wallet does not exist |
| 422 | `VALIDATION_ERROR` | Bad amount, ID, currency, field or key; or the same wallet twice |
| 422 | `CURRENCY_MISMATCH` | A wallet holds another currency |
| 422 | `INSUFFICIENT_FUNDS` | The sender's balance is too low |
| 422 | `IDEMPOTENCY_CONFLICT` | The key was already used with another body |
| 503 | `DATABASE_BUSY` | The database was busy; retry with the same key |

Checks run in this order: token, then key, then wallets and funds. The command
line prints errors to stderr as JSON with the code and request ID, and exits
with 1. A refused call, such as a missing token or a malformed wallet ID,
exits with 2 before anything is sent.

`amount_minor` must be a JSON integer from 1 to 10^12. `10.5`, `100.0`,
`"100"` and `true` are rejected.

## 7. Use it from Python

```python
from api_client import LedgerClient  # with scripts/ on sys.path

client = LedgerClient.from_env()
result = client.transfer("<from-wallet-id>", "<to-wallet-id>", 100, "INR")
print(result.body["id"], result.key, result.replayed)
```

`ApiError` carries `status`, `code`, `message`, `details` and `request_id`.
`ClientError` means the client refused to send, or could not reach or read the
API. Neither ever contains a token.
