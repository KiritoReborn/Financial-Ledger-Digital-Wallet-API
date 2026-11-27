"""B09 secure client for the ledger API: deposits, transfers and the calls around them.

Configuration comes from the environment only:

    API_BASE_URL   for example http://127.0.0.1:8000 (default)
    LEDGER_TOKEN   bearer token of the user making deposits and transfers
    ADMIN_TOKEN    admin bearer token, only for reconcile
    ADMIN_KEY      admin X-Admin-Key, only for reconcile

Secrets are never printed, logged, put in URLs or included in exceptions, and
the client's repr hides them. Tokens are only sent over HTTPS, or over plain
HTTP to this machine (localhost, 127.0.0.1, ::1).

Every deposit and transfer carries an Idempotency-Key. A new UUID v4 key is
generated unless one is passed, and the key is returned with the result. After
a timeout or a 5xx, send the same request again with the same key: the server
then replays the stored response instead of moving money twice. The client
never retries on its own.

Library use:

    from api_client import LedgerClient
    client = LedgerClient.from_env()
    result = client.transfer(source, target, 100, "INR")
    result.body["id"], result.key, result.replayed

Command line (prints response bodies as JSON, never secrets):

    python scripts/api_client.py health
    python scripts/api_client.py register NAME EMAIL --token-file PATH
    python scripts/api_client.py create-wallet INR
    python scripts/api_client.py wallets
    python scripts/api_client.py deposit WALLET_ID 2500 [--key KEY]
    python scripts/api_client.py transfer FROM_ID TO_ID 100 INR [--description TEXT] [--key KEY]
    python scripts/api_client.py reconcile
"""

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

# (method, url, headers, body) -> (status, headers, body). Swappable for tests.
Transport = Callable[[str, str, Mapping[str, str], bytes | None], tuple[int, Mapping[str, str], bytes]]


class ClientError(Exception):
    """A request the client refused to send, or a response it could not read."""


class ApiError(Exception):
    """The API answered with its error envelope. Never contains secrets."""

    def __init__(self, status: int, code: str, message: str, details=None, request_id=None):
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message
        self.details = details
        self.request_id = request_id


@dataclass(frozen=True)
class Result:
    """A successful response; `key` is the Idempotency-Key used, if any."""

    status: int
    body: dict
    request_id: str | None = None
    key: str | None = None
    replayed: bool = False


def urllib_transport(timeout: float = 10.0) -> Transport:
    def send(method, url, headers, body):
        request = Request(url, data=body, headers=dict(headers), method=method)
        try:
            # _check_base_url allows only http(s), so urlopen cannot reach file: or other schemes.
            with urlopen(request, timeout=timeout) as response:
                return response.status, dict(response.headers), response.read()
        except HTTPError as error:
            with error:
                return error.code, dict(error.headers), error.read()
        except (URLError, TimeoutError, OSError) as error:
            # The reason never includes headers, so no secret can leak here.
            raise ClientError(f"Could not reach the API: {type(error).__name__}") from None

    return send


def _check_base_url(base_url: str) -> str:
    parts = urlsplit(base_url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ClientError("API_BASE_URL must be an http or https URL.")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ClientError("API_BASE_URL must not contain credentials, a query or a fragment.")
    if parts.scheme == "http" and parts.hostname not in LOCAL_HOSTS:
        raise ClientError("Plain HTTP is only allowed to localhost; use https for other hosts.")
    return base_url.rstrip("/")


def _key(key: str | None) -> str:
    return str(uuid4()) if key is None else key


def _uuid(value, name: str) -> str:
    try:
        return str(UUID(str(value)))
    except ValueError:
        raise ClientError(f"{name} must be a UUID.") from None


@dataclass(repr=False)
class LedgerClient:
    base_url: str = DEFAULT_BASE_URL
    token: str | None = field(default=None)
    admin_token: str | None = field(default=None)
    admin_key: str | None = field(default=None)
    transport: Transport = field(default_factory=urllib_transport)

    def __post_init__(self):
        self.base_url = _check_base_url(self.base_url)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None, **kwargs) -> "LedgerClient":
        environ = os.environ if environ is None else environ
        return cls(
            base_url=environ.get("API_BASE_URL") or DEFAULT_BASE_URL,
            token=environ.get("LEDGER_TOKEN") or None,
            admin_token=environ.get("ADMIN_TOKEN") or None,
            admin_key=environ.get("ADMIN_KEY") or None,
            **kwargs,
        )

    def __repr__(self) -> str:
        def shown(value):
            return "<set>" if value else None

        return (
            f"LedgerClient(base_url={self.base_url!r}, token={shown(self.token)}, "
            f"admin_token={shown(self.admin_token)}, admin_key={shown(self.admin_key)})"
        )

    def with_token(self, token: str) -> "LedgerClient":
        """A client for another user, sharing this one's URL and transport."""
        return LedgerClient(self.base_url, token, self.admin_token, self.admin_key, self.transport)

    # Requests

    def _send(self, method, path, *, body=None, auth=False, key=None, admin=False) -> Result:
        """Send one request. auth=True sends LEDGER_TOKEN; admin=True sends the admin pair."""
        headers = {"Accept": "application/json"}
        if admin:
            if not self.admin_token or not self.admin_key:
                raise ClientError("Reconcile needs ADMIN_TOKEN and ADMIN_KEY.")
            headers["Authorization"] = f"Bearer {self.admin_token}"
            headers["X-Admin-Key"] = self.admin_key
        elif auth:
            if not self.token:
                raise ClientError("This call needs LEDGER_TOKEN.")
            headers["Authorization"] = f"Bearer {self.token}"
        if key is not None:
            headers["Idempotency-Key"] = key
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")

        status, response_headers, raw = self.transport(method, self.base_url + path, headers, data)
        response_headers = {name.lower(): value for name, value in response_headers.items()}
        request_id = response_headers.get("x-request-id")
        try:
            payload = json.loads(raw) if raw else {}
        except ValueError:
            raise ClientError(f"The API returned non-JSON with status {status}.") from None
        if status >= 400:
            error = payload.get("error", {}) if isinstance(payload, dict) else {}
            raise ApiError(
                status,
                error.get("code", "UNKNOWN"),
                error.get("message", "The API returned an error."),
                error.get("details"),
                request_id,
            )
        return Result(
            status=status,
            body=payload,
            request_id=request_id,
            key=key,
            replayed=response_headers.get("idempotent-replayed") == "true",
        )

    def health(self) -> Result:
        return self._send("GET", "/health")

    def register(self, name: str, email: str) -> Result:
        """Create a user. The body holds the new token: store it, never print it."""
        return self._send("POST", "/users", body={"name": name, "email": email})

    def create_wallet(self, currency: str) -> Result:
        return self._send("POST", "/wallets", body={"currency": currency}, auth=True)

    def wallets(self) -> Result:
        return self._send("GET", "/wallets", auth=True)

    def wallet(self, wallet_id) -> Result:
        return self._send("GET", f"/wallets/{_uuid(wallet_id, 'wallet_id')}", auth=True)

    def deposit(self, wallet_id, amount_minor: int, *, key: str | None = None) -> Result:
        path = f"/wallets/{_uuid(wallet_id, 'wallet_id')}/deposit"
        return self._send(
            "POST", path, body={"amount_minor": amount_minor}, auth=True, key=_key(key)
        )

    def transfer(
        self,
        from_wallet_id,
        to_wallet_id,
        amount_minor: int,
        currency: str,
        *,
        description: str | None = None,
        key: str | None = None,
    ) -> Result:
        body = {
            "from_wallet_id": _uuid(from_wallet_id, "from_wallet_id"),
            "to_wallet_id": _uuid(to_wallet_id, "to_wallet_id"),
            "amount_minor": amount_minor,
            "currency": currency,
        }
        if description is not None:
            body["description"] = description
        return self._send("POST", "/transfers", body=body, auth=True, key=_key(key))

    def reconcile(self) -> Result:
        return self._send("GET", "/admin/reconcile", admin=True)


# Command line


def _write_token(path: Path, token: str) -> None:
    """Write the token to a new file readable only by the current user."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(token)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("health")
    register = commands.add_parser("register")
    register.add_argument("name")
    register.add_argument("email")
    register.add_argument("--token-file", required=True, type=Path,
                          help="New file to receive the token; it is never printed.")
    commands.add_parser("create-wallet").add_argument("currency")
    commands.add_parser("wallets")
    deposit = commands.add_parser("deposit")
    deposit.add_argument("wallet_id")
    deposit.add_argument("amount_minor", type=int)
    deposit.add_argument("--key")
    transfer = commands.add_parser("transfer")
    transfer.add_argument("from_wallet_id")
    transfer.add_argument("to_wallet_id")
    transfer.add_argument("amount_minor", type=int)
    transfer.add_argument("currency")
    transfer.add_argument("--description")
    transfer.add_argument("--key")
    commands.add_parser("reconcile")
    return parser


def main(argv=None, environ=None, client: LedgerClient | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        client = client or LedgerClient.from_env(environ)
        if args.command == "register":
            if args.token_file.exists():
                raise ClientError("The token file already exists; choose a new path.")
            result = client.register(args.name, args.email)
            _write_token(args.token_file, result.body.pop("token"))
            result.body["token"] = f"<written to {args.token_file}>"
        elif args.command == "deposit":
            result = client.deposit(args.wallet_id, args.amount_minor, key=args.key)
        elif args.command == "transfer":
            result = client.transfer(
                args.from_wallet_id, args.to_wallet_id, args.amount_minor, args.currency,
                description=args.description, key=args.key,
            )
        elif args.command == "create-wallet":
            result = client.create_wallet(args.currency)
        else:
            result = {"health": client.health, "wallets": client.wallets,
                      "reconcile": client.reconcile}[args.command]()
    except ApiError as error:
        print(json.dumps({"status": error.status, "code": error.code, "message": error.message,
                          "request_id": error.request_id}), file=sys.stderr)
        return 1
    except ClientError as error:
        print(str(error), file=sys.stderr)
        return 2
    output = {"status": result.status, "body": result.body}
    if result.key is not None:
        output["idempotency_key"] = result.key
        output["replayed"] = result.replayed
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
