"""Exercise the NFR-PERF-1 workload on a local API with a disposable ledger."""

import argparse
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from statistics import median, quantiles
from threading import Barrier, BrokenBarrierError
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import uuid4


@dataclass(frozen=True)
class StressResult:
    outcomes: Counter[tuple[int, str | None]]
    sender_balance: int
    receiver_balance: int
    elapsed_seconds: float
    median_ms: float
    p95_ms: float


class RejectRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


_local_http = build_opener(ProxyHandler({}), RejectRedirect())


def request_json(base_url, method, path, *, token=None, body=None, key=None):
    headers = {"Accept": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if key is not None:
        headers["Idempotency-Key"] = key
    if body is not None:
        headers["Content-Type"] = "application/json"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = Request(base_url + path, data=data, headers=headers, method=method)
    try:
        response = _local_http.open(request, timeout=10)
    except HTTPError as error:
        response = error
    with response:
        try:
            payload = json.load(response)
        except (ValueError, UnicodeError):
            raise ValueError(
                f"{method} {path} returned HTTP {response.status} without JSON."
            ) from None
        if not isinstance(payload, dict):
            raise TypeError(
                f"{method} {path} returned a JSON value instead of an object."
            )
        return response.status, payload


def run_reference_workload(port: int) -> StressResult:
    base_url = f"http://127.0.0.1:{port}"

    def expect(method, path, expected, **kwargs):
        status, payload = request_json(base_url, method, path, **kwargs)
        if status != expected:
            raise ValueError(
                f"{method} {path} returned HTTP {status}, expected {expected}."
            )
        return payload

    def create_wallet():
        user = expect(
            "POST",
            "/users",
            201,
            body={"name": "Stress test", "email": f"{uuid4()}@example.com"},
        )
        token = user.get("token")
        if not isinstance(token, str) or not token.strip():
            raise ValueError("Registration did not return a usable bearer token.")
        wallet = expect("POST", "/wallets", 201, body={"currency": "INR"}, token=token)
        wallet_id = wallet.get("id")
        if not isinstance(wallet_id, str) or not wallet_id:
            raise ValueError("Wallet creation did not return an ID.")
        return token, wallet_id

    sender_token, sender = create_wallet()
    receiver_token, receiver = create_wallet()
    if sender == receiver:
        raise ValueError("Wallet creation returned the same ID for both test users.")

    expect(
        "POST",
        f"/wallets/{sender}/deposit",
        201,
        body={"amount_minor": 100_000},
        token=sender_token,
        key=str(uuid4()),
    )
    transfer = {
        "from_wallet_id": sender,
        "to_wallet_id": receiver,
        "amount_minor": 3_000,
        "currency": "INR",
    }
    start = Barrier(50, timeout=30)

    def send_transfer():
        start.wait()
        started_at = perf_counter()
        status, payload = request_json(
            base_url,
            "POST",
            "/transfers",
            body=transfer,
            token=sender_token,
            key=str(uuid4()),
        )
        elapsed_ms = (perf_counter() - started_at) * 1_000
        error = payload.get("error")
        code = error.get("code") if isinstance(error, dict) else None
        return (
            status,
            "INSUFFICIENT_FUNDS" if code == "INSUFFICIENT_FUNDS" else None,
        ), elapsed_ms

    with ThreadPoolExecutor(max_workers=50) as workers:
        workload_started_at = perf_counter()
        futures = [workers.submit(send_transfer) for _ in range(50)]
        results = [future.result() for future in futures]
        elapsed_seconds = perf_counter() - workload_started_at
    outcomes = Counter(outcome for outcome, _ in results)
    if outcomes != {(201, None): 33, (422, "INSUFFICIENT_FUNDS"): 17}:
        raise ValueError(f"Unexpected transfer results: {dict(outcomes)}")

    sender_balance = expect("GET", f"/wallets/{sender}", 200, token=sender_token).get(
        "balance_minor"
    )
    receiver_balance = expect(
        "GET", f"/wallets/{receiver}", 200, token=receiver_token
    ).get("balance_minor")
    if (
        type(sender_balance) is not int
        or sender_balance != 1_000
        or type(receiver_balance) is not int
        or receiver_balance != 99_000
    ):
        raise ValueError(
            "Unexpected ending balances. Expected 1,000 for sender and 99,000 for receiver."
        )
    durations = [elapsed_ms for _, elapsed_ms in results]
    return StressResult(
        outcomes,
        sender_balance,
        receiver_balance,
        elapsed_seconds,
        median(durations),
        quantiles(durations, n=100, method="inclusive")[94],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--port", type=int, default=8000, help="Port of the local ledger API."
    )
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    try:
        result = run_reference_workload(args.port)
    except (ValueError, TypeError, URLError, TimeoutError, BrokenBarrierError) as error:
        parser.exit(1, f"Reference stress test failed: {error}\n")
    print("50 transfers: 33 succeeded, 17 returned INSUFFICIENT_FUNDS.")
    print(
        f"Final balances: {result.sender_balance:,} sender and {result.receiver_balance:,} receiver."
    )
    print(
        f"Batch took {result.elapsed_seconds:.2f} s. "
        f"Transfer latency: median {result.median_ms:.1f} ms, p95 {result.p95_ms:.1f} ms."
    )


if __name__ == "__main__":
    main()
