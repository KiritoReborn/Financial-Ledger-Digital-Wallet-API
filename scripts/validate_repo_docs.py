"""D08 CI validator for Agent Skills (SK-6), Second Brain notes (SB-0..SB-7), and secrets."""

import argparse
import re
import sys
from pathlib import Path

_FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
_SECRET_ASSIGN_RE = re.compile(
    r"\b(ADMIN_TOKEN|ADMIN_KEY|SECRET_KEY|API_KEY)\s*[:=]\s*(['\"]?)([^\s'\";]+)\2"
)
_BEARER_LITERAL_RE = re.compile(r"\bBearer\s+([A-Za-z0-9._~+/-]{12,})")
_PLACEHOLDER_PREFIXES = (
    "$",
    "<",
    "{",
    "example",
    "placeholder",
    "your-",
    "your_",
    "demo-",
    "changeme",
    "xxx",
)


def parse_frontmatter(text: str) -> tuple[dict[str, str | list[str]], str]:
    """Parse minimal YAML frontmatter (scalars and block string lists)."""
    normalized = text.replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        raise ValueError("Missing opening YAML frontmatter delimiter '---'")
    end = normalized.find("\n---\n", 4)
    if end == -1:
        if normalized.endswith("\n---"):
            end = len(normalized) - 4
            body = ""
        else:
            raise ValueError("Missing closing YAML frontmatter delimiter '---'")
    else:
        body = normalized[end + 5 :]

    raw_fm = normalized[4:end]
    fields: dict[str, str | list[str]] = {}
    current_list_key: str | None = None
    for line in raw_fm.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line.startswith((" ", "\t")) and stripped.startswith("- "):
            if current_list_key is None:
                raise ValueError(f"Unexpected YAML list item without key: {line!r}")
            item = stripped[2:].strip().strip('"').strip("'")
            existing = fields.get(current_list_key)
            if not isinstance(existing, list):
                fields[current_list_key] = [item]
            else:
                existing.append(item)
            continue
        key, sep, value = line.partition(":")
        if sep != ":" or not key.strip():
            raise ValueError(f"Invalid YAML frontmatter line: {line!r}")
        key_name = key.strip()
        val = value.strip()
        if not val:
            fields[key_name] = []
            current_list_key = key_name
        else:
            fields[key_name] = val.strip('"').strip("'")
            current_list_key = None
    return fields, body


def _extract_wikilinks(body: str) -> list[str]:
    without_fences = _FENCED_CODE_RE.sub("", body)
    without_inline = _INLINE_CODE_RE.sub("", without_fences)
    return _WIKILINK_RE.findall(without_inline)


def _is_placeholder_secret(value: str) -> bool:
    lowered = value.lower()
    return any(lowered.startswith(prefix) for prefix in _PLACEHOLDER_PREFIXES)


def validate_brain(repo_root: Path) -> tuple[set[str], list[str]]:
    """Validate frontmatter and internal wikilinks across all brain/**/*.md notes."""
    brain_dir = repo_root / "brain"
    if not brain_dir.is_dir():
        return set(), ["Missing brain/ directory"]

    md_files = sorted(brain_dir.rglob("*.md"))
    stems = {path.stem for path in md_files}
    errors: list[str] = []

    for md_path in md_files:
        rel = md_path.relative_to(repo_root)
        try:
            fields, body = parse_frontmatter(md_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            errors.append(f"{rel}: {exc}")
            continue
        title = fields.get("title")
        if not isinstance(title, str) or not title.strip():
            errors.append(f"{rel}: frontmatter 'title' must be a non-empty string")
        for link in _extract_wikilinks(body):
            target = Path(link).stem
            if target not in stems:
                errors.append(f"{rel}: broken wikilink [[{link}]]")
    return stems, errors


def validate_skills(repo_root: Path, brain_stems: set[str]) -> list[str]:
    """Validate every skills/<name>/SKILL.md per SK-6, secret rules, and brain links."""
    skills_dir = repo_root / "skills"
    if not skills_dir.is_dir():
        return ["Missing skills/ directory"]

    errors: list[str] = []
    for entry in sorted(skills_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        skill_file = entry / "SKILL.md"
        rel = skill_file.relative_to(repo_root)
        if not skill_file.is_file():
            errors.append(f"{entry.relative_to(repo_root)}: missing SKILL.md")
            continue
        text = skill_file.read_text(encoding="utf-8")
        try:
            fields, body = parse_frontmatter(text)
        except ValueError as exc:
            errors.append(f"{rel}: {exc}")
            continue

        name = fields.get("name")
        description = fields.get("description")
        if not isinstance(name, str) or name != entry.name:
            errors.append(
                f"{rel}: frontmatter 'name' ({name!r}) must match folder {entry.name!r}"
            )
        if not isinstance(description, str) or not description.strip():
            errors.append(f"{rel}: frontmatter 'description' must be non-empty")

        links = _extract_wikilinks(body)
        if not links:
            errors.append(f"{rel}: must cite at least one Second Brain [[note]]")
        for link in links:
            if Path(link).stem not in brain_stems:
                errors.append(f"{rel}: broken Second Brain citation [[{link}]]")

        for match in _SECRET_ASSIGN_RE.finditer(text):
            var_name, _, value = match.groups()
            if not _is_placeholder_secret(value):
                errors.append(f"{rel}: potential hardcoded secret for {var_name}")
        for match in _BEARER_LITERAL_RE.finditer(text):
            token_val = match.group(1)
            if not _is_placeholder_secret(token_val):
                errors.append(f"{rel}: potential hardcoded Bearer token literal")
    return errors


def validate_repo(repo_root: Path) -> list[str]:
    """Run all D08 brain and skill documentation checks."""
    brain_stems, brain_errors = validate_brain(repo_root)
    skill_errors = validate_skills(repo_root, brain_stems)
    return [*brain_errors, *skill_errors]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate skills/*/SKILL.md frontmatter, secret hygiene, and brain/ wikilinks."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root directory",
    )
    args = parser.parse_args(argv)
    errors = validate_repo(args.repo_root.resolve())
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Skill and Second Brain validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
