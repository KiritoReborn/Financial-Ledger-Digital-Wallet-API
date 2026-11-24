"""Exercise static Prism fixtures, never the production API or real funds."""

import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID

BASE = "http://127.0.0.1:4010"
WALLET = "00000000-0000-4000-8000-000000000001"
OTHER = "00000000-0000-4000-8000-000000000002"


def request(method, path, body=None, expected=200, prefer=None, *, admin=False, key=None):
    headers = {}
    if path not in {"/health", "/users"}:
        headers["Authorization"] = "Bearer example-only-not-a-real-token"
    if admin:
        headers["X-Admin-Key"] = "example-only-not-a-real-admin-key"
    if key:
        headers["Idempotency-Key"] = key
    if body is not None:
        headers["Content-Type"] = "application/json"
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
        assert UUID(response.headers["X-Request-ID"]).version == 4
        if key and expected == 201:
            assert response.headers.get("Idempotent-Replayed") == "false"
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
    deposit = request("POST", f"/wallets/{WALLET}/deposit", {"amount_minor": 100}, 201, key="deposit-1")
    transfer = {"from_wallet_id": WALLET, "to_wallet_id": OTHER,
                "amount_minor": 100, "currency": "INR"}
    posted = request("POST", "/transfers", transfer, 201, key="transfer-1")
    assert posted["id"] != deposit["id"]
    assert request("GET", f"/transfers/{posted['id']}") == posted
    history = request("GET", f"/wallets/{WALLET}/transactions?limit=20")
    assert all(entry["wallet_id"] == WALLET for entry in history["entries"])
    assert any(entry["txn_id"] == posted["id"] and entry["direction"] == "DEBIT"
               for entry in history["entries"])
    reversal = request("POST", f"/transactions/{posted['id']}/reverse", {}, 201, admin=True, key="reverse-1")
    assert reversal["reverses_txn_id"] == posted["id"] and reversal["id"] != posted["id"]
    assert {(e["wallet_id"], e["direction"], e["amount_minor"]) for e in reversal["entries"]} == {
        (WALLET, "CREDIT", 100), (OTHER, "DEBIT", 100)
    }
    report = request("GET", "/admin/reconcile", admin=True)
    assert report["ok"] and all(report["checks"].values()) and report["mismatches"] == []
    error = request("POST", "/transfers", transfer, 422, "code=422, example=conflict", key="transfer-1")
    assert error["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    print("Prism: all 11 operations and a declared error fixture passed.")


if __name__ == "__main__":
    main()
