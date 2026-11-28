from collections import Counter
from threading import Lock

import pytest

from scripts import check_transfer_stress as stress


@pytest.mark.parametrize("extra_success", [False, True])
def test_http_harness_checks_the_reference_counts_and_balances(
    monkeypatch, extra_success
):
    registrations = 0
    keys = set()
    lock = Lock()

    def request(base_url, method, path, *, token=None, body=None, key=None):
        nonlocal registrations
        assert base_url == "http://127.0.0.1:8000"
        if path == "/users":
            registrations += 1
            return 201, {"token": f"test-user-{registrations}"}
        if path == "/wallets":
            assert body == {"currency": "INR"}
            return 201, {
                "id": {
                    "test-user-1": "sender-wallet",
                    "test-user-2": "receiver-wallet",
                }[token]
            }
        if path == "/wallets/sender-wallet/deposit":
            assert key
            assert token == "test-user-1" and body == {"amount_minor": 100_000}
            return 201, {}
        if path == "/transfers":
            assert method == "POST" and token == "test-user-1"
            assert body == {
                "from_wallet_id": "sender-wallet",
                "to_wallet_id": "receiver-wallet",
                "amount_minor": 3_000,
                "currency": "INR",
            }
            with lock:
                assert key and key not in keys
                keys.add(key)
                if len(keys) <= 33 + extra_success:
                    return 201, {}
            return 422, {"error": {"code": "INSUFFICIENT_FUNDS"}}
        if path == "/wallets/sender-wallet":
            assert method == "GET" and token == "test-user-1"
            return 200, {"balance_minor": 1_000}
        if path == "/wallets/receiver-wallet":
            assert method == "GET" and token == "test-user-2"
            return 200, {"balance_minor": 99_000}
        pytest.fail(f"Unexpected harness request {method} {path}")

    monkeypatch.setattr(stress, "request_json", request)
    if extra_success:
        with pytest.raises(ValueError, match="Unexpected transfer results"):
            stress.run_reference_workload(8000)
    else:
        result = stress.run_reference_workload(8000)
        assert result.outcomes == Counter(
            {(201, None): 33, (422, "INSUFFICIENT_FUNDS"): 17}
        )
        assert (result.sender_balance, result.receiver_balance) == (1_000, 99_000)
    assert registrations == 2
    assert len(keys) == 50
