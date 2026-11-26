from scripts.validate_repo_docs import validate_brain


def test_intake_checks_apply_before_filing(tmp_path):
    vault = tmp_path / "brain"
    inbox = vault / "inbox"
    inbox.mkdir(parents=True)
    (vault / "index.md").write_text("---\ntitle: Index\n---\n")
    note = inbox / "capture.md"
    note.write_text("---\ntitle: Capture\n---\nSummary")
    _, errors = validate_brain(tmp_path)
    for field in ("author", "date", "source", "requirements", "tags", "category", "wikilink"):
        assert any(field in error for error in errors)
    note.write_text(
        "---\ntitle: Capture\nauthor: A\ndate: 2026-11-26\ncategory: inbox\n"
        "source: SRS.pdf section 2.1\nrequirements: [FR-3.1]\ntags: [sqlite]\n---\nSee [[index]]."
    )
    assert validate_brain(tmp_path)[1] == []
