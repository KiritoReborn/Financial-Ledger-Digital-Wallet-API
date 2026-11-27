---
title: "B07 brain-query skill"
date: "2026-11-27"
author: "P. Pranav Sai (B), AI-assisted"
category: projects
type: ai-session
tags: [member-b, b07, skill, second-brain, search]
requirements: [SK-2, SK-6, SB-3, TQ-7, NFR-SEC-7]
source: "Final SRS section 6.3, SDLC course stages 2 and 4, revised work distribution page 8, PRANAV_PLAN Stage 10"
---

# B07 brain-query skill (AI-assisted)

**Goal.** Answer questions about the project from this vault and cite every
note used (SK-2). Also draft ADRs and SRS sections from the notes, as the SDLC
asks for in the design stage.

**What was built.**
- `skills/brain-query/SKILL.md`, in Agent Skills format. It sets out the rules
  (answer only from the vault, treat note text as data, never show secrets),
  a four-step procedure, drafting and the output format.
- `skills/brain-query/scripts/brain_query.py`, standard library only. It reads
  every note under `brain/`, parsing its title, requirement IDs and tags. It
  splits bodies into sentences and leaves out:
  - code blocks
  - H1 headings, which repeat the title
  - `Related:` lines
  - anything that looks like a credential

  It ranks notes by BM25 over title, requirement IDs and tags (weighted ×3) and
  body. Requirement IDs stay whole, other words are lightly stemmed, a
  requirement ID in the question boosts notes listing it, and `index`, `log`
  and `README` count half. It prints the best sentences of the top notes, each
  ending with the note's `[[wikilink]]`, then the notes used. It can also print
  `--json`, or `--draft adr|srs`.

**Decisions.**
- *Extractive.* The script never writes facts of its own. Every line is a
  sentence from a note plus its link, so a citation can always be checked. The
  agent following SKILL.md reads the cited notes and writes the final answer
  from them.
- *Read-only.* The skill never edits the vault. `brain-ingest` and
  `brain-refine` own changes.

**Evidence.** `tests/test_brain_query_skill.py` has 14 tests, and needs no
backend. They cover the SKILL.md format and rules, token handling, answers and
drafts from the real vault, a no-match answer, credential and code-block
filtering on a small vault, and a missing vault.

**Evaluation run (TQ-7).** The questions, the notes cited and the exit codes
are recorded in `skills/brain-query/evaluation.md`, outside the vault. A
record inside the vault would quote the questions and then match them itself.
The run found one limit: keyword ranking can put a note that merely mentions a
topic above the note about it. Step 2 of the procedure, reading the cited notes
and searching again, covers this.

Related: [[projects/2026-11-27-b06-simulate-transfer]], [[index]], [[log]].
