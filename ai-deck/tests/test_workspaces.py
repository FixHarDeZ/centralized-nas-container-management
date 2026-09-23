import concurrent.futures
import json
import subprocess
from pathlib import Path

import pytest

from workspaces import WorkspaceError, WorkspaceStore


def git(*args, cwd=None):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout.strip()


@pytest.fixture
def repository(tmp_path):
    source = tmp_path / "source"
    remote = tmp_path / "remote.git"
    source.mkdir()
    git("init", "-b", "main", cwd=source)
    git("config", "user.name", "Test", cwd=source)
    git("config", "user.email", "test@example.invalid", cwd=source)
    (source / "README.md").write_text("main\n", encoding="utf-8")
    git("add", "README.md", cwd=source)
    git("commit", "-m", "initial", cwd=source)
    git("checkout", "-b", "release", cwd=source)
    (source / "branch.txt").write_text("release\n", encoding="utf-8")
    git("add", "branch.txt", cwd=source)
    git("commit", "-m", "release", cwd=source)
    git("checkout", "main", cwd=source)
    git("clone", "--bare", str(source), str(remote))
    git("symbolic-ref", "HEAD", "refs/heads/main", cwd=remote)
    return remote


@pytest.fixture
def store(tmp_path, repository):
    public = "https://github.com/example/project.git"
    return WorkspaceStore(
        tmp_path / "workspaces",
        trusted_url_resolver=lambda url: str(repository) if url == public else url,
    )


def test_create_clones_and_makes_independent_persistent_worktrees(store):
    first = store.create("alice", "https://github.com/example/project.git")
    second = store.create("alice", "https://github.com/example/project.git")

    assert first["id"] != second["id"]
    assert first["branch"] == f"desk/{first['id']}"
    assert Path(first["path"], "README.md").read_text() == "main\n"
    Path(first["path"], "only-first.txt").write_text("dirty\n")
    assert not Path(second["path"], "only-first.txt").exists()

    reopened = WorkspaceStore(store.root)
    assert reopened.get("alice", first["id"]) == first
    assert {item["id"] for item in reopened.list("alice")} == {
        first["id"], second["id"],
    }


def test_normal_fetch_updates_remote_tracking_branch(store, repository):
    made = store.create("alice", "https://github.com/example/project.git")
    before = git("rev-parse", "refs/remotes/origin/main", cwd=made["path"])
    git("update-ref", "refs/heads/main", "refs/heads/release", cwd=repository)
    expected = git("rev-parse", "refs/heads/main", cwd=repository)
    assert expected != before
    git("fetch", "origin", "main", cwd=made["path"])
    assert git("rev-parse", "refs/remotes/origin/main", cwd=made["path"]) == expected


def test_requested_branch_is_the_start_point(store):
    made = store.create(
        "alice", "https://github.com/example/project.git", branch="release"
    )
    assert Path(made["path"], "branch.txt").read_text() == "release\n"


def test_pushed_workspace_branch_does_not_block_later_creation(store):
    first = store.create("alice", "https://github.com/example/project.git")
    path = Path(first["path"])
    git("config", "user.name", "Test", cwd=path)
    git("config", "user.email", "test@example.invalid", cwd=path)
    (path / "pushed.txt").write_text("pushed\n", encoding="utf-8")
    git("add", "pushed.txt", cwd=path)
    git("commit", "-m", "workspace change", cwd=path)
    git("push", "-u", "origin", first["branch"], cwd=path)

    second = store.create("alice", "https://github.com/example/project.git")
    assert second["id"] != first["id"]
    assert Path(second["path"], "README.md").read_text() == "main\n"


def test_default_branch_is_refreshed_from_remote_head(store, repository):
    first = store.create("alice", "https://github.com/example/project.git")
    assert not Path(first["path"], "branch.txt").exists()

    git("symbolic-ref", "HEAD", "refs/heads/release", cwd=repository)
    second = store.create("alice", "https://github.com/example/project.git")
    assert Path(second["path"], "branch.txt").read_text() == "release\n"


def test_status_reports_head_changes_and_a_bounded_diff(store):
    made = store.create("alice", "https://github.com/example/project.git")
    path = Path(made["path"])
    (path / "README.md").write_text("changed\n" + ("x" * 200_000), encoding="utf-8")
    (path / "new.txt").write_text("untracked\n", encoding="utf-8")

    status = store.status("alice", made["id"])
    assert status["head"] == git("rev-parse", "HEAD", cwd=path)
    assert status["branch"] == made["branch"]
    assert " M README.md" in status["changes"]
    assert "?? new.txt" in status["changes"]
    assert "changed" in status["diff"]
    assert len(status["diff"].encode()) <= 65_536


def test_status_diff_includes_staged_changes(store):
    made = store.create("alice", "https://github.com/example/project.git")
    path = Path(made["path"])
    (path / "README.md").write_text("staged\n", encoding="utf-8")
    git("add", "README.md", cwd=path)

    status = store.status("alice", made["id"])
    assert "M  README.md" in status["changes"]
    assert "+staged" in status["diff"]
    assert len(status["diff"].encode()) <= 65_536


@pytest.mark.parametrize("owner", ["", "../alice", "a/b", ".", "a" * 65])
def test_owner_is_a_safe_single_path_component(tmp_path, owner):
    with pytest.raises(WorkspaceError) as caught:
        WorkspaceStore(tmp_path / "root").list(owner)
    assert caught.value.status == 400


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/example/project.git",
        "https://gitlab.com/example/project.git",
        "https://user:secret@github.com/example/project.git",
        "https://github.com/example/project.git?token=secret",
        "file:///tmp/project.git",
        "git@github.com:example/project.git",
    ],
)
def test_only_plain_github_https_urls_are_accepted(tmp_path, url):
    with pytest.raises(WorkspaceError) as caught:
        WorkspaceStore(tmp_path / "root").create("alice", url)
    assert (caught.value.status, caught.value.message) == (
        400, "Invalid GitHub repository URL"
    )


def test_missing_repository_has_a_sanitized_error(tmp_path):
    secret = "never-show-this"
    store = WorkspaceStore(
        tmp_path / "root",
        trusted_url_resolver=lambda _url: str(tmp_path / secret / "missing.git"),
    )
    with pytest.raises(WorkspaceError) as caught:
        store.create("alice", "https://github.com/example/missing.git")
    assert caught.value.status == 502
    assert secret not in caught.value.message
    assert "missing.git" not in caught.value.message


def test_cross_owner_and_invalid_ids_are_not_found(store):
    made = store.create("alice", "https://github.com/example/project.git")
    for owner, workspace_id in (("bob", made["id"]), ("alice", "../metadata")):
        with pytest.raises(WorkspaceError) as caught:
            store.get(owner, workspace_id)
        assert caught.value.status == 404


def test_metadata_cannot_redirect_get_outside_the_store(store, tmp_path):
    made = store.create("alice", "https://github.com/example/project.git")
    metadata = Path(store.root, "metadata", "alice", made["id"] + ".json")
    record = json.loads(metadata.read_text())
    record["path"] = str(tmp_path)
    metadata.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(WorkspaceError) as caught:
        store.get("alice", made["id"])
    assert caught.value.status == 404


def test_symlinked_metadata_directory_cannot_be_read(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    workspace_id = "a" * 32
    outside.mkdir()
    (root / "metadata").mkdir(parents=True)
    (root / "metadata" / "alice").symlink_to(outside, target_is_directory=True)
    workspace = root / "worktrees" / "alice" / workspace_id
    workspace.mkdir(parents=True)
    record = {
        "id": workspace_id,
        "owner": "alice",
        "url": "https://github.com/example/project.git",
        "branch": "desk/" + workspace_id,
        "path": str(workspace),
        "created": "2026-09-20T00:00:00Z",
    }
    (outside / (workspace_id + ".json")).write_text(
        json.dumps(record), encoding="utf-8"
    )
    with pytest.raises(WorkspaceError) as caught:
        WorkspaceStore(root).get("alice", workspace_id)
    assert caught.value.status == 404


def test_symlinked_owner_directory_cannot_escape(tmp_path, repository):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "worktrees").mkdir(parents=True)
    (root / "worktrees" / "alice").symlink_to(outside, target_is_directory=True)
    store = WorkspaceStore(root, trusted_url_resolver=lambda _url: str(repository))
    with pytest.raises(WorkspaceError) as caught:
        store.create("alice", "https://github.com/example/project.git")
    assert caught.value.status == 400
    assert not list(outside.iterdir())


def test_concurrent_creates_have_unique_complete_metadata(store):
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        made = list(pool.map(
            lambda _: store.create(
                "alice", "https://github.com/example/project.git"
            ),
            range(4),
        ))
    assert len({item["id"] for item in made}) == 4
    assert len(store.list("alice")) == 4
    assert all(Path(item["path"]).is_dir() for item in made)
