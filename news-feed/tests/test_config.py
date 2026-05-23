import json
from pathlib import Path
from unittest.mock import patch
import pytest


def test_get_config_returns_env_defaults_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGEST_TIMES", "08:00,13:00")
    monkeypatch.setenv("SUMMARIZER_PROVIDER", "openrouter")
    with patch("app.config._schedule_file", return_value=tmp_path / "schedule.json"):
        import app.config as config
        result = config.get_config()
    assert "08:00" in result["digest_times"]
    assert result["summarizer_provider"] == "openrouter"


def test_get_config_reads_schedule_json(tmp_path):
    schedule = {"digest_times": ["09:00"], "enabled_sources": ["gsmarena"],
                 "summarizer_provider": "anthropic", "summarizer_model": "claude-sonnet-4-6"}
    f = tmp_path / "schedule.json"
    f.write_text(json.dumps(schedule))
    with patch("app.config._schedule_file", return_value=f):
        import app.config as config
        result = config.get_config()
    assert result["digest_times"] == ["09:00"]
    assert result["enabled_sources"] == ["gsmarena"]


def test_update_config_writes_file(tmp_path):
    with patch("app.config._schedule_file", return_value=tmp_path / "schedule.json"), \
         patch.dict("os.environ", {"DATA_DIR": str(tmp_path)}):
        import app.config as config
        config.update_config({"summarizer_provider": "openrouter", "summarizer_model": "deepseek/deepseek-chat",
                               "digest_times": ["07:00"], "enabled_sources": ["venturebeat"]})
        data = json.loads((tmp_path / "schedule.json").read_text())
    assert data["summarizer_provider"] == "openrouter"
    assert data["summarizer_model"] == "deepseek/deepseek-chat"


def test_update_config_partial_merge(tmp_path):
    initial = {
        "digest_times": ["07:00"],
        "enabled_sources": ["venturebeat"],
        "summarizer_provider": "anthropic",
        "summarizer_model": "claude-sonnet-4-6",
    }
    f = tmp_path / "schedule.json"
    f.write_text(json.dumps(initial))
    with patch("app.config._schedule_file", return_value=f), \
         patch.dict("os.environ", {"DATA_DIR": str(tmp_path)}):
        from app import config
        config.update_config({"summarizer_provider": "openrouter"})
        data = json.loads(f.read_text())
    assert data["summarizer_provider"] == "openrouter"
    assert data["digest_times"] == ["07:00"]          # preserved
    assert data["enabled_sources"] == ["venturebeat"]  # preserved
