import subprocess
from pathlib import Path

import pytest

from workspaces import WorkspaceError, WorkspaceStore


def git(*args, cwd=None):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout.strip()


def commit(repo, name, text, message):
    Path(repo, name).parent.mkdir(parents=True, exist_ok=True)
    Path(repo, name).write_text(text, encoding="utf-8")
    git("add", name, cwd=repo)
    git("commit", "-q", "-m", message, cwd=repo)
    return git("rev-parse", "HEAD", cwd=repo)


@pytest.fixture
def mac(tmp_path):
    repo = tmp_path / "mac"
    repo.mkdir()
    git("init", "-q", "-b", "main", cwd=repo)
    git("config", "user.name", "Mac", cwd=repo)
    git("config", "user.email", "mac@example.invalid", cwd=repo)
    commit(repo, "README.md", "main\n", "initial")
    git("checkout", "-q", "-b", "release", cwd=repo)
    commit(repo, "branch.txt", "release\n", "release")
    git("checkout", "-q", "main", cwd=repo)
    return repo


@pytest.fixture
def store(tmp_path):
    return WorkspaceStore(tmp_path / "workspaces")


def bundle(repo, tmp_path, name, *revs):
    path = tmp_path / name
    git("bundle", "create", "-q", str(path), *(revs or ("--all",)), cwd=repo)
    return path


def agent_commit(record, name="feature.txt"):
    path = record["path"]
    git("config", "user.name", "Agent", cwd=path)
    git("config", "user.email", "agent@example.invalid", cwd=path)
    return commit(path, name, "work\n", "agent work")


def test_import_full_bundle_starts_task_on_default_branch(store, mac, tmp_path):
    made = store.import_bundle("alice", "app", bundle(mac, tmp_path, "a.bundle"))

    assert made["source"] == "bundle"
    assert made["url"] == "local:app"
    assert made["branch"] == "desk/" + made["id"]
    assert made["base_sha"] == git("rev-parse", "main", cwd=mac)
    assert Path(made["path"], "README.md").read_text() == "main\n"
    assert not (tmp_path / "a.bundle").exists()
    assert "warnings" not in store.get("alice", made["id"])
    assert store.list("alice")[0]["source"] == "bundle"


def test_import_honours_branch_and_rejects_missing_one(store, mac, tmp_path):
    made = store.import_bundle(
        "alice", "app", bundle(mac, tmp_path, "a.bundle"), branch="release"
    )
    assert Path(made["path"], "branch.txt").read_text() == "release\n"

    with pytest.raises(WorkspaceError) as caught:
        store.import_bundle("bob", "app", bundle(mac, tmp_path, "b.bundle"), branch="nope")
    assert caught.value.status == 400
    assert not (store.root / "repositories" / "bob").exists() or not any(
        (store.root / "repositories" / "bob").iterdir()
    )
    assert store.list("bob") == []


def test_default_branch_follows_bundle_head(store, mac, tmp_path):
    git("checkout", "-q", "-b", "develop", cwd=mac)
    tip = commit(mac, "dev.txt", "dev\n", "dev")
    made = store.import_bundle(
        "alice", "app", bundle(mac, tmp_path, "a.bundle", "--branches", "HEAD")
    )
    assert made["base_sha"] == tip


def test_corrupt_bundle_is_rejected_and_leaves_nothing(store, tmp_path):
    junk = tmp_path / "junk.bundle"
    junk.write_bytes(b"not a bundle\n")
    with pytest.raises(WorkspaceError) as caught:
        store.import_bundle("alice", "app", junk)
    assert caught.value.status == 400
    assert not junk.exists()
    assert not any((store.root / "repositories" / "alice").glob("*"))


def test_bundle_without_branches_is_rejected(store, mac, tmp_path):
    git("tag", "v1", cwd=mac)
    path = tmp_path / "tag.bundle"
    git("bundle", "create", "-q", str(path), "refs/tags/v1", cwd=mac)
    with pytest.raises(WorkspaceError) as caught:
        store.import_bundle("alice", "app", path)
    assert caught.value.status == 400


@pytest.mark.parametrize("slug", ["../x", "App", "", ".", "..", "a" * 65, "a/b"])
def test_invalid_slug(store, mac, tmp_path, slug):
    with pytest.raises(WorkspaceError) as caught:
        store.import_bundle("alice", slug, bundle(mac, tmp_path, "a.bundle"))
    assert caught.value.status == 400


def test_identity_is_per_task(store, mac, tmp_path):
    first = store.import_bundle(
        "alice", "app", bundle(mac, tmp_path, "a.bundle"),
        name="Work Name", email="me@work.example",
    )
    second = store.import_bundle("alice", "app", bundle(mac, tmp_path, "b.bundle"))
    assert git("config", "user.email", cwd=first["path"]) == "me@work.example"
    assert git("config", "user.name", cwd=first["path"]) == "Work Name"
    # worktreeConfig must not leak the cache's core.bare into task worktrees
    for made in (first, second):
        git("status", "--porcelain", cwd=made["path"])
    assert agent_commit(second)
    assert subprocess.run(
        ["git", "config", "--worktree", "user.email"], cwd=second["path"],
        stdout=subprocess.PIPE, text=True,
    ).stdout.strip() == ""


def test_invalid_email_rejected(store, mac, tmp_path):
    with pytest.raises(WorkspaceError):
        store.import_bundle(
            "alice", "app", bundle(mac, tmp_path, "a.bundle"), email="x\ny"
        )


def test_credential_shaped_files_are_warned(store, mac, tmp_path):
    commit(mac, ".env", "A=1\n", "env")
    commit(mac, "deploy/key.pem", "k\n", "pem")
    made = store.import_bundle("alice", "app", bundle(mac, tmp_path, "a.bundle"))
    assert made["warnings"] == [".env", "deploy/key.pem"]


def test_update_fetches_new_commits_without_touching_worktree(store, mac, tmp_path):
    made = store.import_bundle("alice", "app", bundle(mac, tmp_path, "a.bundle"))
    old = git("rev-parse", "main", cwd=mac)
    new = commit(mac, "later.txt", "x\n", "later")
    store.update_bundle("alice", made["id"], bundle(mac, tmp_path, "u.bundle", old + "..main"))

    assert git("rev-parse", "refs/remotes/origin/main", cwd=made["path"]) == new
    assert not Path(made["path"], "later.txt").exists()
    assert not (tmp_path / "u.bundle").exists()


def test_update_missing_prerequisite_is_409(store, mac, tmp_path):
    made = store.import_bundle(
        "alice", "app", bundle(mac, tmp_path, "a.bundle", "main")
    )
    one = commit(mac, "x.txt", "1\n", "one")
    commit(mac, "y.txt", "2\n", "two")
    with pytest.raises(WorkspaceError) as caught:
        store.update_bundle("alice", made["id"], bundle(mac, tmp_path, "u.bundle", one + "..main"))
    assert caught.value.status == 409
    assert "full bundle" in caught.value.message


def test_update_rejects_github_workspace(tmp_path, mac):
    remote = tmp_path / "remote.git"
    git("clone", "-q", "--bare", str(mac), str(remote))
    public = "https://github.com/example/project.git"
    store = WorkspaceStore(tmp_path / "ws", trusted_url_resolver=lambda url: str(remote))
    made = store.create("alice", public)
    with pytest.raises(WorkspaceError) as caught:
        store.update_bundle("alice", made["id"], bundle(mac, tmp_path, "u.bundle"))
    assert caught.value.status == 400
    with pytest.raises(WorkspaceError) as caught:
        store.export_bundle("alice", made["id"])
    assert caught.value.status == 400


def test_export_round_trips_only_task_commits(store, mac, tmp_path):
    made = store.import_bundle("alice", "app", bundle(mac, tmp_path, "a.bundle"))
    tip = agent_commit(made)

    out, name = store.export_bundle("alice", made["id"])
    assert name == "desk-app-%s.bundle" % made["id"][:8]
    assert store.export_bundle("alice", made["id"])[0] != out  # no shared file
    heads = git("bundle", "list-heads", out, cwd=mac)
    assert heads == "%s refs/heads/desk/%s" % (tip, made["id"])
    verify = subprocess.run(
        ["git", "bundle", "verify", out], cwd=mac, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    ).stdout
    assert made["base_sha"] in verify  # prerequisite = task start

    branch = "desk/" + made["id"]
    git("fetch", "-q", out, "%s:refs/heads/%s" % (branch, branch), cwd=mac)
    assert git("rev-parse", branch, cwd=mac) == tip


def test_export_nothing_new_and_dirty(store, mac, tmp_path):
    made = store.import_bundle("alice", "app", bundle(mac, tmp_path, "a.bundle"))
    with pytest.raises(WorkspaceError) as caught:
        store.export_bundle("alice", made["id"])
    assert caught.value.status == 409 and "nothing" in caught.value.message.lower()

    agent_commit(made)
    Path(made["path"], "dirty.txt").write_text("x\n")
    with pytest.raises(WorkspaceError) as caught:
        store.export_bundle("alice", made["id"])
    assert caught.value.status == 409 and "uncommitted" in caught.value.message
    assert Path(store.export_bundle("alice", made["id"], force=True)[0]).exists()


def test_export_is_owner_scoped(store, mac, tmp_path):
    made = store.import_bundle("alice", "app", bundle(mac, tmp_path, "a.bundle"))
    agent_commit(made)
    with pytest.raises(WorkspaceError) as caught:
        store.export_bundle("bob", made["id"])
    assert caught.value.status == 404


def test_delete_bundle_task(store, mac, tmp_path):
    made = store.import_bundle("alice", "app", bundle(mac, tmp_path, "a.bundle"))
    assert store.delete("alice", made["id"])["deleted"]
    assert store.list("alice") == []


# --- HTTP adapter -----------------------------------------------------------

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer


@pytest.fixture
def server(tmp_path, monkeypatch):
    import chat
    import workspace_api
    monkeypatch.setenv("CODE_WORKER", "1")
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "api"))
    workspace_api._stores.clear()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), chat.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%s" % httpd.server_port
    httpd.shutdown()
    httpd.server_close()
    workspace_api._stores.clear()


def call(url, method="GET", data=None, user="alice"):
    headers = {"X-Desk-User": user} if user else {}
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def test_api_import_update_export_round_trip(server, mac, tmp_path):
    status, _, body = call(
        server + "/projects/bundle?slug=app&email=me%40work.example", "PUT",
        bundle(mac, tmp_path, "a.bundle").read_bytes(),
    )
    assert status == 201, body
    made = json.loads(body)
    assert made["source"] == "bundle"
    assert not list((tmp_path / "api" / "incoming" / "alice").iterdir())

    status, _, body = call(server + "/projects", user="alice")
    assert json.loads(body)["items"][0]["source"] == "bundle"

    old = git("rev-parse", "main", cwd=mac)
    commit(mac, "later.txt", "x\n", "later")
    status, _, body = call(
        server + "/projects/bundle?workspace=" + made["id"], "PUT",
        bundle(mac, tmp_path, "u.bundle", old + "..main").read_bytes(),
    )
    assert status == 200, body

    status, _, body = call(server + "/projects/export?workspace=" + made["id"])
    assert status == 409

    tip = agent_commit(made)
    status, headers, body = call(server + "/projects/export?workspace=" + made["id"])
    assert status == 200
    assert headers["Content-Type"] == "application/octet-stream"
    assert "desk-app-" in headers["Content-Disposition"]
    out = tmp_path / "down.bundle"
    out.write_bytes(body)
    assert git("bundle", "list-heads", str(out), cwd=mac).split()[0] == tip

    status, _, _ = call(server + "/projects/export?workspace=" + made["id"], user="bob")
    assert status == 404


def test_api_bundle_rejections(server, tmp_path):
    assert call(server + "/projects/bundle?slug=app", "PUT", b"x", user=None)[0] == 401
    assert call(server + "/projects/bundle?slug=app", "PUT", b"junk")[0] == 400
    assert call(server + "/projects/bundle?slug=..", "PUT", b"junk")[0] == 400
    assert call(server + "/projects/bundle", "PUT", b"junk")[0] == 400
    incoming = tmp_path / "api" / "incoming" / "alice"
    assert not incoming.exists() or not list(incoming.iterdir())


def test_api_bundle_size_limit(server, monkeypatch):
    import workspace_api
    monkeypatch.setattr(workspace_api, "MAX_BUNDLE_BYTES", 10)
    assert call(server + "/projects/bundle?slug=app", "PUT", b"x" * 11)[0] == 413
