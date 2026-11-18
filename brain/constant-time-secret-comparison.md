---
title: "Constant-Time Secret Comparison with hmac.compare_digest"
author: "Gangavarapu Jaswant (D)"
date: "2026-11-18"
category: "resources"
tags: ["security", "authentication", "hmac", "timing-attack", "admin-api"]
requirements: ["NFR-SEC-1", "NFR-SEC-2", "NFR-SEC-7", "FR-1.9", "FR-4.4", "FR-5.1", "BR-5", "SAF-1"]
source: "https://docs.python.org/3/library/hmac.html#hmac.compare_digest"
---

# Constant-Time Secret Comparison with `hmac.compare_digest`

## Context & Requirements

Administrative operations—reversing a transaction (`POST /transactions/{id}/reverse`, `FR-4.4`) and running ledger reconciliation (`GET /admin/reconcile`, `FR-5.1`)—are restricted to the administrator (`BR-5`) and require both:

1. The admin bearer token (`Authorization: Bearer <ADMIN_TOKEN>`), whose SHA-256 hash is stored on the admin user row at startup (`FR-1.9`).
2. The `X-Admin-Key` header matching `ADMIN_KEY` (`NFR-SEC-2`).

Security and safety constraints governing admin credentials:

- **FR-1.9**: At startup, if `ADMIN_TOKEN` or `ADMIN_KEY` is missing or empty, the application refuses to start and names the missing variable.
- **NFR-SEC-1**: Every endpoint except `GET /health` and `POST /users` requires a valid bearer token and returns `401 UNAUTHENTICATED` otherwise.
- **NFR-SEC-2**: Read `ADMIN_TOKEN` and `ADMIN_KEY` from environment variables, compare the admin key in **constant time**, never store `ADMIN_KEY` in the database, and keep both secrets out of the repository.
- **NFR-SEC-7**: Never write tokens, admin keys, or idempotency payloads to logs, and never leak stack traces or internal paths in error responses.
- **SAF-1**: Authentication is demonstration-level, not production-grade; the system handles simulated funds only.

## Why Standard `==` Is Vulnerable

Standard string equality (`provided == expected`) short-circuits on the first mismatched byte. An attacker measuring response latency over repeated requests can infer how many leading bytes of `X-Admin-Key` match (`timing side-channel`), reducing key recovery from exponential search to linear byte-by-byte guessing.

Python's `hmac.compare_digest(a, b)` prevents content-dependent early exit by examining all bytes of equal-length inputs using bitwise XOR accumulation before returning a boolean result.

## Implementation Pattern

```python
import hmac


def verify_admin_key(provided_key: str | None, expected_key: str) -> bool:
    if not provided_key:
        return False
    return hmac.compare_digest(
        provided_key.encode("utf-8"),
        expected_key.encode("utf-8"),
    )
```

Key operational rules for admin verification:

- **Consistent `401 UNAUTHENTICATED` response (`EI-SW-1`, `NFR-SEC-1`)**: Missing, blank, or mismatched `X-Admin-Key` headers and invalid admin bearer tokens all return `401 UNAUTHENTICATED` without distinguishing which check failed.
- **No database storage (`NFR-SEC-2`)**: Unlike `ADMIN_TOKEN` (whose SHA-256 hash is stored in `users.token_hash`), `ADMIN_KEY` lives exclusively in process memory loaded from the environment.
- **No secret logging (`NFR-SEC-7`)**: Authentication failures log request correlation metadata (`X-Request-ID`) only—never the submitted `Authorization` or `X-Admin-Key` values.

## Related Notes

- [[sqlite-immutability-triggers]]
- [[sqlite-read-only-transaction-snapshots]]
