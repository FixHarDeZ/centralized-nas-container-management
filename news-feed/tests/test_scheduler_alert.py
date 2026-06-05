import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.scheduler import _load_summarizer_state, _save_summarizer_state, _ALERT_THRESHOLD


def test_load_state_missing_file(tmp_path):
    state = _load_summarizer_state(tmp_path)
    assert state["consecutive_empty"] == 0
    assert state["last_alert_at"] is None


def test_load_state_reads_file(tmp_path):
    (tmp_path / "summarizer_state.json").write_text(
        json.dumps({"consecutive_empty": 3, "last_alert_at": "2026-06-01T00:00:00+00:00"})
    )
    state = _load_summarizer_state(tmp_path)
    assert state["consecutive_empty"] == 3


def test_save_and_reload_state(tmp_path):
    _save_summarizer_state(tmp_path, {"consecutive_empty": 2, "last_alert_at": None})
    state = _load_summarizer_state(tmp_path)
    assert state["consecutive_empty"] == 2


def test_load_state_corrupted_file(tmp_path):
    (tmp_path / "summarizer_state.json").write_text("not json{{{")
    state = _load_summarizer_state(tmp_path)
    assert state["consecutive_empty"] == 0


def test_alert_threshold_value():
    assert _ALERT_THRESHOLD == 2
