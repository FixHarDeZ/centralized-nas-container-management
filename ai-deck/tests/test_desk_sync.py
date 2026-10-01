"""desk-sync end to end against the real coding handler behind a fake nginx."""
import base64
import os
import subprocess
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import chat
import workspace_api

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "desk-sync"


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, text=True,
                          capture_output=True).stdout.strip()


class Nginx(chat.Handler):
    """Like the desk's nginx: basic auth user → X-Desk-User, strip /code."""

    def parse_request(self):
        if not super().parse_request():
            return False
        auth = self.headers.get("Authorization", "")
        del self.headers["X-Desk-User"]
        if auth.startswith("Basic "):
            user, _, password = base64.b64decode(auth[6:]).decode().partition(":")
            if password == "pw":
                self.headers["X-Desk-User"] = user
        if self.path.startswith("/code/"):
            self.path = self.path[len("/code"):]
        return True


@pytest.fixture
def desk(tmp_path, monkeypatch):
    monkeypatch.setenv("CODE_WORKER", "1")
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "desk"))
    workspace_api._stores.clear()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Nginx)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    security = bin_dir / "security"
    security.write_text("#!/bin/sh\necho pw\n")
    security.chmod(0o755)
    config = tmp_path / "config"
    config.write_text("DESK_URL=http://127.0.0.1:%d\nDESK_USER=alice\n" % server.server_port)
    env = dict(os.environ, DESK_SYNC_CONFIG=str(config),
               PATH=str(bin_dir) + os.pathsep + os.environ["PATH"])
    yield env
    server.shutdown()
    server.server_close()
    workspace_api._stores.clear()


@pytest.fixture
def mac(tmp_path):
    repo = tmp_path / "My App"
    repo.mkdir()
    git("init", "-q", "-b", "main", cwd=repo)
    git("config", "user.name", "Mac", cwd=repo)
    git("config", "user.email", "mac@example.invalid", cwd=repo)
    (repo / "a.txt").write_text("a\n")
    git("add", ".", cwd=repo)
    git("commit", "-q", "-m", "a", cwd=repo)
    return repo


def sync(env, cwd, *args, ok=True):
    run = subprocess.run([str(SCRIPT), *args], cwd=cwd, env=env, text=True,
                         capture_output=True)
    if ok:
        assert run.returncode == 0, run.stdout + run.stderr
    return run


def test_round_trip(desk, mac):
    out = sync(desk, mac, "up", "--email", "me@work.example").stdout
    assert "started" in out
    task = WorkspaceStore_list()[0]
    assert task["url"] == "local:my-app"
    assert git("config", "user.email", cwd=task["path"]) == "me@work.example"

    assert "nothing new" in sync(desk, mac, "up").stdout

    (mac / "b.txt").write_text("b\n")
    git("add", ".", cwd=mac)
    git("commit", "-q", "-m", "b", cwd=mac)
    sync(desk, mac, "up")
    assert git("rev-parse", "origin/main", cwd=task["path"]) == git("rev-parse", "HEAD", cwd=mac)

    down = sync(desk, mac, "down", ok=False)
    assert down.returncode != 0 and "Nothing to export" in down.stderr

    (Path(task["path"]) / "agent.txt").write_text("agent\n")
    git("add", ".", cwd=task["path"])
    git("commit", "-q", "-m", "agent work", cwd=task["path"])
    (Path(task["path"]) / "dirty.txt").write_text("x\n")
    down = sync(desk, mac, "down", ok=False)
    assert "--force" in down.stderr
    out = sync(desk, mac, "down", "--force").stdout
    assert "agent work" in out
    branch = "desk/" + task["id"]
    assert git("rev-parse", branch, cwd=mac) == git("rev-parse", "HEAD", cwd=task["path"])
    assert "unsent" in sync(desk, mac, "status").stdout

    # Commits made on desk/<id> on the computer are never overwritten.
    git("checkout", "-q", branch, cwd=mac)
    (mac / "mine.txt").write_text("m\n")
    git("add", ".", cwd=mac)
    git("commit", "-q", "-m", "mine", cwd=mac)
    mine = git("rev-parse", "HEAD", cwd=mac)
    run = sync(desk, mac, "down", "--force", ok=False)
    assert run.returncode != 0 and "rename it first" in run.stderr
    assert git("rev-parse", branch, cwd=mac) == mine


def test_first_upload_starts_from_checked_out_branch(desk, mac):
    git("checkout", "-q", "-b", "develop", cwd=mac)
    (mac / "d.txt").write_text("d\n")
    git("add", ".", cwd=mac)
    git("commit", "-q", "-m", "d", cwd=mac)
    sync(desk, mac, "up")
    assert WorkspaceStore_list()[0]["base_sha"] == git("rev-parse", "HEAD", cwd=mac)


def test_bad_password_and_unlinked(desk, mac, tmp_path):
    assert "not linked" in sync(desk, mac, "status").stdout
    (tmp_path / "bin" / "security").write_text("#!/bin/sh\necho wrong\n")
    run = sync(desk, mac, "up", ok=False)
    assert run.returncode != 0 and "401" in run.stderr


def WorkspaceStore_list():
    return workspace_api.store().list("alice")
