"""Persistent, owner-scoped Git workspaces."""

import datetime
import fnmatch
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
_REPO_LIMIT = 500
_SLUG = re.compile(r"^[a-z0-9._-]{1,64}$")
_IDENTITY = re.compile(r"^[^\x00-\x1f<>]{0,128}$")
_RECORD_KEYS = {"id", "owner", "url", "branch", "path", "created"}
_BUNDLE_KEYS = _RECORD_KEYS | {"source", "base_sha"}
# Basenames that usually hold credentials; import warns, never blocks.
_SECRET_NAMES = (
    ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*",
    "id_ed25519*", "id_ecdsa*", "credentials*", "*secret*", ".npmrc", ".netrc",
)
_WARNING_LIMIT = 50


def github_repositories(run=subprocess.run):
    """Repositories visible to the worker's gh login, newest push first.

    One gh login serves every desk user in the coding worker, so the list is
    the same for all of them; not signed in returns signed_in False, not 502.
    """
    env = dict(os.environ, GH_PROMPT_DISABLED="1", GIT_TERMINAL_PROMPT="0")
    try:
        if run(["gh", "auth", "token"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
               stderr=subprocess.DEVNULL, timeout=15, check=False, env=env).returncode:
            return {"signed_in": False, "items": []}
        completed = run(
            ["gh", "api", "--paginate", "user/repos?per_page=100&sort=pushed",
             "--jq", ".[] | {name: .full_name, url: .html_url, private: .private}"],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=_GIT_TIMEOUT,
            check=False, env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise WorkspaceError("GitHub is unavailable", 502)
    if completed.returncode:
        raise WorkspaceError("GitHub is unavailable", 502)
    items = []
    for line in completed.stdout.decode("utf-8", "replace").splitlines()[:_REPO_LIMIT]:
        try:
            item = json.loads(line)
        except ValueError:
            continue
        # Only offer what create() will accept.
        if isinstance(item, dict) and isinstance(item.get("url"), str):
            parts = urlsplit(item["url"]).path.strip("/").split("/")
            if (item["url"].startswith("https://github.com/") and len(parts) == 2
                    and all(_GITHUB_PART.fullmatch(part) for part in parts)):
                items.append({"name": "/".join(parts), "url": item["url"],
                              "private": bool(item.get("private"))})
    return {"signed_in": True, "items": items}


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
            cache = self._cache_path(owner, url)
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
            except WorkspaceError:
                self._cleanup_failed_create(cache, workspace_path)
                raise
            except Exception:
                self._cleanup_failed_create(cache, workspace_path)
                raise WorkspaceError("Unable to create workspace", 502)
            return self._start_task(owner, workspace_id, cache, url, base_branch)

    def import_bundle(self, owner, slug, bundle_path, branch="", name="", email=""):
        """Start a task from a git bundle carried in from a machine Git can't reach.

        Bundle branches land under refs/remotes/origin/* so status, rebase and
        delete work as for GitHub tasks. Re-importing a slug fetches into the
        same cache. The bundle file is always removed.
        """
        try:
            owner = self._valid_owner(owner)
            slug = self._valid_slug(slug)
            branch = self._valid_branch(branch)
            name = self._valid_identity(name)
            email = self._valid_identity(email)
            url = "local:" + slug
            with self._lock:
                self._prepare_owner(owner)
                workspace_id = uuid.uuid4().hex
                workspace_path = self.root / "worktrees" / owner / workspace_id
                cache = self._cache_path(owner, url)
                created = not cache.exists()
                if created:
                    self._git("init", "--bare", "-q", os.fspath(cache))
                elif not self._safe_existing_directory(cache):
                    raise WorkspaceError("Invalid workspace storage", 400)
                try:
                    heads, head = self._fetch_bundle(cache, bundle_path)
                    base_branch = branch or self._bundle_default_branch(heads, head)
                    if base_branch not in heads:
                        raise WorkspaceError("Branch is not in the bundle", 400)
                except Exception:
                    if created and self._safe_existing_directory(cache):
                        shutil.rmtree(cache)
                    raise
                if email and not name:
                    # The worker has no global user.name; email alone = git refuses to commit.
                    name = email.split("@", 1)[0]
                identity = {"user.name": name, "user.email": email}
                record = self._start_task(
                    owner, workspace_id, cache, url, base_branch,
                    extra={"source": "bundle"}, identity=identity,
                )
                record = dict(record)
                warnings = self._secret_warnings(record["path"], record["base_sha"])
                if warnings:
                    record["warnings"] = warnings
                return record
        finally:
            try:
                os.unlink(bundle_path)
            except OSError:
                pass

    def update_bundle(self, owner, workspace_id, bundle_path):
        """Fetch a later (usually incremental) bundle into a task's cache."""
        try:
            with self._lock:
                record = self._bundle_record(owner, workspace_id)
                cache = self._cache_path(record["owner"], record["url"])
                if not self._safe_existing_directory(cache):
                    raise WorkspaceError("Invalid workspace storage", 400)
                heads, _ = self._fetch_bundle(cache, bundle_path)
                return {"id": workspace_id, "updated": sorted(heads)}
        finally:
            try:
                os.unlink(bundle_path)
            except OSError:
                pass

    def export_bundle(self, owner, workspace_id, force=False):
        """Bundle the task's own commits (base_sha..desk/<id>); returns (path, filename)."""
        with self._lock:
            record = self._bundle_record(owner, workspace_id)
            path = record["path"]
            try:
                changes = self._git(
                    "-C", path, "status", "--porcelain", "--untracked-files=all"
                )
                count = self._git(
                    "-C", path, "rev-list", "--count",
                    record["base_sha"] + ".." + record["branch"],
                ).strip()
            except WorkspaceError:
                raise WorkspaceError("Unable to inspect workspace", 500)
            if count == "0":
                raise WorkspaceError("Nothing to export: commit the changes first", 409)
            if changes.strip() and not force:
                raise WorkspaceError(
                    "Task has uncommitted changes; export carries commits only", 409
                )
            directory = self.root / "exports" / record["owner"]
            self._make_safe_directory(directory.parent)
            self._make_safe_directory(directory)
            # Unique on disk: two downloads of one task must not share a file
            # the first one deletes. The readable name is only for the client.
            target = directory / (uuid.uuid4().hex + ".bundle")
            self._git(
                "-C", path, "bundle", "create", "-q", os.fspath(target),
                record["base_sha"] + ".." + record["branch"],
            )
            name = "desk-%s-%s.bundle" % (record["url"][len("local:"):], workspace_id[:8])
            return os.fspath(target), name

    def _start_task(self, owner, workspace_id, cache, url, base_branch,
                    extra=None, identity=None):
        workspace_path = self.root / "worktrees" / owner / workspace_id
        try:
            base_ref = "refs/remotes/origin/" + base_branch
            self._git(
                "-C", os.fspath(cache), "show-ref", "--verify", "--quiet", base_ref
            )
            work_branch = "desk/" + workspace_id
            self._git(
                "-C", os.fspath(cache), "worktree", "add", "-q", "-b", work_branch,
                os.fspath(workspace_path), base_ref,
            )
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
            if extra:
                record.update(extra)
                record["base_sha"] = self._git(
                    "-C", os.fspath(workspace_path), "rev-parse", "HEAD"
                ).strip()
            if identity and any(identity.values()):
                # Per-worktree config: tasks sharing one cache keep their own author.
                self._enable_worktree_config(cache)
                for key, value in identity.items():
                    if value:
                        self._git(
                            "-C", os.fspath(workspace_path), "config", "--worktree",
                            key, value,
                        )
        except WorkspaceError:
            self._cleanup_failed_create(cache, workspace_path)
            raise
        except Exception:
            self._cleanup_failed_create(cache, workspace_path)
            raise WorkspaceError("Unable to create workspace", 502)
        try:
            self._write(record)
        except Exception:
            self._cleanup_failed_create(cache, workspace_path)
            raise WorkspaceError("Unable to save workspace", 500)
        return record

    def _enable_worktree_config(self, cache):
        # With worktreeConfig on, core.bare in the shared config would apply to
        # every worktree ("must be run in a work tree"); git-worktree(1) says
        # to move it into the main worktree's own config.worktree.
        cache = os.fspath(cache)
        if self._git("-C", cache, "config", "--default", "", "extensions.worktreeConfig") == "true":
            return
        self._git("-C", cache, "config", "extensions.worktreeConfig", "true")
        self._git("-C", cache, "config", "--worktree", "core.bare", "true")
        self._git("-C", cache, "config", "--unset", "core.bare")

    def _bundle_record(self, owner, workspace_id):
        record = self.get(owner, workspace_id)
        if record.get("source") != "bundle":
            raise WorkspaceError("Task was not imported from a bundle", 400)
        return record

    def _fetch_bundle(self, cache, bundle_path):
        """Verify then fetch a bundle; returns ({branch: sha}, HEAD sha or None)."""
        bundle_path = os.path.abspath(os.fspath(bundle_path))
        try:
            verify = subprocess.run(
                ["git", "-C", os.fspath(cache), "bundle", "verify", bundle_path],
                stdin=subprocess.DEVNULL, capture_output=True, timeout=_GIT_TIMEOUT,
                check=False, env=dict(os.environ, GIT_TERMINAL_PROMPT="0"),
            )
        except (OSError, subprocess.TimeoutExpired):
            raise WorkspaceError("Git operation failed", 502)
        if verify.returncode:
            if b"prerequisite" in verify.stderr:
                raise WorkspaceError(
                    "Bundle builds on commits this project does not have; "
                    "send a full bundle", 409,
                )
            raise WorkspaceError("Not a valid git bundle", 400)
        listing = self._git("-C", os.fspath(cache), "bundle", "list-heads", bundle_path)
        heads = {}
        for line in listing.splitlines():
            fields = line.split()
            if len(fields) != 2:
                raise WorkspaceError("Not a valid git bundle", 400)
            sha, ref = fields
            if ref == "HEAD":
                heads.setdefault("HEAD", sha)
            elif ref.startswith("refs/heads/"):
                heads[self._valid_branch(ref[len("refs/heads/"):])] = sha
            else:
                raise WorkspaceError("Bundle may only contain branches", 400)
        if set(heads) <= {"HEAD"}:
            raise WorkspaceError("Bundle contains no branches", 400)
        self._git(
            "-C", os.fspath(cache), "fetch", "-q", bundle_path,
            "+refs/heads/*:refs/remotes/origin/*",
        )
        head = heads.pop("HEAD", None)
        return heads, head

    def _bundle_default_branch(self, branches, head):
        for preferred in ("main", "master"):
            if preferred in branches and (head is None or branches[preferred] == head):
                return preferred
        for name in sorted(branches):
            if branches[name] == head:
                return name
        for preferred in ("main", "master"):
            if preferred in branches:
                return preferred
        return sorted(branches)[0]

    def _secret_warnings(self, path, sha):
        try:
            names = self._git(
                "-C", path, "ls-tree", "-r", "--name-only", sha, limit=4 * 1024 * 1024
            )
        except WorkspaceError:
            return []
        found = []
        for name in names.splitlines():
            base = name.rsplit("/", 1)[-1].lower()
            if any(fnmatch.fnmatchcase(base, pattern) for pattern in _SECRET_NAMES):
                found.append(name)
                if len(found) >= _WARNING_LIMIT:
                    break
        return found

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

    def delete(self, owner, workspace_id, force=False):
        """Remove a task worktree, its desk/<id> branch, metadata and uploads.

        Refuses (409) while the task has uncommitted files or commits that no
        remote-tracking branch contains, unless force is set. A squash-merged
        branch whose GitHub copy was deleted looks unpushed, hence force.
        """
        with self._lock:
            record = self.get(owner, workspace_id)
            path = record["path"]
            if not force:
                try:
                    changes = self._git(
                        "-C", path, "status", "--porcelain", "--untracked-files=all"
                    )
                    unpushed = self._git(
                        "-C", path, "rev-list", "--count", "HEAD", "--not", "--remotes"
                    ).strip()
                except WorkspaceError:
                    raise WorkspaceError("Unable to inspect workspace", 500)
                if changes.strip():
                    raise WorkspaceError("Task has uncommitted changes", 409)
                if unpushed != "0":
                    raise WorkspaceError(
                        "Task has %s commit(s) not pushed to GitHub" % unpushed, 409
                    )
            cache = self._cache_path(owner, record["url"])
            if not self._safe_existing_directory(cache):
                raise WorkspaceError("Invalid workspace storage", 400)
            try:
                self._git("-C", os.fspath(cache), "worktree", "remove", "--force", path)
            except WorkspaceError:
                raise WorkspaceError("Unable to remove workspace", 500)
            try:
                self._git("-C", os.fspath(cache), "branch", "-D", record["branch"])
            except WorkspaceError:
                pass  # Worktree is gone; a leftover branch only costs a ref.
            (self.root / "metadata" / owner / (workspace_id + ".json")).unlink()
            attachments = self.root / "attachments" / owner / workspace_id
            if self._safe_existing_directory(attachments):
                shutil.rmtree(attachments)
            return {"id": workspace_id, "deleted": True}

    def _cache_path(self, owner, url):
        return self.root / "repositories" / owner / (
            hashlib.sha256(url.encode("utf-8")).hexdigest() + ".git"
        )

    def _valid_owner(self, owner):
        if not isinstance(owner, str) or not _OWNER.fullmatch(owner):
            raise WorkspaceError("Invalid workspace owner", 400)
        return owner

    def _valid_slug(self, slug):
        if not isinstance(slug, str) or not _SLUG.fullmatch(slug) or slug in (".", ".."):
            raise WorkspaceError("Invalid project name", 400)
        return slug

    def _valid_identity(self, value):
        if value is None:
            return ""
        if not isinstance(value, str) or not _IDENTITY.fullmatch(value):
            raise WorkspaceError("Invalid commit identity", 400)
        return value.strip()

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
        if set(record) != _RECORD_KEYS and not (
            set(record) == _BUNDLE_KEYS and record.get("source") == "bundle"
            and record.get("url", "").startswith("local:")
        ):
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
