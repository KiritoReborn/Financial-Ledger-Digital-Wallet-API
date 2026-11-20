# A001 schema fixture for C04 integration tests

`a001_initial_schema.sql` is an exact read-only test copy of A's actual
`db/migrations/001_initial_schema.sql` at commit
`3d7ecb03b4260524189d971206e677be4f1e4826` on `feat/database-schema-001`.
SHA-256: `fe1b2cb2baa563b11832728b897be6165bc96a79f6498caa10501df5bb7b5e49`.
The test verifies this digest. Keep this fixture as LF text (`.gitattributes`).

It is not an alternate production migration or a proposal to change A's work.
The C04 fixture creates disposable databases and tests C's posting engine against
that schema. Actual A/H03 transaction-provider integration and any later schema
updates need separate verification before handover.
