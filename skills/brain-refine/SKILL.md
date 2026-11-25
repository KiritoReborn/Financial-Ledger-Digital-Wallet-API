---
name: brain-refine
description: Refine the Second Brain PARA vault by filing brain/inbox/ notes into projects, areas, resources, or archive, merging duplicates, repairing broken wikilinks, and updating brain/index.md and brain/log.md without displaying or storing secrets.
---

# Brain Refine (`brain-refine`)

Maintain the Obsidian Second Brain vault (`brain/`) so research notes, project
decisions, and verification logs remain organized, deduplicated, and free of
broken links (`SK-3`, `SK-6`, `SB-0`–`SB-7`).

## Secret-Safety Rules (`SK-6`, `NFR-SEC-7`)

- **Never display, echo, log, or store secrets or credentials.** Strip or refuse
  to ingest any raw `ADMIN_TOKEN`, `ADMIN_KEY`, bearer tokens, `.env` values, or
  request payloads containing credentials.
- If an external API check is ever needed alongside vault refinement, load
  credentials solely from environment variables through `scripts/api_client.py`
  (`SK-6`).
- Report only sanitized note paths, requirement IDs, and link-repair counts.

## PARA Vault Structure (`SB-0`, `SB-1`)

- `brain/inbox/` — Unfiled intake notes awaiting triage (`brain-ingest`).
- `brain/projects/` — Active or completed work-package and milestone notes.
- `brain/areas/` — Ongoing module or operational ownership notes.
- `brain/resources/` — Reusable technical reference notes.
- `brain/archive/` — Completed session transcripts and superseded records.
- `brain/index.md` — Vault table of contents linking active and reference notes.
- `brain/log.md` — Chronological record of vault runs and engineering checks.

## Step-by-Step Procedure (`SK-3`)

Execute the steps below in order and record every change in `brain/log.md`.

### Step 1 — Inspect `brain/inbox/` and Validate Frontmatter

List all Markdown files in `brain/inbox/` (excluding `.gitkeep`). For each note,
verify YAML frontmatter contains `title`, `author`, `date`, `category`, `tags`,
`requirements`, and `source`, plus at least one SRS requirement ID and
`[[wikilink]]`.

### Step 2 — File Inbox Notes into PARA Folders

Move each validated inbox note into the matching PARA destination:

- Time-bound work packages or milestone reviews -> `brain/projects/`
- Ongoing module responsibilities -> `brain/areas/`
- Technical concepts, SQLite/API patterns, or standards -> `brain/resources/`
- Completed session logs or retired notes -> `brain/archive/`

Preserve concise filenames (kebab-case `.md`) and update the frontmatter
`category` field (`projects`, `areas`, `resources`, or `archive`) to match the
destination folder.

### Step 3 — Merge Duplicate Notes

Scan `brain/projects/`, `brain/areas/`, and `brain/resources/` for notes
covering the same topic or requirement set:

1. Keep the canonical note (or most recent reviewed note) as the primary target.
2. Merge unique findings, SRS requirement IDs, code paths, and PR/test evidence.
3. Update any incoming `[[wikilinks]]` pointing to the retired duplicate, then
   archive or remove the superseded duplicate file.

### Step 4 — Audit and Repair Broken `[[wikilinks]]`

Scan every Markdown file under `brain/` (ignoring fenced code blocks) for
`[[target]]` and `[[target|alias]]` wikilinks:

1. Verify every target stem resolves to an existing `.md` note in `brain/`.
2. Repair misspelled, moved, or path-shifted targets (e.g., updating a moved
   inbox note reference to its new PARA path).
3. Flag any unresolved reference that lacks a corresponding note.

### Step 5 — Update `brain/index.md` and `brain/log.md`

1. Add newly filed or unindexed project/resource notes to `brain/index.md`
   under the matching section.
2. Append a dated entry to `brain/log.md` summarizing how many notes were
   moved, merged, or repaired, along with a `[[wikilink]]` to the affected
   notes.

### Step 6 — Output Summary Table

Return a concise summary table containing no secrets or raw credentials:

| Action | Count | Details |
| --- | --- | --- |
| Filed from `brain/inbox/` | N | Destination PARA paths |
| Merged duplicates | N | Canonical notes kept |
| Repaired `[[wikilinks]]` | N | Fixed target references |
| Updated `brain/index.md` & `brain/log.md` | Yes / No | Linked sections updated |
| Skipped / needs review | N | Missing metadata or ambiguous targets |

## Second Brain References (`SB-0`–`SB-7`)

- [[index]] — Vault entry point and PARA directory guide.
- [[log]] — Chronological second-brain run log.
- [[2026-11-20-d03-reconciliation]] — D03 reconciliation implementation record.
- [[projects/2026-11-25-d02-reversal]] — D02 reversal service and endpoint record.
- [[constant-time-secret-comparison]] — Secret handling and non-logging rules (`NFR-SEC-2`, `NFR-SEC-7`).
