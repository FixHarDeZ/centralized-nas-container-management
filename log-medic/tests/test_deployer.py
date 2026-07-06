import subprocess
from unittest.mock import MagicMock, patch


def _row(name="torrentwatch", subdir="torrentwatch"):
    return {
        "name": name,
        "repo": "/workspaces/centralized-nas-container-management",
        "subdir": subdir,
        "maturity": "stable",
    }


def _init_repo(path):
    def run(args):
        subprocess.run(args, cwd=str(path), check=True, capture_output=True, text=True)
    run(["git", "init", "-b", "main"])
    run(["git", "config", "user.email", "t@e.com"])
    run(["git", "config", "user.name", "T"])
    return run


def test_copy_tracked_files_copies_tracked_and_spares_env(tmp_path):
    """Real-git test: tracked files under subdir are copied; untracked .env and
    data/ in the destination survive untouched; files outside subdir ignored."""
    from app import deployer
    ws = tmp_path / "ws"
    ws.mkdir()
    run = _init_repo(ws)
    (ws / "torrentwatch").mkdir()
    (ws / "torrentwatch" / "main.py").write_text("v2\n")
    (ws / "torrentwatch" / "sub").mkdir()
    (ws / "torrentwatch" / "sub" / "util.py").write_text("u\n")
    (ws / "other-stack").mkdir()
    (ws / "other-stack" / "x.py").write_text("x\n")
    run(["git", "add", "-A"])
    run(["git", "commit", "-m", "init"])

    dest = tmp_path / "stacks" / "torrentwatch"
    dest.mkdir(parents=True)
    (dest / ".env").write_text("SECRET=1\n")
    (dest / "data").mkdir()
    (dest / "data" / "app.db").write_text("blob")
    (dest / "main.py").write_text("v1\n")

    n = deployer.copy_tracked_files(str(ws), "torrentwatch", str(dest))
    assert n == 2
    assert (dest / "main.py").read_text() == "v2\n"
    assert (dest / "sub" / "util.py").read_text() == "u\n"
    assert (dest / ".env").read_text() == "SECRET=1\n"
    assert (dest / "data" / "app.db").read_text() == "blob"
    assert not (dest / "x.py").exists()


@patch("app.deployer.notify")
def test_deploy_self_stack_skips_and_notifies(mock_notify, tmp_path):
    from app import db, deployer
    conn = db.get_conn(str(tmp_path / "t.db"))
    db.init_db(conn)
    db.record_event(conn, "fp1", "log-medic", status="merged")
    ok = deployer.deploy(conn, _row(name="log-medic", subdir="log-medic"), "fp1", "https://github.com/o/r/pull/9")
    assert ok is False
    assert "manually" in mock_notify.call_args.args[0]
    row = conn.execute("SELECT status FROM events WHERE fingerprint='fp1'").fetchone()
    assert row["status"] == "merged"  # terminal, not deploy_failed


@patch("app.deployer.notify")
@patch("app.deployer.copy_tracked_files", return_value=3)
@patch("subprocess.run")
def test_deploy_happy_path(mock_run, mock_copy, mock_notify, tmp_path):
    from app import db, deployer
    conn = db.get_conn(str(tmp_path / "t.db"))
    db.init_db(conn)
    db.record_event(conn, "fp2", "torrentwatch", status="merged")

    mock_run.return_value = MagicMock(returncode=0, stdout="")
    docker_client = MagicMock()
    container = MagicMock()
    container.attrs = {"State": {"Running": True}, "RestartCount": 0}
    docker_client.containers.get.return_value = container

    ok = deployer.deploy(conn, _row(), "fp2", "https://github.com/o/r/pull/10",
                         docker_client=docker_client, sleep=lambda s: None)
    assert ok is True
    row = conn.execute("SELECT status FROM events WHERE fingerprint='fp2'").fetchone()
    assert row["status"] == "deployed"
    assert "🚀" in mock_notify.call_args.args[0]

    calls = [c.args[0] for c in mock_run.call_args_list]
    assert ["git", "fetch", "origin"] in calls
    assert ["git", "checkout", "-B", "main", "origin/main"] in calls
    assert ["git", "reset", "--hard", "origin/main"] in calls
    assert any(c[:3] == ["docker", "compose", "--project-directory"] for c in calls)


@patch("app.deployer.notify")
@patch("app.deployer.copy_tracked_files", return_value=3)
@patch("subprocess.run")
def test_deploy_uses_subdir_not_name_for_stack_dir(mock_run, mock_copy, mock_notify, tmp_path):
    """Regression: name and subdir can diverge (container name != repo path).
    stack_dir / --project-directory must use subdir, not the container name."""
    from app import db, deployer
    conn = db.get_conn(str(tmp_path / "t.db"))
    db.init_db(conn)
    db.record_event(conn, "fp2b", "tw-container", status="merged")

    mock_run.return_value = MagicMock(returncode=0, stdout="")
    docker_client = MagicMock()
    container = MagicMock()
    container.attrs = {"State": {"Running": True}, "RestartCount": 0}
    docker_client.containers.get.return_value = container

    row = _row(name="tw-container", subdir="torrentwatch")
    ok = deployer.deploy(conn, row, "fp2b", "https://github.com/o/r/pull/13",
                         docker_client=docker_client, sleep=lambda s: None)
    assert ok is True

    assert mock_copy.call_args.args[1] == "torrentwatch"

    calls = [c.args[0] for c in mock_run.call_args_list]
    compose_call = next(c for c in calls if c[:3] == ["docker", "compose", "--project-directory"])
    assert compose_call[3] == "/stacks/torrentwatch"
    assert "/stacks/tw-container" not in compose_call


@patch("app.deployer.notify")
@patch("app.deployer.copy_tracked_files", return_value=3)
@patch("subprocess.run")
def test_deploy_compose_failure_marks_deploy_failed(mock_run, mock_copy, mock_notify, tmp_path):
    from app import db, deployer
    conn = db.get_conn(str(tmp_path / "t.db"))
    db.init_db(conn)
    db.record_event(conn, "fp3", "torrentwatch", status="merged")

    def side_effect(args, **kwargs):
        if args[:2] == ["docker", "compose"]:
            raise subprocess.CalledProcessError(1, args, stderr="build failed")
        return MagicMock(returncode=0, stdout="")

    mock_run.side_effect = side_effect
    ok = deployer.deploy(conn, _row(), "fp3", "https://github.com/o/r/pull/11",
                         docker_client=MagicMock(), sleep=lambda s: None)
    assert ok is False
    row = conn.execute("SELECT status FROM events WHERE fingerprint='fp3'").fetchone()
    assert row["status"] == "deploy_failed"
    assert "❌" in mock_notify.call_args.args[0]


@patch("app.deployer.notify")
@patch("app.deployer.copy_tracked_files", return_value=3)
@patch("subprocess.run")
def test_deploy_container_not_running_marks_deploy_failed(mock_run, mock_copy, mock_notify, tmp_path):
    from app import db, deployer
    conn = db.get_conn(str(tmp_path / "t.db"))
    db.init_db(conn)
    db.record_event(conn, "fp4", "torrentwatch", status="merged")

    mock_run.return_value = MagicMock(returncode=0, stdout="")
    docker_client = MagicMock()
    container = MagicMock()
    container.attrs = {"State": {"Running": False}, "RestartCount": 4}
    docker_client.containers.get.return_value = container

    ok = deployer.deploy(conn, _row(), "fp4", "https://github.com/o/r/pull/12",
                         docker_client=docker_client, sleep=lambda s: None)
    assert ok is False
    row = conn.execute("SELECT status FROM events WHERE fingerprint='fp4'").fetchone()
    assert row["status"] == "deploy_failed"
