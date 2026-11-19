"""Exercise static Prism fixtures, never the production API or real funds."""

import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = "http://127.0.0.1:4010"
WALLET = "00000000-0000-4000-8000-000000000001"
OTHER = "00000000-0000-4000-8000-000000000002"
TRANSACTION = "00000000-0000-4000-8000-000000000003"


def request(method, path, body=None, expected=200, prefer=None):
    headers = {
        "Authorization": "Bearer example-only-not-a-real-token",
        "X-Admin-Key": "example-only-not-a-real-admin-key",
        "Idempotency-Key": "mock-fixture-only",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    data = None if body is None else json.dumps(body).encode()
    call = Request(BASE + path, data=data, headers=headers, method=method)
    try:
        response = urlopen(call, timeout=3)
    except HTTPError as error:
        response = error
    with response:
        assert response.status == expected, (method, path, response.status, expected)
        payload = json.load(response)
        assert response.headers.get("X-Request-ID"), (method, path, "missing request ID")
        if method == "POST" and any(part in path for part in ("deposit", "transfer", "reverse")) and expected == 201:
            assert response.headers.get("Idempotent-Replayed") in {"true", "false"}
    print(f"{method} {path}: {expected}")
    return payload


def main():
    deadline = time.monotonic() + 20
    while True:
        try:
            health = request("GET", "/health")
            assert health == {"status": "ok"}
            break
        except (URLError, TimeoutError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.2)
    request("POST", "/users", {"name": "Example User", "email": "example@example.test"}, 201)
    request("POST", "/wallets", {"currency": "INR"}, 201)
    request("GET", "/wallets")
    request("GET", f"/wallets/{WALLET}")
    request("POST", f"/wallets/{WALLET}/deposit", {"amount_minor": 100}, 201)
    transfer = {"from_wallet_id": WALLET, "to_wallet_id": OTHER,
                "amount_minor": 100, "currency": "INR"}
    request("POST", "/transfers", transfer, 201)
    request("GET", f"/transfers/{TRANSACTION}")
    request("GET", f"/wallets/{WALLET}/transactions?limit=20")
    request("POST", f"/transactions/{TRANSACTION}/reverse", {}, 201)
    request("GET", "/admin/reconcile")
    error = request("POST", "/transfers", transfer, 422, "code=422")
    assert error["error"]["code"]
    print("Prism: all 11 operations and a declared error fixture passed.")


if __name__ == "__main__":
    main()
