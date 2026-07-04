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


@patch("app.analyzer.notify")
@patch("subprocess.run")
def test_run_fix_happy_path_creates_pr(mock_run, mock_notify):
    import app.analyzer as analyzer

    def side_effect(args, **kwargs):
        if args[:2] == ["git", "diff"] and "--name-only" in args:
            return MagicMock(stdout="src/foo.py\n")
        if args[:2] == ["git", "diff"] and "--stat" in args:
            return MagicMock(stdout="1 file changed, 2 insertions(+)")
        if args == ["git", "diff"]:
            return MagicMock(stdout="+line1\n+line2\n")
        if args[:2] == ["gh", "pr"]:
            return MagicMock(stdout="https://github.com/org/repo/pull/42\n")
        return MagicMock(stdout="")

    mock_run.side_effect = side_effect
    row = {"name": "torrentwatch", "repo": "/workspaces/r", "subdir": "torrentwatch"}
    analysis = {"text": "root cause X", "excerpt": "ERROR boom"}
    pr_url = analyzer.run_fix(row, "fp123", analysis, "/workspaces/r/torrentwatch")
    assert pr_url == "https://github.com/org/repo/pull/42"

    calls = [c.args[0] for c in mock_run.call_args_list]
    assert ["git", "fetch", "origin"] in calls
    assert any(c[:3] == ["git", "checkout", "-b"] and c[3] == "fix/fp123" for c in calls)
    assert ["git", "checkout", "-B", "main", "origin/main"] in calls


@patch("app.analyzer.notify")
@patch("subprocess.run")
def test_run_fix_rejects_forbidden_file(mock_run, mock_notify):
    import app.analyzer as analyzer

    def side_effect(args, **kwargs):
        if args[:2] == ["git", "diff"] and "--name-only" in args:
            return MagicMock(stdout="docker-compose.yml\n")
        if args[:2] == ["git", "diff"] and "--stat" in args:
            return MagicMock(stdout="1 file changed")
        if args == ["git", "diff"]:
            return MagicMock(stdout="+line1\n")
        return MagicMock(stdout="")

    mock_run.side_effect = side_effect
    row = {"name": "torrentwatch", "repo": "/workspaces/r", "subdir": "torrentwatch"}
    analysis = {"text": "root cause X", "excerpt": "ERROR boom"}
    pr_url = analyzer.run_fix(row, "fp123", analysis, "/workspaces/r/torrentwatch")
    assert pr_url is None
    mock_notify.assert_called_once()
    calls = [c.args[0] for c in mock_run.call_args_list]
    assert not any(c[:2] == ["gh", "pr"] for c in calls)
    assert ["git", "checkout", "-B", "main", "origin/main"] in calls


@patch("app.analyzer.notify")
@patch("subprocess.run")
def test_run_fix_rejects_oversized_diff(mock_run, mock_notify):
    import app.analyzer as analyzer

    big_diff = "\n".join(f"+line{i}" for i in range(250))

    def side_effect(args, **kwargs):
        if args[:2] == ["git", "diff"] and "--name-only" in args:
            return MagicMock(stdout="src/foo.py\n")
        if args[:2] == ["git", "diff"] and "--stat" in args:
            return MagicMock(stdout="1 file changed")
        if args == ["git", "diff"]:
            return MagicMock(stdout=big_diff)
        return MagicMock(stdout="")

    mock_run.side_effect = side_effect
    row = {"name": "torrentwatch", "repo": "/workspaces/r", "subdir": "torrentwatch"}
    analysis = {"text": "root cause X", "excerpt": "ERROR boom"}
    pr_url = analyzer.run_fix(row, "fp123", analysis, "/workspaces/r/torrentwatch")
    assert pr_url is None
    mock_notify.assert_called_once()
    calls = [c.args[0] for c in mock_run.call_args_list]
    assert ["git", "checkout", "-B", "main", "origin/main"] in calls


@patch("app.analyzer.notify")
@patch("subprocess.run")
def test_run_fix_rejects_empty_diff(mock_run, mock_notify):
    import app.analyzer as analyzer

    def side_effect(args, **kwargs):
        if args[:2] == ["git", "diff"] and "--name-only" in args:
            return MagicMock(stdout="")
        if args[:2] == ["git", "diff"] and "--stat" in args:
            return MagicMock(stdout="")
        if args == ["git", "diff"]:
            return MagicMock(stdout="")
        return MagicMock(stdout="")

    mock_run.side_effect = side_effect
    row = {"name": "torrentwatch", "repo": "/workspaces/r", "subdir": "torrentwatch"}
    analysis = {"text": "root cause X", "excerpt": "ERROR boom"}
    pr_url = analyzer.run_fix(row, "fp123", analysis, "/workspaces/r/torrentwatch")
    assert pr_url is None
    mock_notify.assert_called_once()
    calls = [c.args[0] for c in mock_run.call_args_list]
    assert not any(c[:2] == ["gh", "pr"] for c in calls)
    assert ["git", "checkout", "-B", "main", "origin/main"] in calls
