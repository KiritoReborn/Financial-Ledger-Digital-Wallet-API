"""B06 simulate-transfer run against the real app (FR-1.6, FR-1.7, FR-2.7, FR-2.10, FR-4.2, TQ-7).

The script runs with its client's transport routed through FastAPI's
TestClient on a fresh temporary SQLite file, so every step hits the real
routes. Failure cases check the report names the failing step and shows no
secret.
"""

import importlib.util
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

TestClient = pytest.importorskip("fastapi.testclient").TestClient
create_app = pytest.importorskip("app.main").create_app

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "simulate_transfer", ROOT / "skills" / "simulate-transfer" / "scripts" / "simulate_transfer.py"
)
simulate = importlib.util.module_from_spec(_spec)
sys.modules["simulate_transfer"] = simulate
_spec.loader.exec_module(simulate)

BASE = "http://127.0.0.1:8000"
ADMIN_TOKEN, ADMIN_KEY = "simulate-test-admin-token", "simulate-test-admin-key"


class Recorder:
    def __init__(self, http):
        self.http = http
        self.tokens = set()

    def __call__(self, method, url, headers, body):
        response = self.http.request(method, url[len(BASE):], content=body, headers=dict(headers))
        if url.endswith("/users") and response.status_code == 201:
            self.tokens.add(response.json()["token"])
        return response.status_code, response.headers, response.content


@pytest.fixture
def transport(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "simulate.sqlite3"))
    monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)
    monkeypatch.setenv("ADMIN_KEY", ADMIN_KEY)
    with TestClient(create_app()) as http:
        yield Recorder(http)


def client(transport, admin_token=ADMIN_TOKEN, admin_key=ADMIN_KEY):
    return simulate.LedgerClient(BASE, admin_token=admin_token, admin_key=admin_key,
                                 transport=transport)


def run_main(argv, ledger_client):
    out = io.StringIO()
    with redirect_stdout(out):
        code = simulate.main(argv, client=ledger_client)
    return code, out.getvalue()


def test_full_simulation_passes_all_eight_steps(transport):
    report = simulate.run_simulation(client(transport))

    assert report.passed, report.as_table()
    assert [step.name for step in report.steps] == list(simulate._STEP_NAMES)
    assert report.balances == {
        "first": {"opening": 10_000, "expected": 7_200, "final": 7_200},
        "second": {"opening": 5_000, "expected": 7_800, "final": 7_800},
    }


def test_two_runs_on_one_database_both_pass(transport):
    assert simulate.run_simulation(client(transport)).passed
    assert simulate.run_simulation(client(transport)).passed
    assert len(transport.tokens) == 4


def test_table_output_and_exit_code_hide_every_secret(transport):
    code, out = run_main([], client(transport))

    assert code == 0
    assert "**Overall:** PASS" in out
    assert out.count("| PASS |") == 8
    for secret in (*transport.tokens, ADMIN_TOKEN, ADMIN_KEY):
        assert secret not in out


def test_json_output(transport):
    code, out = run_main(["--json"], client(transport))
    report = json.loads(out)
    assert code == 0 and report["passed"] is True
    assert [step["number"] for step in report["steps"]] == list(range(1, 9))
    assert report["balances"]["second"]["final"] == 7_800


def test_missing_admin_credentials_fail_at_reconcile(transport):
    code, out = run_main([], client(transport, admin_token=None, admin_key=None))

    assert code == 1
    assert "| 7 | Reconcile | FAIL | Reconcile needs ADMIN_TOKEN and ADMIN_KEY. |" in out
    assert "**Overall:** FAIL" in out


def test_wrong_admin_key_reports_only_the_status_and_code(transport):
    report = simulate.run_simulation(client(transport, admin_key="wrong-admin-key"))

    assert not report.passed
    last = report.steps[-1]
    assert (last.number, last.name, last.passed, last.note) == (
        7, "Reconcile", False, "401 UNAUTHENTICATED"
    )
    assert "wrong-admin-key" not in report.as_table()


def test_a_replay_that_posts_again_fails_step_five(transport, monkeypatch):
    """If the server ignored the key, the second debit must be caught."""
    real_transfer = simulate.LedgerClient.transfer

    def forget_the_key(self, *args, key=None, **kwargs):
        return real_transfer(self, *args, **kwargs)

    monkeypatch.setattr(simulate.LedgerClient, "transfer", forget_the_key)
    report = simulate.run_simulation(client(transport))

    assert [step.passed for step in report.steps] == [True] * 4 + [False]
    assert report.steps[-1].note == "replay posted again or differed"


def test_unreachable_api_fails_at_health():
    def refuse(*_):
        raise simulate.ClientError("Could not reach the API: ConnectionRefusedError")

    report = simulate.run_simulation(simulate.LedgerClient(BASE, transport=refuse))
    assert [(step.number, step.name, step.passed) for step in report.steps] == [
        (1, "Health", False)
    ]
