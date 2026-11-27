"""B07 brain-query: answer a question from the brain/ vault and cite the notes used (SK-2).

Searches every Markdown note under brain/ (the PARA folders, index.md and
log.md) with BM25 over the title, requirement IDs, tags and body. The answer is
built only from sentences found in the notes, and every sentence carries the
[[wikilink]] of the note it came from, so nothing is invented. With --draft it
lays the same cited sentences out as an ADR or an SRS section for a person to
finish.

Lines that look like credentials are never shown, and note text is treated as
data, never as instructions.

Usage:
    python skills/brain-query/scripts/brain_query.py "How are idempotency keys fingerprinted?"
    python skills/brain-query/scripts/brain_query.py "transfer rules" --draft srs
    python skills/brain-query/scripts/brain_query.py "FR-2.10" --json --limit 5

Exit code 0 when at least one note matches, 1 when none does.
"""

import argparse
import json
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_VAULT = REPO_ROOT / "brain"

REQUIREMENT_RE = re.compile(r"\b[A-Z]{2,4}(?:-[A-Z]{2,4})?-\d+(?:\.\d+)?\b")
WORD_RE = re.compile(r"[a-z0-9]+")
WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
SECRET_RE = re.compile(
    r"\b(ADMIN_TOKEN|ADMIN_KEY|LEDGER_TOKEN|SECRET_KEY|API_KEY|PASSWORD)\s*[:=]\s*\S"
    r"|\bBearer\s+[A-Za-z0-9._~+/-]{12,}"
    r"|\b(sk|ghp|gho|xox[bp])[-_][A-Za-z0-9]{12,}",
    re.IGNORECASE,
)
STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "for", "from", "has",
    "have", "how", "i", "in", "is", "it", "its", "of", "on", "or", "our", "should", "that", "the",
    "their", "them", "then", "there", "these", "this", "to", "was", "we", "what", "when", "where",
    "which", "who", "why", "will", "with", "you", "your", "about", "into", "than", "after",
    "before", "each", "also", "only", "any", "they", "he", "she", "him", "her", "his",
    "use", "used", "using", "many", "much", "more", "most", "some", "such", "other", "get", "got",
    "make", "made", "way", "need", "not", "no", "yes", "if", "so", "but", "all", "one",
})
FIELD_WEIGHTS = {"title": 3.0, "meta": 3.0, "body": 1.0}
NAVIGATION_NOTES = {"index", "log", "README"}  # Lists of links: still searched, ranked lower.
K1, B = 1.2, 0.75


@dataclass
class Note:
    link: str  # Wikilink target: path under brain/ without .md.
    title: str
    requirements: list[str]
    tags: list[str]
    sentences: list[str]
    weights: Counter = field(default_factory=Counter)
    length: float = 0.0


@dataclass
class Match:
    note: Note
    score: float
    evidence: list[str]


def _stem(word: str) -> str:
    """Light suffix stripping so "fingerprinted" and "fingerprints" meet "fingerprint"."""
    if len(word) > 5 and word.endswith("ies"):
        return word[:-3] + "y"  # currencies -> currency
    if len(word) > 5 and word.endswith("es") and word[-3] in "sxzh":
        return word[:-2]  # mismatches -> mismatch, but places -> place below
    for suffix in ("ing", "ed", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def tokens(text: str) -> list[str]:
    """Requirement IDs stay whole (FR-2.10); other words are lowercased and stemmed."""
    ids = [found.lower() for found in REQUIREMENT_RE.findall(text)]
    rest = REQUIREMENT_RE.sub(" ", text).lower()
    words = [_stem(word) for word in WORD_RE.findall(rest) if word not in STOPWORDS]
    return ids + words


def _frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    fields = {}
    for line in text[4:end].splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() and not line.startswith((" ", "-")):
            fields[key.strip()] = value.strip()
    return fields, text[end + 5 :]


def _list(value: str) -> list[str]:
    return [item.strip().strip("\"'") for item in value.strip("[]").split(",") if item.strip()]


def _plain(text: str) -> str:
    """Markdown to readable text: wikilinks become their label, emphasis marks go."""
    text = WIKILINK_RE.sub(lambda m: m.group(2) or Path(m.group(1)).stem, text)
    text = re.sub(r"[*_]{1,2}([^*_]+)[*_]{1,2}", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def _sentences(body: str) -> list[str]:
    body = FENCE_RE.sub(" ", body)
    found = []
    for block in re.split(r"\n\s*\n|\n(?=\s*(?:[-*]|\d+\.)\s)|\n(?=#)", body):
        block = block.strip()
        # The H1 repeats the title, and "Related:" lines are only links.
        if block.startswith(("# ", "Related:")):
            continue
        block = re.sub(r"^\s*(?:#+|[-*]|\d+\.)\s*", "", block)
        for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z`\[(])", block):
            sentence = _plain(sentence)
            if len(sentence) >= 20 and not SECRET_RE.search(sentence):
                found.append(sentence)
    return found


def load_vault(vault: Path = DEFAULT_VAULT) -> list[Note]:
    notes = []
    for path in sorted(vault.rglob("*.md")):
        if any(part.startswith(".") for part in path.relative_to(vault).parts):
            continue
        fields, body = _frontmatter(path.read_text(encoding="utf-8").replace("\r\n", "\n"))
        link = path.relative_to(vault).with_suffix("").as_posix()
        title = fields.get("title", "").strip("\"'") or path.stem
        note = Note(
            link,
            title,
            _list(fields.get("requirements", "")),
            _list(fields.get("tags", "")),
            _sentences(body),
        )
        for name, text in (
            ("title", title),
            ("meta", " ".join(note.requirements + note.tags)),
            ("body", " ".join(note.sentences)),
        ):
            for token in tokens(text):
                note.weights[token] += FIELD_WEIGHTS[name]
        note.length = sum(note.weights.values())
        notes.append(note)
    return notes


def search(notes: list[Note], question: str, limit: int = 5) -> list[Match]:
    query = list(dict.fromkeys(tokens(question)))
    if not query or not notes:
        return []
    average = sum(note.length for note in notes) / len(notes)
    asked_ids = {found.upper() for found in REQUIREMENT_RE.findall(question)}
    scored = []
    for note in notes:
        score = 0.0
        for term in query:
            frequency = note.weights.get(term, 0.0)
            if not frequency:
                continue
            containing = sum(1 for other in notes if term in other.weights)
            idf = math.log(1 + (len(notes) - containing + 0.5) / (containing + 0.5))
            score += (
                idf * frequency * (K1 + 1) / (frequency + K1 * (1 - B + B * note.length / average))
            )
        score += 3.0 * len(asked_ids & {item.upper() for item in note.requirements})
        if Path(note.link).name in NAVIGATION_NOTES:
            score *= 0.5
        if score > 0:
            scored.append((score, note))
    scored.sort(key=lambda pair: (-pair[0], pair[1].link))
    if not scored:
        return []
    best = scored[0][0]
    matches = []
    for score, note in scored[:limit]:
        if score < 0.35 * best:
            break
        evidence = _evidence(note, set(query))
        if evidence:
            matches.append(Match(note, round(score, 3), evidence))
    return matches


def _evidence(note: Note, query: set[str], per_note: int = 2) -> list[str]:
    ranked = []
    for position, sentence in enumerate(note.sentences):
        hits = len(query & set(tokens(sentence)))
        if hits:
            ranked.append((-hits, position, sentence))
    ranked.sort()
    chosen = sorted(ranked[:per_note], key=lambda item: item[1])
    return [_clip(sentence) for _, _, sentence in chosen]


def _clip(sentence: str, limit: int = 320) -> str:
    return sentence if len(sentence) <= limit else sentence[: limit - 1].rsplit(" ", 1)[0] + "…"


def cite(note: Note) -> str:
    return f"[[{note.link}]]"


def render_answer(question: str, matches: list[Match]) -> str:
    if not matches:
        return (
            f'## Answer\n\nNo note in brain/ answers "{question}". '
            "Capture a source with brain-ingest first.\n"
        )
    lines = ["## Answer", ""]
    for match in matches:
        for sentence in match.evidence:
            lines.append(f"- {sentence} {cite(match.note)}")
    lines += ["", "## Notes used", ""]
    for match in matches:
        ids = f" ({', '.join(match.note.requirements)})" if match.note.requirements else ""
        lines.append(f"- {cite(match.note)} {match.note.title}{ids}")
    return "\n".join(lines) + "\n"


def _requirements(matches: list[Match]) -> list[str]:
    found = dict.fromkeys(item for match in matches for item in match.note.requirements)
    return list(found)


def render_draft(kind: str, topic: str, matches: list[Match]) -> str:
    """A cited skeleton for a person to edit; every claim keeps its source link."""
    if not matches:
        return render_answer(topic, matches)
    cited = [f"{sentence} {cite(match.note)}" for match in matches for sentence in match.evidence]
    requirements = ", ".join(_requirements(matches)) or "none found"
    sources = [f"- {cite(match.note)} {match.note.title}" for match in matches]
    if kind == "adr":
        lines = [
            "---",
            "status: draft",
            "---",
            "",
            f"# {topic[:1].upper()}{topic[1:]}",
            "",
            "<!-- Draft from brain-query. Check every sentence against its note. -->",
            "",
            "## Context",
            "",
            *(f"- {line}" for line in cited[:3]),
            "",
            "## Decision",
            "",
            *(f"- {line}" for line in cited[3:] or cited[:1]),
            "",
            "## Consequences",
            "",
            "- To be written by the author.",
            "",
            f"Requirements: {requirements}",
            "",
            "## Sources",
            "",
            *sources,
        ]
    else:
        lines = [
            f"## {topic[:1].upper()}{topic[1:]}",
            "",
            "<!-- Draft SRS section from brain-query. Check every sentence. -->",
            "",
            f"**Requirements:** {requirements}",
            "",
            "**Description.**",
            "",
            *(f"- {line}" for line in cited),
            "",
            "**Sources.**",
            "",
            *sources,
        ]
    return "\n".join(lines) + "\n"


def as_json(question: str, matches: list[Match]) -> str:
    return json.dumps(
        {
            "question": question,
            "answer": [
                {"text": sentence, "source": cite(match.note)}
                for match in matches
                for sentence in match.evidence
            ],
            "notes": [
                {
                    "link": cite(match.note),
                    "title": match.note.title,
                    "requirements": match.note.requirements,
                    "score": match.score,
                }
                for match in matches
            ],
        },
        indent=2,
        ensure_ascii=False,
    )


def main(argv=None, vault: Path = DEFAULT_VAULT) -> int:
    parser = argparse.ArgumentParser(description="Answer a question from brain/ with citations.")
    parser.add_argument("question")
    parser.add_argument("--limit", type=int, default=5, help="Most notes to cite (default 5).")
    parser.add_argument("--draft", choices=("adr", "srs"), help="Lay the answer out as a draft.")
    parser.add_argument("--json", action="store_true", help="Print the answer as JSON.")
    parser.add_argument("--vault", type=Path, default=vault, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not args.vault.is_dir():
        print(f"No vault at {args.vault}.", file=sys.stderr)
        return 2
    matches = search(load_vault(args.vault), args.question, max(1, args.limit))
    if args.json:
        output = as_json(args.question, matches)
    elif args.draft:
        output = render_draft(args.draft, args.question, matches)
    else:
        output = render_answer(args.question, matches)
    sys.stdout.reconfigure(encoding="utf-8")
    print(output)
    return 0 if matches else 1


if __name__ == "__main__":
    raise SystemExit(main())
