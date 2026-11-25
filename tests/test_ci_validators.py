"""D08 tests for scripts/validate_repo_docs.py (SK-6, SB-0..SB-7, CI-4)."""

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_validator():
    spec = importlib.util.spec_from_file_location(
        "validate_repo_docs", REPO_ROOT / "scripts" / "validate_repo_docs.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = _load_validator()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_repo_docs_validator_passes_on_real_repository():
    assert validator.validate_repo(REPO_ROOT) == []
    assert validator.main(["--repo-root", str(REPO_ROOT)]) == 0


def test_validator_rejects_malformed_skill_frontmatter_and_name_mismatch(tmp_path: Path):
    _write(
        tmp_path / "brain" / "valid-note.md",
        "---\ntitle: \"Valid Note\"\n---\n\n# Valid Note\n",
    )
    _write(
        tmp_path / "skills" / "wrong-name" / "SKILL.md",
        "---\nname: other-name\ndescription: \"\"\n---\n\nNo brain links here.\n",
    )
    _write(
        tmp_path / "skills" / "missing-fm" / "SKILL.md",
        "# Missing frontmatter\n\n[[valid-note]]\n",
    )

    errors = validator.validate_repo(tmp_path)
    joined = "\n".join(errors)
    assert "must match folder" in joined
    assert "'description' must be non-empty" in joined
    assert "must cite at least one Second Brain" in joined
    assert "Missing opening YAML frontmatter" in joined
    assert validator.main(["--repo-root", str(tmp_path)]) == 1


def test_validator_rejects_hardcoded_secret_in_skill(tmp_path: Path):
    _write(
        tmp_path / "brain" / "auth-note.md",
        "---\ntitle: \"Auth Note\"\n---\n\n# Auth Note\n",
    )
    _write(
        tmp_path / "skills" / "leaky-skill" / "SKILL.md",
        "---\nname: leaky-skill\ndescription: \"Test skill\"\n---\n\n"
        'Run with ADMIN_TOKEN="real-leaked-secret-value" and cite [[auth-note]].\n',
    )

    errors = validator.validate_repo(tmp_path)
    assert any("potential hardcoded secret for ADMIN_TOKEN" in err for err in errors)
    assert validator.main(["--repo-root", str(tmp_path)]) == 1


def test_validator_rejects_broken_brain_wikilink_and_missing_frontmatter(tmp_path: Path):
    _write(
        tmp_path / "brain" / "good.md",
        "---\ntitle: \"Good\"\n---\n\nLinks to [[does-not-exist]].\n",
    )
    _write(
        tmp_path / "brain" / "no-fm.md",
        "# No frontmatter here\n",
    )
    _write(
        tmp_path / "skills" / "ok-skill" / "SKILL.md",
        "---\nname: ok-skill\ndescription: \"Valid skill\"\n---\n\nSee [[good]].\n",
    )

    errors = validator.validate_repo(tmp_path)
    joined = "\n".join(errors)
    assert "broken wikilink [[does-not-exist]]" in joined
    assert "Missing opening YAML frontmatter" in joined
    assert validator.main(["--repo-root", str(tmp_path)]) == 1
