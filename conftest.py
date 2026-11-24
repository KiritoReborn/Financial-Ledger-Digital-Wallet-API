"""Isolated startup settings for tests that exercise the ASGI lifespan."""

import pytest


@pytest.fixture
def api_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "api.sqlite3"))
    monkeypatch.setenv("ADMIN_TOKEN", "test-only-token")
    monkeypatch.setenv("ADMIN_KEY", "test-only-key")
