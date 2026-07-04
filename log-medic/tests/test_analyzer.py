import subprocess
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


def test_rejection_cleanup_sequence_leaves_working_tree_clean(tmp_path):
    """Real-git integration test: proves checkout -B / reset --hard / clean -fd
    actually leaves a clean working tree after a no-op branch cut, which is the
    exact scenario check_dirty_repo's `git status --porcelain` trips on.

    No subprocess mocking here on purpose -- mocked-subprocess tests only prove
    the commands were *called*, not that they clean the tree, which is how the
    original bug slipped past the prior fix round's tests.
    """
    repo_dir = str(tmp_path)

    def run(args):
        subprocess.run(args, cwd=repo_dir, check=True, capture_output=True, text=True)

    run(["git", "init", "-b", "main"])
    run(["git", "config", "user.email", "test@example.com"])
    run(["git", "config", "user.name", "Test"])
    (tmp_path / "a.txt").write_text("original\n")
    run(["git", "add", "-A"])
    run(["git", "commit", "-m", "init"])

    # Fix branch cut from main with zero commits (mirrors a fix branch cut
    # from origin/main that Claude never committed to before rejection).
    run(["git", "checkout", "-b", "fix/test"])
    (tmp_path / "a.txt").write_text("claude edited this\n")  # dirty tracked file
    (tmp_path / "b.txt").write_text("new file\n")  # untracked file

    # The cleanup sequence under test.
    run(["git", "checkout", "-B", "main", "main"])
    run(["git", "reset", "--hard", "main"])
    run(["git", "clean", "-fd"])
    run(["git", "branch", "-D", "fix/test"])

    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo_dir, capture_output=True, text=True
    ).stdout.strip()
    assert status == ""
