"""B06 simulate-transfer: one end-to-end run of deposits, transfers, a replay and reconcile.

Steps (each recorded PASS or FAIL):

 1. GET /health
 2. Register two fresh users and give each an INR wallet
 3. Deposit opening balances and read them back
 4. Transfer from the first user to the second with an Idempotency-Key
 5. Send the same transfer again with the same key: it must replay, not post
 6. Two concurrent transfers, one in each direction, with different keys
 7. GET /admin/reconcile must report ok
 8. Final balances must equal opening balances plus the net of what moved

Configuration comes from the environment through scripts/api_client.py:
API_BASE_URL, plus ADMIN_TOKEN and ADMIN_KEY for step 7. The two users' tokens
live only in memory. Nothing secret is ever printed.

Usage: python skills/simulate-transfer/scripts/simulate_transfer.py [--json]
Exit code 0 when every step passes, 1 otherwise.
"""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from api_client import ApiError, ClientError, LedgerClient

CURRENCY = "INR"
OPENING = {"first": 10_000, "second": 5_000}
TRANSFER = 1_500
CONCURRENT = {"first": 2_000, "second": 700}  # Each user sends this much at the same moment.


@dataclass
class Step:
    number: int
    name: str
    passed: bool
    note: str


@dataclass
class Report:
    steps: list[Step] = field(default_factory=list)
    balances: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return len(self.steps) == 8 and all(step.passed for step in self.steps)

    def add(self, name: str, passed: bool, note: str) -> bool:
        self.steps.append(Step(len(self.steps) + 1, name, passed, note))
        return passed

    def as_dict(self) -> dict:
        return {
            "passed": self.passed,
            "steps": [step.__dict__ for step in self.steps],
            "balances": self.balances,
        }

    def as_table(self) -> str:
        lines = ["| Step | Check | Result | Notes |", "| --- | --- | --- | --- |"]
        lines += [
            f"| {step.number} | {step.name} | {'PASS' if step.passed else 'FAIL'} | {step.note} |"
            for step in self.steps
        ]
        if self.balances:
            lines += ["", "| User | Opening | Expected | Final |", "| --- | --- | --- | --- |"]
            lines += [
                f"| {user} | {row['opening']} | {row['expected']} | {row.get('final', '?')} |"
                for user, row in self.balances.items()
            ]
        lines += ["", f"**Overall:** {'PASS' if self.passed else 'FAIL'}"]
        return "\n".join(lines)


def _failure(error: Exception) -> str:
    if isinstance(error, ApiError):
        return f"{error.status} {error.code}"
    return str(error)


def run_simulation(client: LedgerClient) -> Report:
    """Run all steps; stop at the first failure, since later steps depend on earlier ones."""
    report = Report()
    users: dict[str, tuple[LedgerClient, str]] = {}
    run = uuid4().hex[:8]
    try:
        health = client.health()
        if not report.add("Health", health.body == {"status": "ok"}, f"HTTP {health.status}"):
            return report

        for user in ("first", "second"):
            token = client.register(
                f"Simulated {user} {run}", f"sim-{user}-{run}@example.test"
            ).body["token"]
            user_client = client.with_token(token)
            users[user] = (user_client, user_client.create_wallet(CURRENCY).body["id"])
        report.add("Two users with INR wallets", True, f"run {run}")

        opening = {}
        for user, (user_client, wallet) in users.items():
            user_client.deposit(wallet, OPENING[user])
            opening[user] = user_client.wallet(wallet).body["balance_minor"]
        if not report.add("Opening deposits", opening == OPENING,
                          ", ".join(f"{user} {amount}" for user, amount in opening.items())):
            return report

        (first, first_wallet), (second, second_wallet) = users["first"], users["second"]
        sent = first.transfer(first_wallet, second_wallet, TRANSFER, CURRENCY,
                              description="simulate-transfer")
        if not report.add("Transfer with a key", sent.status == 201 and not sent.replayed,
                          f"{TRANSFER} moved, Idempotent-Replayed false"):
            return report

        replay = first.transfer(first_wallet, second_wallet, TRANSFER, CURRENCY,
                                description="simulate-transfer", key=sent.key)
        after_replay = first.wallet(first_wallet).body["balance_minor"]
        replay_ok = (replay.replayed and replay.body == sent.body
                     and after_replay == OPENING["first"] - TRANSFER)
        if not report.add("Replay with the same key", replay_ok,
                          "same transfer returned, no second debit" if replay_ok
                          else "replay posted again or differed"):
            return report

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda call: call(), [
                lambda: first.transfer(first_wallet, second_wallet, CONCURRENT["first"], CURRENCY),
                lambda: second.transfer(second_wallet, first_wallet, CONCURRENT["second"],
                                        CURRENCY),
            ]))
        concurrent_ok = all(result.status == 201 and not result.replayed for result in results)
        if not report.add("Two concurrent transfers", concurrent_ok,
                          f"{CONCURRENT['first']} and {CONCURRENT['second']} in opposite "
                          "directions"):
            return report

        admin = client.reconcile()
        if not report.add("Reconcile", admin.body.get("ok") is True,
                          "ok" if admin.body.get("ok") else "mismatches reported"):
            return report

        net = TRANSFER + CONCURRENT["first"] - CONCURRENT["second"]
        expected = {"first": OPENING["first"] - net, "second": OPENING["second"] + net}
        final = {
            user: user_client.wallet(wallet).body["balance_minor"]
            for user, (user_client, wallet) in users.items()
        }
        report.balances = {
            user: {"opening": OPENING[user], "expected": expected[user], "final": final[user]}
            for user in users
        }
        report.add("Final balances", final == expected,
                   "match the transfers" if final == expected else "differ from expected")
    except (ApiError, ClientError) as error:
        report.add(_next_step_name(report), False, _failure(error))
    return report


_STEP_NAMES = (
    "Health", "Two users with INR wallets", "Opening deposits", "Transfer with a key",
    "Replay with the same key", "Two concurrent transfers", "Reconcile", "Final balances",
)


def _next_step_name(report: Report) -> str:
    return _STEP_NAMES[min(len(report.steps), len(_STEP_NAMES) - 1)]


def main(argv=None, client: LedgerClient | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the simulate-transfer skill once.")
    parser.add_argument("--json", action="store_true", help="Print the report as JSON.")
    args = parser.parse_args(argv)
    try:
        client = client or LedgerClient.from_env()
    except ClientError as error:
        print(str(error), file=sys.stderr)
        return 1
    report = run_simulation(client)
    print(json.dumps(report.as_dict(), indent=2) if args.json else report.as_table())
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
