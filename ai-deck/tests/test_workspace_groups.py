import json
import sys
from pathlib import Path

import pytest

from workspaces import WorkspaceError

sys.path.insert(0, str(Path(__file__).parent))
from test_workspace_bundles import (  # noqa: F401 - fixtures
    agent_commit, bundle, call, git, mac, server, store,
)


@pytest.fixture
def two(store, mac, tmp_path):
    pipeline = store.import_bundle("alice", "pipeline", bundle(mac, tmp_path, "p.bundle"))
    library = store.import_bundle("alice", "library", bundle(mac, tmp_path, "l.bundle"))
    return pipeline, library


def test_group_nests_real_worktrees_and_members_still_export(store, two):
    pipeline, library = two
    group = store.create_group("alice", "jenkins", [pipeline["id"], library["id"]])

    root = Path(group["path"])
    assert group["source"] == "group" and group["url"] == "group:jenkins"
    for slug in ("pipeline", "library"):
        assert (root / slug).is_dir() and not (root / slug).is_symlink()
        assert (root / slug / "README.md").exists()
    assert "Commit in each repository" in (root / "CLAUDE.md").read_text()
    assert (root / "AGENTS.md").exists()
    assert not (root / ".git").exists()

    moved = store.get("alice", library["id"])
    assert moved["path"] == str(root / "library") and moved["group"] == group["id"]
    tip = agent_commit(moved)
    path, _ = store.export_bundle("alice", library["id"])
    assert tip in git("bundle", "list-heads", path)

    status = store.status("alice", group["id"])
    repos = {item["slug"]: item for item in status["repositories"]}
    assert repos["library"]["commits"] == 1 and repos["pipeline"]["commits"] == 0
    with pytest.raises(WorkspaceError):
        store.export_bundle("alice", group["id"])


def test_group_rejections(store, two, mac, tmp_path):
    pipeline, library = two
    with pytest.raises(WorkspaceError):
        store.create_group("alice", "g", [pipeline["id"]])
    with pytest.raises(WorkspaceError):
        store.create_group("alice", "g", [pipeline["id"], pipeline["id"]])
    with pytest.raises(WorkspaceError):
        store.create_group("bob", "g", [pipeline["id"], library["id"]])
    again = store.import_bundle("alice", "pipeline", bundle(mac, tmp_path, "p2.bundle"))
    with pytest.raises(WorkspaceError, match="different projects"):
        store.create_group("alice", "g", [pipeline["id"], again["id"]])
    group = store.create_group("alice", "g", [pipeline["id"], library["id"]])
    with pytest.raises(WorkspaceError, match="already"):
        store.create_group("alice", "h", [pipeline["id"], again["id"]])
    with pytest.raises(WorkspaceError):
        store.create_group("alice", "h", [group["id"], again["id"]])
    # Failed attempts leave members where they were.
    assert store.get("alice", again["id"])["path"].endswith(again["id"])


def test_ungroup_moves_members_back_and_member_delete_updates_group(store, two):
    pipeline, library = two
    group = store.create_group("alice", "jenkins", [pipeline["id"], library["id"]])
    assert store.delete("alice", library["id"])["deleted"]
    assert store.get("alice", group["id"])["members"] == [pipeline["id"]]

    assert store.delete("alice", group["id"])["deleted"]
    back = store.get("alice", pipeline["id"])
    assert "group" not in back and back["path"].endswith(pipeline["id"])
    assert Path(back["path"], "README.md").exists()
    assert not Path(group["path"]).exists()
    assert [item["id"] for item in store.list("alice")] == [pipeline["id"]]


def test_api_group(server, mac, tmp_path):
    ids = []
    for slug in ("pipeline", "library"):
        status, _, body = call(server + "/projects/bundle?slug=" + slug, "PUT",
                               bundle(mac, tmp_path, slug + ".bundle").read_bytes())
        ids.append(json.loads(body)["id"])
    payload = json.dumps({"name": "jenkins", "members": ids}).encode()
    status, _, body = call(server + "/projects/group", "POST", payload)
    assert status == 415
    import urllib.request
    request = urllib.request.Request(server + "/projects/group", data=payload, method="POST",
                                     headers={"X-Desk-User": "alice",
                                              "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.status == 201
        group = json.loads(response.read())
    status, _, body = call(server + "/projects/status?workspace=" + group["id"])
    assert status == 200 and len(json.loads(body)["repositories"]) == 2
    status, _, _ = call(server + "/projects/export?workspace=" + group["id"])
    assert status == 400
    status, _, body = call(server + "/projects")
    assert {item["source"] for item in json.loads(body)["items"]} == {"bundle", "group"}


def test_ungroup_refuses_to_drop_files_left_at_group_root(store, two):
    pipeline, library = two
    group = store.create_group("alice", "jenkins", [pipeline["id"], library["id"]])
    notes = Path(group["path"], "notes.md")
    notes.write_text("plan\n")
    with pytest.raises(WorkspaceError, match="notes.md") as caught:
        store.delete("alice", group["id"])
    assert caught.value.status == 409 and notes.exists()
    assert store.get("alice", library["id"])["group"] == group["id"]
    assert store.delete("alice", group["id"], force=True)["deleted"]
    assert "group" not in store.get("alice", library["id"])


def test_agent_follows_task_after_it_moves(monkeypatch):
    import chat
    monkeypatch.setattr(chat, "AGENTS", {})
    first = chat.agent_for("alice", "claude", "a" * 32, "/old")
    assert chat.agent_for("alice", "claude", "a" * 32, "/old") is first
    moved = chat.agent_for("alice", "claude", "a" * 32, "/new")
    assert moved is not first and moved.cwd == "/new"
    moved.busy = True
    with pytest.raises(chat.TaskMoved):
        chat.agent_for("alice", "claude", "a" * 32, "/newer")
