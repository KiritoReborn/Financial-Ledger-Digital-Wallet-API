# brain-query evaluation run (TQ-7)

Run on 2026-11-27 by P. Pranav Sai (B), AI-assisted, against the real `brain/`
vault (36 notes). It used Python 3.11.9 on Windows and the default limit of
five notes. This record lives outside `brain/` so its quoted questions cannot
match themselves.

| # | Question | Notes cited, in rank order | Verdict |
| --- | --- | --- | --- |
| 1 | How are idempotency keys fingerprinted and what happens on conflict? | `projects/2026-11-26-b04-exactly-once-suite`, `projects/2026-11-25-b01-idempotency`, `resources/idempotency-keys-and-request-fingerprints`, `projects/2026-11-25-b03-transfers`, `projects/2026-11-25-b01b-idempotency-concurrency` | Good: the research note and the B01 note both cited |
| 2 | FR-2.10 concurrent requests | `projects/2026-11-25-b01b-idempotency-concurrency` first | Good: the note that proves FR-2.10 ranks first |
| 3 | What does reconciliation check? | `sqlite-read-only-transaction-snapshots`, `projects/2026-11-20-d03-reconciliation`, `projects/2026-11-25-d10-reconciliation-review`, … | Good |
| 4 | transfer rules and errors | B03 transfers note fifth, below B06, B09, B05 and B04 | Partial: the right note is cited, but not first |
| 5 | How is the admin key compared? | `constant-time-secret-comparison` third | Partial: "compared" does not meet "comparison" |
| 6 | Which currencies are supported and how many decimal places do they use? | B05 UI note third; `projects/fr-1-wallets` not cited | Partial: precision is spread thinly across notes |
| 7 | Three unrelated nonsense words | None. "No note in brain/ answers", exit code 1 | Good: no invented citation |

The ADR and SRS drafts for question 1 kept a citation on every sentence. The
only uncited line was the ADR's "To be written by the author" placeholder.

**Limits found.** The search matches words, not meaning. Light stemming cannot
join every word form, and a note that mentions a topic often can outrank the
note about it. Step 2 of SKILL.md covers this: the agent reads the cited notes
and searches again with a note's own terms or a requirement ID before
answering. Each answer stays extractive and cited, so a weak ranking gives a
less complete answer, never an invented one.

**Fixed during the run.**
- "fingerprinted" did not match "fingerprint": added light stemming.
- `FR-2.10` split into stray tokens such as "10": requirement IDs now stay
  whole.
- Headings and `Related:` lines were used as answers: they are now skipped.
- "currencies" became "currenci" and "places" became "plac": fixed the "-ies"
  and "-es" rules.
- "they", "use" and "many" counted as content words: added them to the
  stopwords.
