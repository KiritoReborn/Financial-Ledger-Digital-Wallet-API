---
title: "BM25 search for cited vault answers"
type: research
date: "2026-11-28"
author: "P. Pranav Sai (B), AI-assisted"
category: resources
requirements: [SK-2, SB-3, TQ-7]
tags: [b10, second-brain, search, bm25, skills]
source: "Robertson and Zaragoza, 'The Probabilistic Relevance Framework: BM25 and Beyond', Foundations and Trends in Information Retrieval 3(4), 2009; Robertson, Zaragoza and Taylor, 'Simple BM25 Extension to Multiple Weighted Fields', CIKM 2004"
---

# BM25 search for cited vault answers (AI-assisted)

**Question.** The brain-query skill must answer from about forty Markdown notes
and cite every note it uses (SK-2). Which ranking is simple enough for a
standard-library script and still dependable?

**What the sources say.**
- *BM25.* BM25 scores a document by summing, over the query terms, an inverse
  document frequency times a saturating function of the term's frequency in
  that document. Two parameters shape it:
  - `k1` controls how quickly repeated occurrences stop adding score.
  - `b` controls how much longer documents are penalized.

  Values around `k1` = 1.2 to 2.0 and `b` = 0.75 are the usual starting points
  (Robertson and Zaragoza, 2009).
- *BM25F.* For documents with several fields, such as a title and a body,
  scoring each field separately and adding the scores breaks the saturation
  assumption. The better approach is to weight each field's term frequency
  first, then apply one saturation and length normalization to the combined
  frequency (Robertson, Zaragoza and Taylor, 2004).

**What it means for us.**
- [[projects/2026-11-27-b07-brain-query]] uses BM25 with `k1` = 1.2 and
  `b` = 0.75. Fields are combined BM25F-style: title, requirement IDs and tags
  are weighted three times the body before saturation. Index, log and README
  notes, which are mostly lists of links, count half.
- *Extractive answers.* Each answer line is a sentence copied from a note with
  that note's `[[wikilink]]`. A weak ranking can make the answer less
  complete, but it can never put words in a note's mouth. Generating free text
  would read better but would need a model and a check that every claim is
  supported.
- *What keyword matching misses.* The evaluation in
  `skills/brain-query/evaluation.md` found these limits:
  - word forms that light stemming does not join ("compared" and "comparison")
  - notes that mention a topic often outranking the note about it

  Embedding-based search would help, but would add dependencies and make
  results harder to explain. For a vault this size, the skill's procedure
  covers the gap instead: the agent reads the cited notes and searches again
  with their terms.
- *A trap to avoid.* A record of evaluation questions stored *inside* the vault
  matches those same questions and pollutes later runs. Evaluation records
  belong outside `brain/`.

**PR informed.** KiritoReborn/Financial-Ledger-Digital-Wallet-API#56 (B07)

Related: [[index]], [[projects/2026-11-27-b06-simulate-transfer]].
