from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time

import docker

from app import db
from app.locks import workspace_lock
from app.notifier import notify

logger = logging.getLogger(__name__)

STACKS_ROOT = os.environ.get("STACKS_ROOT", "/stacks")
SELF_STACK = "log-medic"
COMPOSE_TIMEOUT_SECONDS = 600
VERIFY_DELAY_SECONDS = 60


def _workspace_repo_root(container_row) -> str:
    repo = (container_row["repo"] or "").rstrip("/")
    return os.path.join("/workspaces", os.path.basename(repo))


def copy_tracked_files(workspace_repo_root: str, subdir: str, dest_stack_dir: str) -> int:
    """Copy git-tracked files under subdir into the runtime stack dir.
    Never deletes anything at the destination, so .env / data volumes /
    .htpasswd living only on the NAS are structurally untouchable."""
    listed = subprocess.run(
        ["git", "ls-files", "-z", subdir],
        cwd=workspace_repo_root, capture_output=True, text=True, check=True,
    ).stdout
    files = [f for f in listed.split("\0") if f]
    prefix = subdir.rstrip("/") + "/"
    for tracked in files:
        rel = tracked[len(prefix):] if tracked.startswith(prefix) else tracked
        src = os.path.join(workspace_repo_root, tracked)
        dst = os.path.join(dest_stack_dir, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
    return len(files)


def deploy(conn, container_row, fingerprint: str, pr_url: str, docker_client=None, sleep=time.sleep) -> bool:
    name = container_row["name"]
    subdir = (container_row["subdir"] or "").strip("/")

    if subdir == SELF_STACK:
        notify(f"⚠️ PR merged for {SELF_STACK} itself — deploy manually from workstation\n{pr_url}")
        return False

    repo_root = _workspace_repo_root(container_row)
    stack_dir = os.path.join(STACKS_ROOT, subdir)
    step = "sync_workspace"
    try:
        with workspace_lock:
            subprocess.run(["git", "fetch", "origin"], cwd=repo_root, check=True, capture_output=True, text=True)
            subprocess.run(["git", "checkout", "-B", "main", "origin/main"], cwd=repo_root, check=True, capture_output=True, text=True)
            subprocess.run(["git", "reset", "--hard", "origin/main"], cwd=repo_root, check=True, capture_output=True, text=True)

            step = "copy_files"
            copied = copy_tracked_files(repo_root, subdir, stack_dir)

        step = "compose_up"
        subprocess.run(
            ["docker", "compose", "--project-directory", stack_dir,
             "-f", os.path.join(stack_dir, "docker-compose.yml"),
             "up", "-d", "--build"],
            check=True, capture_output=True, text=True, timeout=COMPOSE_TIMEOUT_SECONDS,
        )

        step = "verify"
        client = docker_client or docker.from_env()
        baseline = client.containers.get(name).attrs.get("RestartCount", 0)
        sleep(VERIFY_DELAY_SECONDS)
        container = client.containers.get(name)
        running = container.attrs["State"]["Running"]
        restarts = container.attrs.get("RestartCount", 0)
        if not running or restarts > baseline:
            raise RuntimeError(f"container not healthy (running={running}, restarts={restarts})")
    except Exception as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        logger.exception("deploy failed for %s at %s", name, step)
        db.update_event_status(conn, fingerprint, name, status="deploy_failed")
        notify(
            f"❌ Deploy failed for {name} at step {step}: {str(detail)[:300]}\n"
            f"Recovery: fix forward or revert on the workstation, then redeploy manually (./scripts/deploy.sh)."
        )
        return False

    with workspace_lock:
        subprocess.run(["git", "branch", "-D", f"fix/{fingerprint}"],
                       cwd=repo_root, capture_output=True, text=True)  # best-effort local cleanup

    db.update_event_status(conn, fingerprint, name, status="deployed")
    notify(f"🚀 Deployed {name} ({copied} files) — PR merged: {pr_url}")
    return True
