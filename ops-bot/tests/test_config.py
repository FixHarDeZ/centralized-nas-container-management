import os

from app.config import Settings


def test_settings_defaults():
    s = Settings()
    assert s.mimo_base_url == "https://token-plan-sgp.xiaomimimo.com/v1"
    assert s.mimo_model == "mimo-v2.5-pro"
    assert s.watchtower_grace_minutes == 5
    assert s.ssh_port == 22


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("MIMO_API_KEY", "test-key")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    s = Settings()
    assert s.mimo_api_key == "test-key"
    assert s.telegram_bot_token == "test-token"


def test_github_settings_default_empty(monkeypatch):
    import app.config
    app.config._config = None
    s = app.config.Settings()
    assert s.github_token == ""
    assert s.github_repo == ""


def test_github_settings_from_env(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")
    import app.config
    app.config._config = None
    s = app.config.Settings()
    assert s.github_token == "tok"
    assert s.github_repo == "owner/repo"
