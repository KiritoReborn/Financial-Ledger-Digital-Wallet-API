---
title: User registration and bearer tokens
work_package: H04
date: 2026-11-23
category: projects
tags: [registration, sqlite]
requirements: [FR-1.1, FR-1.2, FR-1.9, NFR-SEC-1, NFR-SEC-2]
---

# User registration and bearer tokens

`POST /users` accepts a name and email. Spaces around each field are trimmed and the email is stored in lowercase. Two simultaneous requests for the same address produce one 201 and one 409. The 201 response is the only place the generated token is returned. The lookup uses its SHA-256 digest and the unique index from [[projects/h02-database-migration]].

Startup checks both admin settings before creating the database. The admin keeps the same user ID across restarts. Changing the configured token replaces the stored digest, so the previous token stops working. Reconciliation still requires the admin key.

[HTTP and restart tests](../../backend/tests/test_registration.py) · [[projects/h03-sqlite-provider|Request transactions]]
