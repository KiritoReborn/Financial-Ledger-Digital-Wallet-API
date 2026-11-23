"""D06 validation checks for skills/local-check/SKILL.md (SRS SK-5, SK-6, SB-0..SB-7)."""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills" / "local-check"
SKILL_FILE = SKILL_DIR / "SKILL.md"
BRAIN_DIR = REPO_ROOT / "brain"


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    assert text.startswith("---\n"), "SKILL.md must start with YAML frontmatter"
    end = text.index("\n---\n", 4)
    raw_frontmatter = text[4:end]
    body = text[end + 5 :]
    fields: dict[str, str] = {}
    for line in raw_frontmatter.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition(":")
        assert sep == ":", f"Invalid YAML frontmatter line: {line!r}"
        fields[key.strip()] = value.strip().strip('"').strip("'")
    return fields, body


def test_local_check_skill_frontmatter_matches_folder_and_has_description():
    text = SKILL_FILE.read_text(encoding="utf-8")
    frontmatter, _ = _parse_frontmatter(text)

    assert frontmatter.get("name") == SKILL_DIR.name == "local-check"
    assert frontmatter.get("description")
    assert len(frontmatter["description"]) >= 20


def test_local_check_skill_covers_required_steps_and_secret_safety():
    _, body = _parse_frontmatter(SKILL_FILE.read_text(encoding="utf-8"))

    for required_snippet in (
        "pip install",
        "pytest",
        "uvicorn",
        "GET /health",
        "PASS / FAIL",
        "SK-5",
        "SK-6",
        "UC-10",
        "scripts/api_client.py",
    ):
        assert required_snippet in body, f"Missing expected section/item: {required_snippet}"

    lowered = body.lower()
    assert "never" in lowered and "secret" in lowered


def test_local_check_skill_cites_existing_second_brain_notes():
    _, body = _parse_frontmatter(SKILL_FILE.read_text(encoding="utf-8"))
    wikilinks = re.findall(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", body)
    assert wikilinks, "Skill must cite at least one Second Brain note"

    vault_stems = {path.stem for path in BRAIN_DIR.rglob("*.md")}
    for link in wikilinks:
        target = Path(link).stem
        assert target in vault_stems, f"Broken Second Brain citation: [[{link}]]"
