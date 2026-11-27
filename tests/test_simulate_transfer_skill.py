"""B06 checks for skills/simulate-transfer/SKILL.md (SK-6, SB-3, TQ-7).

Runs without the backend installed: it reads SKILL.md and the script's
constants, never starts the API.
"""

import importlib.util
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills" / "simulate-transfer"
SKILL_FILE = SKILL_DIR / "SKILL.md"
SCRIPT = SKILL_DIR / "scripts" / "simulate_transfer.py"
BRAIN_DIR = REPO_ROOT / "brain"


def _parse(text: str) -> tuple[dict[str, str], str]:
    assert text.startswith("---\n"), "SKILL.md must start with YAML frontmatter"
    end = text.index("\n---\n", 4)
    fields = {}
    for line in text[4:end].splitlines():
        key, sep, value = line.partition(":")
        assert sep == ":", f"Invalid frontmatter line: {line!r}"
        fields[key.strip()] = value.strip()
    return fields, text[end + 5:]


def _script():
    spec = importlib.util.spec_from_file_location("simulate_transfer_constants", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_frontmatter_name_matches_folder_and_description_is_present():
    fields, _ = _parse(SKILL_FILE.read_text(encoding="utf-8"))
    assert fields["name"] == SKILL_DIR.name == "simulate-transfer"
    assert len(fields["description"]) >= 20


def test_skill_covers_every_step_of_the_simulation():
    _, body = _parse(SKILL_FILE.read_text(encoding="utf-8"))
    for snippet in (
        "GET /health",
        "Register two users",
        "Deposit",
        "Idempotency-Key",
        "same key",
        "concurrent",
        "GET /admin/reconcile",
        "final balances",
        "simulate_transfer.py",
    ):
        assert snippet.lower() in body.lower(), snippet


def test_skill_states_the_secret_rules_and_uses_the_secure_client():
    _, body = _parse(SKILL_FILE.read_text(encoding="utf-8"))
    assert "Never display, echo, log or store secrets" in body
    assert "scripts/api_client.py" in body
    assert "SK-6" in body and "NFR-SEC-7" in body
    assert not re.search(r"Bearer\s+[A-Za-z0-9._~+/-]{12,}", body)
    assert not re.search(r"\b(ADMIN_TOKEN|ADMIN_KEY)\s*=\s*\S", body)


def test_skill_cites_existing_brain_notes():
    _, body = _parse(SKILL_FILE.read_text(encoding="utf-8"))
    links = re.findall(r"\[\[([^\]|]+)", body)
    stems = {path.stem for path in BRAIN_DIR.rglob("*.md")}
    assert links
    assert all(Path(link).stem in stems for link in links), links


def test_documented_amounts_match_the_script():
    _, body = _parse(SKILL_FILE.read_text(encoding="utf-8"))
    script = _script()
    net = script.TRANSFER + script.CONCURRENT["first"] - script.CONCURRENT["second"]
    final_first = script.OPENING["first"] - net
    final_second = script.OPENING["second"] + net
    for amount in (*script.OPENING.values(), script.TRANSFER, *script.CONCURRENT.values(),
                   final_first, final_second):
        assert f"{amount:,}" in body, amount
    assert f"First user {final_first:,} and second user {final_second:,}" in body


def test_script_never_prints_tokens():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "token" not in "".join(re.findall(r"print\((.*)\)", source))
    assert "from api_client import" in source
