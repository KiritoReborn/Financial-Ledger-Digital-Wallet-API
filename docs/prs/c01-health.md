# C01: Add read-only API health check

GET /health returns 200 with status ok when the configured SQLite database is
readable. It requires no authentication, opens the file read-only, and does not
create or migrate a database. Corrupt/missing files produce a generic structured
INTERNAL_ERROR; SQLite busy errors use DATABASE_BUSY. SQL, paths and exception
text are omitted from responses.

The endpoint uses an injected readiness adapter so HTTP behavior is separate
from SQLite access. This is the first C01 increment. Common request IDs, CORS,
global validation/errors and integration with A's full provider remain later
work. No financial operation is added.

Reuses existing main and preserves A/B/D migrations, tests and business modules.
The original team CI file is unchanged; the new API-only workflow installs this
component and runs its tests on Python 3.11. The earlier project-setup branch is
not merged or used as the base.

Final-SRS references: EI-SW-1 (health portion), NFR-SEC-7 (safe health errors),
SE-6 (small readiness boundary). Owner delegation comes from the user-selected
revised distribution, which assigns C01 to C.

Validation: six real SQLite readiness tests passed on Python 3.11; ten pytest
tests passed on available Python 3.14 (six readiness plus four existing trigger
tests). Direct adapter/OpenAPI checks and the package build also passed on
available Python 3.14. HTTP TestClient execution timed out locally; full HTTP validation and
Ruff are pending the API CI job. Do not mark all C01 complete or merge until
the required checks and human review pass.

Issue and PR links: not created because the connection rejects repository writes
with HTTP 403 and shell networking is denied. Progress note:
brain/projects/2026-11-19-c01-health.md.
