"""C02 contract checks. Full FastAPI drift enforcement remains B08-owned."""

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="Install backend[dev] for contract checks.")
jsonschema = pytest.importorskip("jsonschema")
create_app = pytest.importorskip("app.main").create_app
ROOT = Path(__file__).resolve().parents[2]
SPEC = yaml.safe_load((ROOT / "docs/api/openapi.yaml").read_text(encoding="utf-8"))
ID = "00000000-0000-4000-8000-000000000001"
OPERATIONS = [(path, method, operation) for path, item in SPEC["paths"].items()
              for method, operation in item.items()]


def resolve(value):
    if isinstance(value, dict):
        if "$ref" in value:
            target = SPEC
            for part in value["$ref"].removeprefix("#/").split("/"):
                target = target[part]
            return resolve(target)
        return {key: resolve(item) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve(item) for item in value]
    return value


def request_validator(name):
    return jsonschema.Draft7Validator(resolve(SPEC["components"]["schemas"][name]),
                                      format_checker=jsonschema.FormatChecker())


def test_full_openapi_document_is_valid():
    validator = pytest.importorskip("openapi_spec_validator", reason="Full validator runs in CI.")
    validator.validate(SPEC)


def test_all_final_srs_paths_and_methods_are_documented():
    expected = {
        "/health": {"get"}, "/users": {"post"}, "/wallets": {"get", "post"},
        "/wallets/{id}": {"get"}, "/wallets/{id}/deposit": {"post"},
        "/transfers": {"post"},
        "/transfers/{id}": {"get"}, "/wallets/{id}/transactions": {"get"},
        "/transactions/{id}/reverse": {"post"}, "/admin/reconcile": {"get"},
    }
    assert {path: set(item) for path, item in SPEC["paths"].items()} == expected
    assert len(OPERATIONS) == 11
    assert len({operation["operationId"] for _, _, operation in OPERATIONS}) == 11
    resolve(SPEC)


@pytest.mark.parametrize("path,method,operation", OPERATIONS)
def test_each_operation_declares_security_status_and_request_id(path, method, operation):
    assert operation["security"] == ([] if path in {"/health", "/users"} else [
        {"bearerAuth": [], "adminKey": []} if path.startswith(("/admin", "/transactions"))
        else {"bearerAuth": []}
    ])
    success = "201" if method == "post" else "200"
    assert success in operation["responses"]
    for response in operation["responses"].values():
        response = resolve(response)
        assert "X-Request-ID" in response["headers"]
        assert "application/json" in response["content"]


def test_idempotency_headers_only_belong_to_the_three_financial_writes():
    expected = {"deposit", "createTransfer", "reverseTransaction"}
    actual = set()
    for _, _, operation in OPERATIONS:
        parameters = [resolve(parameter) for parameter in operation.get("parameters", [])]
        for parameter in parameters:
            if parameter["name"] == "Idempotency-Key":
                actual.add(operation["operationId"])
                assert parameter["required"]
                assert parameter["schema"]["maxLength"] == 128
                assert "400" in operation["responses"]
        if operation["operationId"] in expected:
            assert "Idempotent-Replayed" in operation["responses"]["201"]["headers"]
    assert actual == expected


@pytest.mark.parametrize("name", ["UserRequest", "WalletRequest", "DepositRequest", "TransferRequest", "ReverseRequest"])
def test_request_objects_reject_unknown_fields(name):
    schema = SPEC["components"]["schemas"][name]
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize("value", [0, -1, 1.5, True, "100", 10**12 + 1])
def test_amount_contract_rejects_invalid_money_values(value):
    assert not request_validator("DepositRequest").is_valid({"amount_minor": value})


@pytest.mark.parametrize("value", [1, 10**12])
def test_amount_contract_accepts_valid_boundaries(value):
    assert request_validator("DepositRequest").is_valid({"amount_minor": value})


def test_transfer_id_and_currency_contract_rejects_bad_values():
    valid = {"from_wallet_id": ID, "to_wallet_id": ID, "amount_minor": 1, "currency": "INR"}
    validator = request_validator("TransferRequest")
    assert validator.is_valid(valid)
    assert not validator.is_valid({**valid, "from_wallet_id": "not-a-uuid"})
    assert not validator.is_valid({**valid, "from_wallet_id": "00000000-0000-1000-8000-000000000001"})
    assert not validator.is_valid({**valid, "currency": "EUR"})
    assert not validator.is_valid({**valid, "unknown": True})


def test_history_paging_matches_the_final_srs():
    parameters = {resolve(value)["name"]: resolve(value) for value in
                  SPEC["paths"]["/wallets/{id}/transactions"]["get"]["parameters"]}
    assert parameters["limit"]["schema"] == {
        "type": "integer", "minimum": 1, "maximum": 100, "default": 20
    }
    assert parameters["before_id"]["schema"]["minimum"] == 1
    assert "next_before_id" in SPEC["components"]["schemas"]["History"]["properties"]


def test_request_examples_pass_their_declared_schemas():
    for _, _, operation in OPERATIONS:
        if "requestBody" in operation:
            content = operation["requestBody"]["content"]["application/json"]
            schema = resolve(content["schema"])
            jsonschema.Draft7Validator(schema, format_checker=jsonschema.FormatChecker()).validate(content["example"])


def test_response_examples_pass_openapi_schemas():
    validator = pytest.importorskip("openapi_schema_validator", reason="OpenAPI schema dialect runs in CI.")
    for _, _, operation in OPERATIONS:
        for response in operation["responses"].values():
            content = resolve(response)["content"]["application/json"]
            samples = [content["example"]] if "example" in content else [
                example["value"] for example in content["examples"].values()
            ]
            for sample in samples:
                validator.OAS30Validator(content["schema"]).validate(sample)


def test_implemented_health_contract_matches_real_fastapi_behavior():
    generated = create_app().openapi()
    health = generated["paths"]["/health"]["get"]
    assert not health.get("security")
    assert {"200", "500", "503"}.issubset(health["responses"])
    schema_name = health["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].split("/")[-1]
    status = generated["components"]["schemas"][schema_name]["properties"]["status"]
    assert status.get("const") == "ok" or status.get("enum") == ["ok"]
