import sys
from unittest.mock import patch
import ingest


@patch("ingest.run_incremental")
def test_cli_default_runs_incremental(mock_run, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["ingest.py"])
    ingest.main()
    mock_run.assert_called_once_with(dry_run=False)


@patch("ingest.run_full")
def test_cli_full_flag(mock_run, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["ingest.py", "--full"])
    ingest.main()
    mock_run.assert_called_once_with(dry_run=False)


@patch("ingest.run_single")
def test_cli_page_flag(mock_run, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["ingest.py", "--page", "abc123"])
    ingest.main()
    mock_run.assert_called_once_with("abc123", dry_run=False)


@patch("ingest.run_incremental")
def test_cli_dry_run_flag(mock_run, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["ingest.py", "--dry-run"])
    ingest.main()
    mock_run.assert_called_once_with(dry_run=True)


@patch("ingest.run_full")
def test_cli_full_dry_run(mock_run, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["ingest.py", "--full", "--dry-run"])
    ingest.main()
    mock_run.assert_called_once_with(dry_run=True)
