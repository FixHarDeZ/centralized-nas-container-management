from unittest.mock import MagicMock, patch


def test_render_prompt_substitutes_placeholders(tmp_path):
    import app.analyzer as analyzer
    template = tmp_path / "t.md"
    template.write_text("Container: {{container}}\nExcerpt:\n{{excerpt}}")
    rendered = analyzer.render_prompt(str(template), container="torrentwatch", excerpt="ERROR boom")
    assert "torrentwatch" in rendered
    assert "ERROR boom" in rendered


def test_workspace_dir_joins_repo_and_subdir():
    import app.analyzer as analyzer
    row = {"repo": "/workspaces/centralized-nas-container-management", "subdir": "torrentwatch"}
    assert analyzer.workspace_dir(row) == "/workspaces/centralized-nas-container-management/torrentwatch"


@patch("subprocess.run")
def test_analyze_invokes_claude_readonly_and_parses_json(mock_run):
    import app.analyzer as analyzer
    mock_run.return_value = MagicMock(stdout='{"result": "root cause: db pool exhausted"}', returncode=0)
    row = {"name": "torrentwatch", "repo": "/workspaces/r", "subdir": "torrentwatch"}
    result = analyzer.analyze(row, "fp123", "ERROR boom")
    assert result["text"] == "root cause: db pool exhausted"
    args = mock_run.call_args.args[0]
    assert args[0] == "claude"
    assert "-p" in args
    assert "Edit" not in " ".join(args)
    assert "Write" not in " ".join(args)


@patch("subprocess.run")
def test_analyze_raises_on_nonzero_returncode(mock_run):
    import app.analyzer as analyzer
    import pytest
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="auth error")
    row = {"name": "torrentwatch", "repo": "/workspaces/r", "subdir": "torrentwatch"}
    with pytest.raises(RuntimeError) as exc_info:
        analyzer.analyze(row, "fp123", "ERROR boom")
    assert "claude analyze failed" in str(exc_info.value)
    assert "exit 1" in str(exc_info.value)
