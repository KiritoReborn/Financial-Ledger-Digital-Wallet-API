"""B08 OpenAPI drift check: the running app against docs/api/openapi.yaml.

Compares every operation FastAPI generates from create_app() with the
documented contract and reports real divergence:

- an implemented operation that is not documented
- a different operationId or success status
- a status code the app declares but the contract does not
- different security schemes
- missing or extra path, query or header parameters, or a different required flag
- a request body whose fields, required fields, unknown-field policy, types,
  enums or limits differ

Approved, non-semantic differences are ignored on purpose:

- titles, summaries, descriptions, examples and tags
- FastAPI's generated 422 schema; the contract's shared error responses
- statuses the contract lists but FastAPI cannot see because middleware or
  shared handlers return them (for example 401, 413, 500 and 503)
- response headers and success response bodies, which contract and endpoint
  tests check at runtime
- `anyOf: [X, null]` for an optional field or body, `1.0` versus `1`
- Pydantic's `uuid4` format versus the contract's `uuid` plus the v4 pattern
- documented operations that are not implemented yet (listed, not failed)

KNOWN_DRIFT holds divergence that is already reported to its owner. The check
fails on any new drift, and also on a known entry that no longer occurs, so the
list only shrinks.

Usage: python scripts/check_openapi_drift.py
"""

import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "docs" / "api" / "openapi.yaml"
METHODS = ("get", "post", "put", "patch", "delete")
SCHEMA_KEYS = ("type", "enum", "minimum", "maximum", "minLength", "maxLength", "pattern")
UUID4_PATTERN = (
    "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)


@dataclass(frozen=True, order=True)
class Drift:
    method: str
    path: str
    kind: str
    detail: str

    def __str__(self) -> str:
        return f"{self.method.upper()} {self.path}: {self.kind}: {self.detail}"


# Reported to each owner; remove an entry when its fix lands.
KNOWN_DRIFT = {
    Drift("get", "/health", "operationId", "app 'health_health_get', contract 'health'"):
        "api/health.py, Member C",
    Drift("get", "/admin/reconcile", "operationId",
          "app 'reconcile_ledger_admin_reconcile_get', contract 'reconcile'"):
        "api/admin.py, Member D",
    Drift("get", "/admin/reconcile", "security", "app [], contract ['adminKey', 'bearerAuth']"):
        "api/admin.py, Member D",
    Drift("post", "/transactions/{id}/reverse", "security",
          "app [], contract ['adminKey', 'bearerAuth']"):
        "api/admin.py, Member D",
    Drift("post", "/transactions/{id}/reverse", "parameters",
          "missing header 'idempotency-key'"):
        "api/admin.py, Member D",
}


def load_contract(path: Path = SPEC_PATH) -> dict:
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8"))


def generated_contract() -> dict:
    sys.path.insert(0, str(ROOT / "backend"))
    from app.main import create_app

    return create_app().openapi()


def _resolve(document: dict, node):
    while isinstance(node, dict) and "$ref" in node:
        target = document
        for part in node["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        node = target
    return node


def _without_null(document: dict, schema) -> dict:
    """Unwrap FastAPI's `anyOf: [X, null]` for an optional field or body."""
    schema = _resolve(document, schema) or {}
    options = schema.get("anyOf")
    if options:
        non_null = [option for option in options if option.get("type") != "null"]
        if len(non_null) == 1:
            rest = {key: value for key, value in schema.items() if key != "anyOf"}
            schema = {**rest, **_resolve(document, non_null[0])}
    return schema


def _normalize_schema(document: dict, schema) -> dict:
    """Reduce a property schema to the fields that change what a request may contain."""
    schema = _without_null(document, schema)
    normalized = {}
    for key in SCHEMA_KEYS:
        if key in schema:
            value = schema[key]
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            normalized[key] = value
    # Pydantic's UUID4 checks the version at runtime; the contract spells it as a pattern.
    if schema.get("format") == "uuid4" or (
        schema.get("format") == "uuid" and normalized.get("pattern") == UUID4_PATTERN
    ):
        normalized.pop("pattern", None)
        normalized["format"] = "uuid4"
    elif schema.get("format") == "uuid":
        normalized["format"] = "uuid"
    return normalized


def _parameters(document: dict, operation: dict) -> dict[tuple[str, str], bool]:
    found = {}
    for parameter in operation.get("parameters", []):
        parameter = _resolve(document, parameter)
        name = parameter["name"].lower() if parameter["in"] == "header" else parameter["name"]
        found[(parameter["in"], name)] = bool(parameter.get("required", False))
    return found


def _body_schema(document: dict, operation: dict) -> dict | None:
    body = _resolve(document, operation.get("requestBody"))
    if not body:
        return None
    schema = body.get("content", {}).get("application/json", {}).get("schema")
    return _without_null(document, schema)


def _compare_bodies(method, path, app, app_doc, contract, contract_doc) -> list[Drift]:
    drift = []
    if (app is None) != (contract is None):
        side = "app" if app is not None else "contract"
        return [Drift(method, path, "requestBody", f"only the {side} has a JSON body")]
    if app is None:
        return []
    app_fields, contract_fields = app.get("properties", {}), contract.get("properties", {})
    for name in sorted(set(app_fields) ^ set(contract_fields)):
        side = "app" if name in app_fields else "contract"
        drift.append(Drift(method, path, "requestBody", f"field '{name}' only in the {side}"))
    if set(app.get("required", [])) != set(contract.get("required", [])):
        drift.append(Drift(
            method, path, "requestBody",
            f"required app {sorted(app.get('required', []))}, "
            f"contract {sorted(contract.get('required', []))}",
        ))
    if app.get("additionalProperties") is not contract.get("additionalProperties"):
        drift.append(Drift(method, path, "requestBody", "unknown-field policy differs"))
    for name in sorted(set(app_fields) & set(contract_fields)):
        mine = _normalize_schema(app_doc, app_fields[name])
        theirs = _normalize_schema(contract_doc, contract_fields[name])
        if mine != theirs:
            drift.append(Drift(
                method, path, "requestBody", f"field '{name}' app {mine}, contract {theirs}"
            ))
    return drift


def _success(operation: dict) -> str | None:
    codes = sorted(code for code in operation.get("responses", {}) if code.startswith("2"))
    return codes[0] if codes else None


def find_drift(app_doc: dict, contract_doc: dict) -> tuple[list[Drift], list[str]]:
    """Return (divergence, documented operations not implemented yet)."""
    drift: list[Drift] = []
    for path, operations in sorted(app_doc.get("paths", {}).items()):
        for method in METHODS:
            app = operations.get(method)
            if app is None:
                continue
            contract = contract_doc.get("paths", {}).get(path, {}).get(method)
            if contract is None:
                drift.append(Drift(method, path, "undocumented", "operation is not in the contract"))
                continue
            if app.get("operationId") != contract.get("operationId"):
                drift.append(Drift(
                    method, path, "operationId",
                    f"app '{app.get('operationId')}', contract '{contract.get('operationId')}'",
                ))
            if _success(app) != _success(contract):
                drift.append(Drift(
                    method, path, "success",
                    f"app {_success(app)}, contract {_success(contract)}",
                ))
            extra = sorted(set(app.get("responses", {})) - set(contract.get("responses", {})))
            if extra:
                drift.append(Drift(method, path, "responses", f"undocumented status {extra}"))
            app_security = sorted({name for item in app.get("security", []) for name in item})
            contract_security = sorted(
                {name for item in contract.get("security", []) for name in item}
            )
            if app_security != contract_security:
                drift.append(Drift(
                    method, path, "security", f"app {app_security}, contract {contract_security}"
                ))
            mine, theirs = _parameters(app_doc, app), _parameters(contract_doc, contract)
            for location, name in sorted(set(theirs) - set(mine)):
                drift.append(Drift(method, path, "parameters", f"missing {location} '{name}'"))
            for location, name in sorted(set(mine) - set(theirs)):
                drift.append(Drift(method, path, "parameters", f"extra {location} '{name}'"))
            for key in sorted(set(mine) & set(theirs)):
                if mine[key] != theirs[key]:
                    drift.append(Drift(
                        method, path, "parameters",
                        f"{key[0]} '{key[1]}' required app {mine[key]}, contract {theirs[key]}",
                    ))
            drift += _compare_bodies(
                method, path, _body_schema(app_doc, app), app_doc,
                _body_schema(contract_doc, contract), contract_doc,
            )
    pending = sorted(
        f"{method.upper()} {path}"
        for path, operations in contract_doc.get("paths", {}).items()
        for method in METHODS
        if method in operations and method not in app_doc.get("paths", {}).get(path, {})
    )
    return sorted(drift), pending


def check(app_doc: dict, contract_doc: dict) -> tuple[list[Drift], list[Drift], list[str]]:
    """Return (new drift, known entries that no longer occur, pending operations)."""
    drift, pending = find_drift(app_doc, contract_doc)
    new = [item for item in drift if item not in KNOWN_DRIFT]
    stale = sorted(item for item in KNOWN_DRIFT if item not in drift)
    return new, stale, pending


def main() -> int:
    new, stale, pending = check(generated_contract(), load_contract())
    for item in sorted(KNOWN_DRIFT):
        if item not in stale:
            print(f"known  {item}  ({KNOWN_DRIFT[item]})")
    for operation in pending:
        print(f"todo   {operation}: documented, not implemented yet")
    for item in new:
        print(f"DRIFT  {item}")
    for item in stale:
        print(f"FIXED  {item}: remove it from KNOWN_DRIFT")
    if new or stale:
        return 1
    print("OpenAPI drift check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
