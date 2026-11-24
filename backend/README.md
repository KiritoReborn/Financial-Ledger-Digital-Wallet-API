# Backend setup and database transactions

The API exposes `GET /health` and `GET /admin/reconcile`. SQLite initialization runs during application startup.

## Install and run

Use Python 3.11. From the repository root:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
$env:DATABASE_PATH = "C:\path\to\ledger.sqlite3"
$env:FRONTEND_ORIGIN = "http://localhost:5173"
.\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

`DATABASE_PATH` defaults to `data/ledger.sqlite3`. On first startup, the app creates the parent directory, enables WAL and applies the numbered migrations. On restart it preserves recorded versions. An unreadable or corrupt database stops startup. The package built from the repository root includes the shared migration runner and SQL under `db/` on Windows and Linux.

`GET /health` reads the SQLite catalog in one read-only transaction. After startup an unreadable database yields a sanitized 500 response, and an expired SQLite busy timeout yields 503.

## Financial request handlers

In a synchronous request handler, open `with request.app.state.database.transaction() as conn:` once and pass `conn` to each service. The context reserves the write lock before yielding, commits on success, rolls back on an exception and closes the connection. For read-only handlers use `transaction(write=False)` to keep all reads on the same snapshot. Each connection uses foreign keys, FULL synchronization and a five-second busy timeout.

## Checks

```powershell
.\.venv\Scripts\python.exe -m pytest -q backend/tests tests
.\.venv\Scripts\python.exe -m ruff check backend
.\.venv\Scripts\python.exe -m build --outdir .venv/dist
```

## Frontend origin (C01 / EI-CM-1)

`FRONTEND_ORIGIN` allows exactly one frontend origin: scheme, hostname, and port.
It defaults to `http://localhost:5173` for local Vite development. Set it to the
frontend's actual origin before starting the API. Do not include a trailing
slash, path, query, credentials, a comma-separated list, `null`, or a wildcard;
invalid configuration fails at application creation.

The API enables CORS for GET and POST with the documented Authorization,
Content-Type, Idempotency-Key, X-Admin-Key and X-Request-ID request headers.
Browser JavaScript can read Idempotent-Replayed and X-Request-ID response
headers when the corresponding features produce them.

Allowed origins receive an explicit Access-Control-Allow-Origin header;
other origins receive no such browser-access permission. Disallowed preflight
origins, methods and headers receive HTTP 400. Non-browser requests without an
Origin header continue to work. Cookie credentials are not enabled; frontend
authentication will use the documented bearer header. CORS does not replace
the later authentication and ownership checks.

## Request boundaries (C01)

Every HTTP response, including preflight and errors, gets a new server-generated
UUID v4 X-Request-ID. Incoming IDs are replaced. Handlers can read the value
from request.state.request_id. The request logger writes one JSON line with the
ID, method, route template, status and elapsed milliseconds. It omits raw URL
parameters, unknown path values, headers, bodies and exception messages. Use
the documented --no-access-log option to avoid a second raw-URL server log.

Expected service failures may raise app.http.ApiError with a fixed message and
non-sensitive details. Framework 404/405 and validation errors use the shared
JSON error envelope. Validation details contain only locations and error types;
internal errors contain only INTERNAL_ERROR and a generic message. Unexpected
SQLite busy errors return DATABASE_BUSY without an application retry loop.

POST bodies are limited to 16 KiB, counting received bytes before a handler is
invoked, including chunked bodies and bodies with understated Content-Length.
Oversize bodies return 413 PAYLOAD_TOO_LARGE. The revised C01 plan requires this
limit, and its numeric value comes from the older 47-page SRS. Error envelopes
and safe handling follow the submitted 14-page SRS.
