"""Persistent, owner-scoped Git workspaces."""

import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path
from urllib.parse import urlsplit


_OWNER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,63})$")
_WORKSPACE_ID = re.compile(r"^[0-9a-f]{32}$")
_GITHUB_PART = re.compile(r"^[A-Za-z0-9_.-]+$")
_DIFF_LIMIT = 64 * 1024
_OUTPUT_LIMIT = 64 * 1024
_GIT_TIMEOUT = 90


class WorkspaceError(Exception):
    """An error safe to expose through the workspace HTTP API."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


class WorkspaceStore:
    """Create and inspect durable Git worktrees below one trusted root."""

    def __init__(self, root, trusted_url_resolver=None):
        self.root = Path(root).expanduser().resolve()
        self._resolve_url = trusted_url_resolver or (lambda url: url)
        self._lock = threading.RLock()

    def list(self, owner):
        owner = self._valid_owner(owner)
        directory = self.root / "metadata" / owner
        if not directory.exists():
            return []
        if not self._safe_existing_directory(directory):
            raise WorkspaceError("Invalid workspace storage", 400)
        records = []
        for path in directory.glob("*.json"):
            workspace_id = path.stem
            try:
                records.append(self._read(owner, workspace_id))
            except WorkspaceError:
                continue
        return sorted(records, key=lambda record: record["created"])

    def create(self, owner, url, branch=""):
        owner = self._valid_owner(owner)
        url = self._valid_url(url)
        branch = self._valid_branch(branch)
        try:
            clone_url = self._resolve_url(url)
        except Exception:
            raise WorkspaceError("Unable to access repository", 502)
        if not isinstance(clone_url, (str, os.PathLike)):
            raise WorkspaceError("Unable to access repository", 502)

        with self._lock:
            self._prepare_owner(owner)
            workspace_id = uuid.uuid4().hex
            workspace_path = self.root / "worktrees" / owner / workspace_id
            cache = self.root / "repositories" / owner / (
                hashlib.sha256(url.encode("utf-8")).hexdigest() + ".git"
            )
            try:
                if not cache.exists():
                    self._git("clone", "--bare", os.fspath(clone_url), os.fspath(cache))
                elif not self._safe_existing_directory(cache):
                    raise WorkspaceError("Invalid workspace storage", 400)

                # Bare clones omit the normal fetch mapping. Persist it so Git
                # commands run inside task worktrees refresh origin/main too.
                self._git(
                    "-C", os.fspath(cache), "config", "--replace-all",
                    "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*",
                )

                self._git(
                    "-C", os.fspath(cache), "fetch", "--prune", "origin",
                    "+refs/heads/*:refs/remotes/origin/*",
                )
                base_branch = branch or self._remote_default_branch(cache)
                base_ref = "refs/remotes/origin/" + base_branch
                self._git(
                    "-C", os.fspath(cache), "show-ref", "--verify", "--quiet", base_ref
                )
                work_branch = "desk/" + workspace_id
                self._git(
                    "-C", os.fspath(cache), "worktree", "add", "-b", work_branch,
                    os.fspath(workspace_path), base_ref,
                )
            except WorkspaceError:
                self._cleanup_failed_create(cache, workspace_path)
                raise
            except Exception:
                self._cleanup_failed_create(cache, workspace_path)
                raise WorkspaceError("Unable to create workspace", 502)

            record = {
                "id": workspace_id,
                "owner": owner,
                "url": url,
                "branch": work_branch,
                "path": os.fspath(workspace_path),
                "created": datetime.datetime.now(
                    datetime.timezone.utc
                ).isoformat().replace("+00:00", "Z"),
            }
            try:
                self._write(record)
            except Exception:
                self._cleanup_failed_create(cache, workspace_path)
                raise WorkspaceError("Unable to save workspace", 500)
            return record

    def get(self, owner, workspace_id):
        owner = self._valid_owner(owner)
        if not isinstance(workspace_id, str) or not _WORKSPACE_ID.fullmatch(workspace_id):
            raise WorkspaceError("Workspace not found", 404)
        return self._read(owner, workspace_id)

    def status(self, owner, workspace_id):
        record = self.get(owner, workspace_id)
        path = record["path"]
        try:
            head = self._git("-C", path, "rev-parse", "HEAD").strip()
            branch = self._git(
                "-C", path, "symbolic-ref", "--short", "HEAD"
            ).strip()
            changes = self._git(
                "-C", path, "status", "--short", "--untracked-files=all"
            )
            diff = self._git(
                "-C", path, "diff", "HEAD", "--no-ext-diff", "--no-color", "--",
                limit=_DIFF_LIMIT,
            )
        except WorkspaceError:
            raise WorkspaceError("Unable to inspect workspace", 500)
        result = dict(record)
        result.update({
            "head": head,
            "branch": branch,
            "changes": changes,
            "diff": diff,
        })
        return result

    def _valid_owner(self, owner):
        if not isinstance(owner, str) or not _OWNER.fullmatch(owner):
            raise WorkspaceError("Invalid workspace owner", 400)
        return owner

    def _valid_url(self, url):
        if not isinstance(url, str):
            raise WorkspaceError("Invalid GitHub repository URL", 400)
        parsed = urlsplit(url)
        parts = parsed.path.strip("/").split("/")
        if (
            parsed.scheme != "https"
            or parsed.hostname != "github.com"
            or parsed.netloc != "github.com"
            or parsed.query
            or parsed.fragment
            or len(parts) != 2
            or not all(_GITHUB_PART.fullmatch(part) for part in parts)
            or parts[1] in ("", ".git")
        ):
            raise WorkspaceError("Invalid GitHub repository URL", 400)
        return url

    def _valid_branch(self, branch):
        if branch is None:
            branch = ""
        if not isinstance(branch, str) or len(branch) > 255:
            raise WorkspaceError("Invalid branch", 400)
        if not branch:
            return ""
        try:
            self._git("check-ref-format", "--branch", branch)
        except WorkspaceError:
            raise WorkspaceError("Invalid branch", 400)
        return branch

    def _remote_default_branch(self, cache):
        output = self._git(
            "-C", os.fspath(cache), "ls-remote", "--symref", "origin", "HEAD"
        )
        for line in output.splitlines():
            fields = line.split()
            if len(fields) == 3 and fields[0] == "ref:" and fields[2] == "HEAD":
                branch = fields[1]
                if branch.startswith("refs/heads/"):
                    branch = branch[len("refs/heads/"):]
                    return self._valid_branch(branch)
        raise WorkspaceError("Git operation failed", 502)

    def _prepare_owner(self, owner):
        for base in ("metadata", "repositories", "worktrees"):
            parent = self.root / base
            child = parent / owner
            self._make_safe_directory(parent)
            self._make_safe_directory(child)

    def _make_safe_directory(self, path):
        if path.is_symlink():
            raise WorkspaceError("Invalid workspace storage", 400)
        path.mkdir(parents=True, exist_ok=True)
        if not self._safe_existing_directory(path):
            raise WorkspaceError("Invalid workspace storage", 400)

    def _safe_existing_directory(self, path):
        try:
            return (
                path.is_dir()
                and not path.is_symlink()
                and path.resolve().is_relative_to(self.root)
            )
        except (OSError, ValueError, AttributeError):
            try:
                path.resolve().relative_to(self.root)
                return path.is_dir() and not path.is_symlink()
            except (OSError, ValueError):
                return False

    def _read(self, owner, workspace_id):
        if not _WORKSPACE_ID.fullmatch(workspace_id):
            raise WorkspaceError("Workspace not found", 404)
        metadata = self.root / "metadata" / owner / (workspace_id + ".json")
        try:
            if (
                not self._safe_existing_directory(metadata.parent)
                or metadata.is_symlink()
                or metadata.resolve().parent != metadata.parent.resolve()
            ):
                raise ValueError
            record = json.loads(metadata.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            raise WorkspaceError("Workspace not found", 404)
        expected_path = self.root / "worktrees" / owner / workspace_id
        expected = {
            "id": workspace_id,
            "owner": owner,
            "path": os.fspath(expected_path),
        }
        if any(record.get(key) != value for key, value in expected.items()):
            raise WorkspaceError("Workspace not found", 404)
        if set(record) != {"id", "owner", "url", "branch", "path", "created"}:
            raise WorkspaceError("Workspace not found", 404)
        if not self._safe_existing_directory(expected_path):
            raise WorkspaceError("Workspace not found", 404)
        return record

    def _write(self, record):
        directory = self.root / "metadata" / record["owner"]
        target = directory / (record["id"] + ".json")
        descriptor, temporary = tempfile.mkstemp(
            prefix="." + record["id"] + ".", suffix=".tmp", dir=directory
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(record, handle, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def _cleanup_failed_create(self, cache, workspace_path):
        if workspace_path.exists() and self._safe_existing_directory(workspace_path):
            shutil.rmtree(workspace_path)
        if cache.exists() and self._safe_existing_directory(cache):
            try:
                self._git("-C", os.fspath(cache), "worktree", "prune")
            except WorkspaceError:
                pass

    def _git(self, *arguments, limit=_OUTPUT_LIMIT):
        stdout = tempfile.TemporaryFile()
        stderr = tempfile.TemporaryFile()
        try:
            completed = subprocess.run(
                ["git", *arguments],
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                timeout=_GIT_TIMEOUT,
                check=False,
                env=dict(os.environ, GIT_TERMINAL_PROMPT="0"),
            )
            if completed.returncode:
                raise WorkspaceError("Git operation failed", 502)
            stdout.seek(0)
            return stdout.read(limit).decode("utf-8", "replace").rstrip("\n")
        except (OSError, subprocess.TimeoutExpired):
            raise WorkspaceError("Git operation failed", 502)
        finally:
            stdout.close()
            stderr.close()
