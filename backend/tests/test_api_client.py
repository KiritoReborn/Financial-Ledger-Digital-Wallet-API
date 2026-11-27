"""B09 scripts/api_client.py against the real app (SK-6, NFR-SEC, FR-1.6, FR-1.7, FR-2.7).

The client's transport is swapped for one that sends each request through
FastAPI's TestClient, so every helper runs against the real routes and a fresh
temporary SQLite file. Secret-handling tests check that tokens never reach
URLs, bodies, exceptions, repr or command-line output.
"""

import importlib.util
import io
import json
import socket
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from uuid import UUID, uuid4

import pytest

TestClient = pytest.importorskip("fastapi.testclient").TestClient
create_app = pytest.importorskip("app.main").create_app

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("api_client", ROOT / "scripts" / "api_client.py")
api_client = importlib.util.module_from_spec(_spec)
sys.modules["api_client"] = api_client
_spec.loader.exec_module(api_client)

BASE = "http://127.0.0.1:8000"
ADMIN_TOKEN, ADMIN_KEY = "client-test-admin-token", "client-test-admin-key"


class Recorder:
    """Transport that forwards to the app and keeps every request it sent."""

    def __init__(self, http):
        self.http = http
        self.sent = []

    def __call__(self, method, url, headers, body):
        assert url.startswith(BASE)
        self.sent.append((method, url, dict(headers), body))
        response = self.http.request(method, url[len(BASE):], content=body, headers=dict(headers))
        return response.status_code, response.headers, response.content


@pytest.fixture
def transport(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "client.sqlite3"))
    monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)
    monkeypatch.setenv("ADMIN_KEY", ADMIN_KEY)
    with TestClient(create_app()) as http:
        yield Recorder(http)


@pytest.fixture
def anonymous(transport):
    return api_client.LedgerClient(BASE, transport=transport)


@pytest.fixture
def people(anonymous):
    """Alice with INR 1,000 and Bob with an empty INR wallet, each with their own client."""
    clients = {}
    for name in ("alice", "bob"):
        token = anonymous.register(name, f"{name}@example.test").body["token"]
        user = anonymous.with_token(token)
        clients[name] = (user, user.create_wallet("INR").body["id"], token)
    alice, alice_inr, _ = clients["alice"]
    alice.deposit(alice_inr, 1_000)
    return clients


def secrets(people):
    return [token for _, _, token in people.values()] + [ADMIN_TOKEN, ADMIN_KEY]


# Helpers against the real routes


def test_health_needs_no_token(anonymous):
    assert anonymous.health().body == {"status": "ok"}


def test_deposit_transfer_replay_and_reconcile(people, transport):
    alice, alice_inr, _ = people["alice"]
    _, bob_inr, _ = people["bob"]

    sent = alice.transfer(alice_inr, bob_inr, 250, "INR", description="Rent")
    again = alice.transfer(alice_inr, bob_inr, 250, "INR", description="Rent", key=sent.key)

    assert sent.status == 201 and not sent.replayed
    assert UUID(sent.key).version == 4
    assert again.replayed and again.body == sent.body
    assert alice.wallet(alice_inr).body["balance_minor"] == 750
    assert [wallet["id"] for wallet in alice.wallets().body["wallets"]] == [alice_inr]
    admin = api_client.LedgerClient(BASE, admin_token=ADMIN_TOKEN, admin_key=ADMIN_KEY,
                                    transport=transport)
    assert admin.reconcile().body["ok"] is True


def test_each_operation_gets_a_new_key_unless_one_is_passed(people):
    alice, alice_inr, _ = people["alice"]
    first, second = alice.deposit(alice_inr, 1), alice.deposit(alice_inr, 1)
    assert first.key != second.key
    assert not first.replayed and not second.replayed
    assert alice.deposit(alice_inr, 1, key="my-own-key").key == "my-own-key"


def test_deposit_result_reports_key_and_request_id(people):
    alice, alice_inr, _ = people["alice"]
    result = alice.deposit(alice_inr, 5)
    assert result.body["type"] == "DEPOSIT"
    assert UUID(result.request_id).version == 4


def test_api_errors_carry_status_code_and_request_id(people):
    alice, alice_inr, _ = people["alice"]
    _, bob_inr, _ = people["bob"]

    with pytest.raises(api_client.ApiError) as raised:
        alice.transfer(alice_inr, bob_inr, 5_000, "INR")

    error = raised.value
    assert (error.status, error.code) == (422, "INSUFFICIENT_FUNDS")
    assert UUID(error.request_id).version == 4
    assert str(error) == "422 INSUFFICIENT_FUNDS: Balance is too low."


def test_reused_key_with_another_body_raises_conflict(people):
    alice, alice_inr, _ = people["alice"]
    alice.deposit(alice_inr, 10, key="once")
    with pytest.raises(api_client.ApiError) as raised:
        alice.deposit(alice_inr, 11, key="once")
    assert raised.value.code == "IDEMPOTENCY_CONFLICT"


# Refusals happen before anything is sent


def test_calls_that_need_a_token_refuse_without_one(anonymous, transport):
    for call in (lambda: anonymous.wallets(), lambda: anonymous.deposit(uuid4(), 1)):
        with pytest.raises(api_client.ClientError, match="LEDGER_TOKEN"):
            call()
    with pytest.raises(api_client.ClientError, match="ADMIN_TOKEN and ADMIN_KEY"):
        api_client.LedgerClient(BASE, admin_token="only-token", transport=transport).reconcile()
    assert transport.sent == []


@pytest.mark.parametrize("bad", ["not-a-uuid", "", "../admin"])
def test_malformed_wallet_ids_are_refused_locally(people, transport, bad):
    alice, alice_inr, _ = people["alice"]
    before = len(transport.sent)
    with pytest.raises(api_client.ClientError, match="must be a UUID"):
        alice.transfer(alice_inr, bad, 1, "INR")
    with pytest.raises(api_client.ClientError, match="must be a UUID"):
        alice.deposit(bad, 1)
    assert len(transport.sent) == before


@pytest.mark.parametrize(
    "url",
    [
        "http://ledger.example.org",
        "ftp://127.0.0.1",
        "file:///etc/passwd",
        "http://user:pass@127.0.0.1:8000",
        "http://127.0.0.1:8000/?token=x",
        "127.0.0.1:8000",
    ],
)
def test_unsafe_base_urls_are_refused(url):
    with pytest.raises(api_client.ClientError):
        api_client.LedgerClient(url)


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1:8000", "http://localhost:8000/", "http://[::1]:8000",
     "https://ledger.example.org"],
)
def test_https_and_local_http_are_allowed(url):
    assert api_client.LedgerClient(url).base_url == url.rstrip("/")


def test_unreachable_api_is_a_client_error_without_secrets():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    client = api_client.LedgerClient(
        f"http://127.0.0.1:{port}", token="unreachable-secret",
        transport=api_client.urllib_transport(timeout=2),
    )
    with pytest.raises(api_client.ClientError) as raised:
        client.wallets()
    assert "unreachable-secret" not in str(raised.value)


def test_non_json_response_is_a_client_error():
    client = api_client.LedgerClient(BASE, transport=lambda *_: (502, {}, b"<html>bad gateway"))
    with pytest.raises(api_client.ClientError, match="non-JSON with status 502"):
        client.health()


# Secrets stay out of URLs, bodies, exceptions and repr


def test_tokens_travel_only_in_the_authorization_header(people, transport):
    alice, alice_inr, _ = people["alice"]
    _, bob_inr, _ = people["bob"]
    alice.transfer(alice_inr, bob_inr, 10, "INR")

    assert len(transport.sent) == 6  # Two registrations, two wallets, a deposit, a transfer.
    for _, url, headers, body in transport.sent:
        others = {name: value for name, value in headers.items() if name != "Authorization"}
        for secret in secrets(people):
            assert secret not in url
            assert secret.encode() not in (body or b"")
            assert secret not in json.dumps(others)


def test_repr_and_errors_hide_secrets(people):
    alice, alice_inr, token = people["alice"]
    client = api_client.LedgerClient(BASE, token=token, admin_token=ADMIN_TOKEN,
                                     admin_key=ADMIN_KEY, transport=alice.transport)
    assert repr(client) == (
        "LedgerClient(base_url='http://127.0.0.1:8000', token=<set>, "
        "admin_token=<set>, admin_key=<set>)"
    )
    with pytest.raises(api_client.ApiError) as raised:
        client.deposit(alice_inr, 0)
    rendered = repr(raised.value) + str(raised.value) + json.dumps(raised.value.details)
    assert all(secret not in rendered for secret in secrets(people))


def test_from_env_reads_variables_and_ignores_blanks():
    client = api_client.LedgerClient.from_env(
        {"API_BASE_URL": "https://ledger.example.org", "LEDGER_TOKEN": "t",
         "ADMIN_TOKEN": "", "ADMIN_KEY": "k"}
    )
    assert (client.base_url, client.token, client.admin_token, client.admin_key) == (
        "https://ledger.example.org", "t", None, "k"
    )
    assert api_client.LedgerClient.from_env({}).base_url == api_client.DEFAULT_BASE_URL


# Command line


def run(argv, client):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = api_client.main(argv, client=client)
    return code, out.getvalue(), err.getvalue()


def test_cli_register_writes_the_token_to_a_file_and_never_prints_it(anonymous, tmp_path):
    token_file = tmp_path / "alice.token"
    code, out, err = run(["register", "Alice", "alice@example.test", "--token-file",
                          str(token_file)], anonymous)

    token = token_file.read_text(encoding="utf-8")
    assert code == 0 and token
    assert token not in out + err
    assert json.loads(out)["body"]["token"] == f"<written to {token_file}>"
    assert anonymous.with_token(token).wallets().body == {"wallets": []}


def test_cli_register_refuses_to_overwrite_a_token_file(anonymous, tmp_path, transport):
    token_file = tmp_path / "existing.token"
    token_file.write_text("keep me", encoding="utf-8")
    code, _, err = run(["register", "A", "a@example.test", "--token-file", str(token_file)],
                       anonymous)
    assert code == 2 and "already exists" in err
    assert token_file.read_text(encoding="utf-8") == "keep me"
    assert transport.sent == []


def test_cli_deposit_and_transfer_print_the_key_and_replay_flag(people):
    alice, alice_inr, token = people["alice"]
    _, bob_inr, _ = people["bob"]

    code, out, _ = run(["deposit", alice_inr, "200", "--key", "cli-deposit"], alice)
    assert code == 0
    assert json.loads(out)["idempotency_key"] == "cli-deposit"
    code, out, err = run(["transfer", alice_inr, bob_inr, "50", "INR", "--description", "Tea"],
                         alice)
    printed = json.loads(out)
    assert code == 0 and printed["status"] == 201 and printed["replayed"] is False
    assert UUID(printed["idempotency_key"]).version == 4
    assert token not in out + err

    code, out, _ = run(["deposit", alice_inr, "200", "--key", "cli-deposit"], alice)
    assert json.loads(out)["replayed"] is True


def test_cli_errors_go_to_stderr_without_secrets(people):
    alice, alice_inr, token = people["alice"]
    _, bob_inr, _ = people["bob"]
    code, out, err = run(["transfer", alice_inr, bob_inr, "999999", "INR"], alice)
    assert code == 1 and out == ""
    assert json.loads(err)["code"] == "INSUFFICIENT_FUNDS"
    assert token not in err


def test_cli_reconcile_and_wallets(people, transport):
    alice, _, _ = people["alice"]
    admin = api_client.LedgerClient(BASE, admin_token=ADMIN_TOKEN, admin_key=ADMIN_KEY,
                                    transport=transport)
    code, out, _ = run(["reconcile"], admin)
    assert code == 0 and json.loads(out)["body"]["ok"] is True
    assert ADMIN_TOKEN not in out and ADMIN_KEY not in out
    code, out, _ = run(["wallets"], alice)
    assert len(json.loads(out)["body"]["wallets"]) == 1
