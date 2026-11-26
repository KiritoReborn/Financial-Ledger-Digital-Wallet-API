"""B08 OpenAPI drift check: create_app().openapi() against docs/api/openapi.yaml.

The first test is the CI gate. The rest prove the checker catches each kind of
real divergence, ignores the approved non-semantic differences, and that the
deposit and transfer responses match the documented schemas at runtime.
"""

import copy
import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest

yaml = pytest.importorskip("yaml", reason="Install backend[dev] for contract checks.")
TestClient = pytest.importorskip("fastapi.testclient").TestClient
create_app = pytest.importorskip("app.main").create_app

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "check_openapi_drift", ROOT / "scripts" / "check_openapi_drift.py"
)
drift_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(drift_check)
Drift = drift_check.Drift

CONTRACT = drift_check.load_contract()
GENERATED = create_app().openapi()


def drift_after(change):
    """Apply change to a copy of the contract and return the drift it causes."""
    contract = copy.deepcopy(CONTRACT)
    change(contract)
    drift, _ = drift_check.find_drift(GENERATED, contract)
    baseline, _ = drift_check.find_drift(GENERATED, CONTRACT)
    return [item for item in drift if item not in baseline]


def transfer_body_schema(contract):
    return contract["components"]["schemas"]["TransferRequest"]


# CI gate


def test_app_matches_the_documented_contract():
    new, stale, _ = drift_check.check(GENERATED, CONTRACT)
    assert not new, "Undocumented API divergence:\n" + "\n".join(map(str, new))
    assert not stale, "Fixed drift still listed in KNOWN_DRIFT:\n" + "\n".join(map(str, stale))


def test_command_line_check_passes(capsys):
    assert drift_check.main() == 0
    assert "OpenAPI drift check passed." in capsys.readouterr().out


def test_deposit_and_transfer_document_key_header_and_bearer_auth():
    for path in ("/wallets/{id}/deposit", "/transfers"):
        operation = GENERATED["paths"][path]["post"]
        headers = [item for item in operation["parameters"] if item["in"] == "header"]
        assert [(item["name"], item["required"]) for item in headers] == [("Idempotency-Key", True)]
        assert operation["security"] == [{"bearerAuth": []}]


# Each kind of real divergence is caught


def test_renamed_operation_id_is_drift():
    def change(contract):
        contract["paths"]["/transfers"]["post"]["operationId"] = "sendMoney"

    assert drift_after(change) == [
        Drift("post", "/transfers", "operationId", "app 'createTransfer', contract 'sendMoney'")
    ]


def test_undocumented_operation_is_drift():
    def change(contract):
        del contract["paths"]["/transfers"]

    assert drift_after(change) == [
        Drift("post", "/transfers", "undocumented", "operation is not in the contract")
    ]


def test_status_the_contract_does_not_list_is_drift():
    def change(contract):
        del contract["paths"]["/transfers"]["post"]["responses"]["404"]

    assert drift_after(change) == [
        Drift("post", "/transfers", "responses", "undocumented status ['404']")
    ]


def test_different_success_status_is_drift():
    def change(contract):
        responses = contract["paths"]["/transfers"]["post"]["responses"]
        responses["200"] = responses.pop("201")

    assert Drift("post", "/transfers", "success", "app 201, contract 200") in drift_after(change)


def test_different_security_is_drift():
    def change(contract):
        contract["paths"]["/transfers"]["post"]["security"] = []

    assert drift_after(change) == [
        Drift("post", "/transfers", "security", "app ['bearerAuth'], contract []")
    ]


def test_missing_and_optional_parameters_are_drift():
    def add_query(contract):
        contract["paths"]["/transfers"]["post"]["parameters"].append(
            {"name": "dry_run", "in": "query", "required": False, "schema": {"type": "boolean"}}
        )

    def optional_key(contract):
        contract["components"]["parameters"]["IdempotencyKey"]["required"] = False

    assert drift_after(add_query) == [
        Drift("post", "/transfers", "parameters", "missing query 'dry_run'")
    ]
    assert Drift(
        "post", "/transfers", "parameters",
        "header 'idempotency-key' required app True, contract False",
    ) in drift_after(optional_key)


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (
            lambda body: body["properties"].pop("description"),
            "field 'description' only in the app",
        ),
        (
            lambda body: body["properties"].update(memo={"type": "string"}),
            "field 'memo' only in the contract",
        ),
        (
            lambda body: body["required"].remove("currency"),
            ("required app ['amount_minor', 'currency', 'from_wallet_id', 'to_wallet_id'], "
            "contract ['amount_minor', 'from_wallet_id', 'to_wallet_id']"),
        ),
        (
            lambda body: body.update(additionalProperties=True),
            "unknown-field policy differs",
        ),
        (
            lambda body: body["properties"]["description"].update(maxLength=100),
            ("field 'description' app {'type': 'string', 'maxLength': 200}, "
            "contract {'type': 'string', 'maxLength': 100}"),
        ),
    ],
)
def test_request_body_changes_are_drift(change, expected):
    assert drift_after(lambda contract: change(transfer_body_schema(contract))) == [
        Drift("post", "/transfers", "requestBody", expected)
    ]


def test_shared_schema_changes_reach_every_operation_that_uses_them():
    def change(contract):
        contract["components"]["schemas"]["Amount"]["maximum"] = 500
        contract["components"]["schemas"]["Currency"]["enum"] = ["INR", "USD"]

    found = {(item.path, item.detail.split(" app ")[0]) for item in drift_after(change)}
    assert found == {
        ("/transfers", "field 'amount_minor'"),
        ("/transfers", "field 'currency'"),
        ("/wallets/{id}/deposit", "field 'amount_minor'"),
        ("/wallets", "field 'currency'"),
    }


def test_wallet_id_without_the_v4_rule_is_drift():
    def change(contract):
        del contract["components"]["schemas"]["ResourceId"]["pattern"]

    details = {item.detail for item in drift_after(change) if item.path == "/transfers"}
    assert details == {
        ("field 'from_wallet_id' app {'type': 'string', 'format': 'uuid4'}, "
        "contract {'type': 'string', 'format': 'uuid'}"),
        ("field 'to_wallet_id' app {'type': 'string', 'format': 'uuid4'}, "
        "contract {'type': 'string', 'format': 'uuid'}"),
    }


# Approved, non-semantic differences are ignored


def test_wording_examples_and_tags_are_not_drift():
    def change(contract):
        operation = contract["paths"]["/transfers"]["post"]
        operation["summary"] = "Different words"
        operation["description"] = "Different words"
        operation["tags"] = ["other"]
        operation["requestBody"]["content"]["application/json"]["example"] = {}
        transfer_body_schema(contract)["properties"]["description"]["description"] = "Memo"

    assert drift_after(change) == []


def test_statuses_only_the_contract_lists_are_not_drift():
    def change(contract):
        contract["paths"]["/transfers"]["post"]["responses"]["429"] = {"description": "Slow down"}

    assert drift_after(change) == []


def test_documented_but_unbuilt_operations_are_listed_not_failed():
    drift, pending = drift_check.find_drift(GENERATED, CONTRACT)
    assert "GET /transfers/{id}" in pending
    assert all(item.path != "/transfers/{id}" for item in drift)


# KNOWN_DRIFT only shrinks


def test_known_drift_is_reported_to_an_owner():
    assert all("Member" in owner for owner in drift_check.KNOWN_DRIFT.values())
    assert all(item.path not in ("/wallets/{id}/deposit", "/transfers")
               for item in drift_check.KNOWN_DRIFT)


def test_a_fixed_entry_left_in_known_drift_fails(monkeypatch):
    fixed = Drift("get", "/health", "security", "already fixed")
    monkeypatch.setitem(drift_check.KNOWN_DRIFT, fixed, "Member C")
    _, stale, _ = drift_check.check(GENERATED, CONTRACT)
    assert stale == [fixed]
    assert drift_check.main() == 1


def test_new_drift_fails_the_command(monkeypatch, capsys):
    contract = copy.deepcopy(CONTRACT)
    contract["paths"]["/transfers"]["post"]["operationId"] = "sendMoney"
    monkeypatch.setattr(drift_check, "load_contract", lambda: contract)

    assert drift_check.main() == 1
    assert "DRIFT  POST /transfers: operationId" in capsys.readouterr().out


# Runtime: real responses match the documented schemas


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "drift.sqlite3"))
    monkeypatch.setenv("ADMIN_TOKEN", "drift-admin-token")
    monkeypatch.setenv("ADMIN_KEY", "drift-admin-key")
    with TestClient(create_app()) as client:
        yield client


def validate(instance, schema_name):
    validator_class = pytest.importorskip("openapi_schema_validator").OAS30Validator
    schema = {**CONTRACT["components"]["schemas"][schema_name], "components": CONTRACT["components"]}
    validator_class(schema).validate(instance)


def test_deposit_and_transfer_responses_match_the_contract_schemas(client):
    users = []
    for name in ("alice", "bob"):
        token = client.post("/users", json={"name": name, "email": f"{name}@example.test"})
        auth = {"Authorization": f"Bearer {token.json()['token']}"}
        wallet = client.post("/wallets", json={"currency": "INR"}, headers=auth).json()["id"]
        users.append((auth, wallet))
    (alice, alice_inr), (_, bob_inr) = users

    deposit = client.post(
        f"/wallets/{alice_inr}/deposit",
        json={"amount_minor": 500},
        headers={**alice, "Idempotency-Key": str(uuid4())},
    )
    transfer = client.post(
        "/transfers",
        json={"from_wallet_id": alice_inr, "to_wallet_id": bob_inr, "amount_minor": 200,
              "currency": "INR", "description": "Lunch"},
        headers={**alice, "Idempotency-Key": str(uuid4())},
    )

    assert (deposit.status_code, transfer.status_code) == (201, 201)
    validate(deposit.json(), "Transaction")
    validate(transfer.json(), "Transfer")


def test_documented_required_header_still_gives_400_when_missing(client):
    response = client.post(
        f"/wallets/{uuid4()}/deposit",
        json={"amount_minor": 1},
        headers={"Authorization": "Bearer unknown"},
    )
    assert response.status_code == 401
    token = client.post("/users", json={"name": "carol", "email": "carol@example.test"})
    response = client.post(
        f"/wallets/{uuid4()}/deposit",
        json={"amount_minor": 1},
        headers={"Authorization": f"Bearer {token.json()['token']}"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_MISSING"
