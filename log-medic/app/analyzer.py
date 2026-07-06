from __future__ import annotations

import json
import os
import re
import subprocess

from app.locks import workspace_lock
from app.notifier import notify

PHASE1_ALLOWED_TOOLS = "Read,Grep,Glob,Bash(git log:*),Bash(git diff:*)"
PHASE1_TIMEOUT_SECONDS = 600
PHASE2_ALLOWED_TOOLS = "Read,Grep,Glob,Edit,Write"
PHASE2_TIMEOUT_SECONDS = 900
FORBIDDEN_FIX_FILES = re.compile(r"(^|/)(\.env\S*|docker-compose\S*\.ya?ml|\S+\.db)$")
MAX_DIFF_LINES = 200

_VERDICT_RE = re.compile(r"^\s*VERDICT:\s*(code|infra)\s*$", re.IGNORECASE)


def parse_verdict(raw_text: str) -> tuple[str, str]:
    """Extract mandatory VERDICT first line. Fail-safe: anything
    unparseable defaults to 'infra' so malformed response never triggers fix
    runner; in case of error, text returned untouched so notification shows it."""
    first, _, rest = raw_text.partition("\n")
    m = _VERDICT_RE.match(first)
    if m:
        return m.group(1).lower(), rest.strip()
    return "infra", raw_text.strip()


_FIX_PROMPT_TEMPLATE = """You are fixing a bug in `{container}` based on this root-cause analysis:

{analysis}

Make the minimal code change needed. Do NOT edit `.env*`, `docker-compose*.yml`,
or any `*.db` file. Do NOT run any `docker` or `docker compose` commands.
"""

_PROMPT_DIR = os.path.join(os.path.dirname(__file__), "..", "prompts")


def render_prompt(template_path: str, **kwargs) -> str:
    with open(template_path) as f:
        text = f.read()
    for key, value in kwargs.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


def workspace_dir(container_row) -> str:
    repo = (container_row["repo"] or "").rstrip("/")
    repo_name = os.path.basename(repo)
    subdir = container_row["subdir"] or ""
    return os.path.join("/workspaces", repo_name, subdir) if repo_name else ""


def analyze(container_row, fingerprint: str, excerpt: str) -> dict:
    prompt = render_prompt(
        os.path.join(_PROMPT_DIR, "analyze.md"),
        container=container_row["name"],
        excerpt=excerpt,
        repo=container_row["repo"] or "",
        subdir=container_row["subdir"] or "",
    )
    result = subprocess.run(
        [
            "claude", "-p", prompt,
            "--output-format", "json",
            "--max-turns", "15",
            "--allowedTools", PHASE1_ALLOWED_TOOLS,
        ],
        cwd=workspace_dir(container_row) or None,
        capture_output=True,
        text=True,
        timeout=PHASE1_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude analyze failed (exit {result.returncode}): {result.stderr[:500]}")

    try:
        payload = json.loads(result.stdout or "{}")
        text = payload.get("result", result.stdout.strip())
    except json.JSONDecodeError:
        text = result.stdout.strip()
    verdict, text = parse_verdict(text)
    return {"text": text, "excerpt": excerpt, "verdict": verdict}


def run_fix(container_row, fingerprint: str, analysis: dict, workspace_dir: str) -> str | None:
    name = container_row["name"]
    branch = f"fix/{fingerprint}"

    with workspace_lock:
        subprocess.run(["git", "fetch", "origin"], cwd=workspace_dir, check=True)
        subprocess.run(["git", "checkout", "-b", branch, "origin/main"], cwd=workspace_dir, check=True)

        prompt = _FIX_PROMPT_TEMPLATE.format(container=name, analysis=analysis["text"])
        subprocess.run(
            [
                "claude", "-p", prompt,
                "--output-format", "json",
                "--max-turns", "15",
                "--allowedTools", PHASE2_ALLOWED_TOOLS,
            ],
            cwd=workspace_dir,
            capture_output=True,
            text=True,
            timeout=PHASE2_TIMEOUT_SECONDS,
        )

        changed_files = subprocess.run(
            ["git", "diff", "--name-only"], cwd=workspace_dir, capture_output=True, text=True
        ).stdout.splitlines()
        diff_stat = subprocess.run(
            ["git", "diff", "--stat"], cwd=workspace_dir, capture_output=True, text=True
        ).stdout
        diff_text = subprocess.run(
            ["git", "diff"], cwd=workspace_dir, capture_output=True, text=True
        ).stdout
        diff_lines = sum(
            1 for line in diff_text.splitlines() if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
        )

        forbidden_hit = any(FORBIDDEN_FIX_FILES.search(f) for f in changed_files)
        if not changed_files:
            reason = "claude produced no changes"
        elif forbidden_hit:
            reason = "touched a forbidden file"
        elif diff_lines > MAX_DIFF_LINES:
            reason = f"diff too large ({diff_lines} lines)"
        else:
            reason = None

        if reason:
            subprocess.run(["git", "checkout", "-B", "main", "origin/main"], cwd=workspace_dir, check=True)
            subprocess.run(["git", "reset", "--hard", "origin/main"], cwd=workspace_dir, check=True)
            subprocess.run(["git", "clean", "-fd"], cwd=workspace_dir, check=True)
            subprocess.run(["git", "branch", "-D", branch], cwd=workspace_dir, check=True)
            notify(f"🚫 Fix rejected for {name} (fingerprint {fingerprint}): {reason}")
            return None

        subprocess.run(["git", "add", "-A"], cwd=workspace_dir, check=True)
        subprocess.run(["git", "commit", "-m", f"fix: log-medic auto-fix for {fingerprint}"], cwd=workspace_dir, check=True)
        subprocess.run(["git", "push", "origin", branch], cwd=workspace_dir, check=True)

        pr_body = (
            f"## Log excerpt\n```\n{analysis.get('excerpt', '')}\n```\n\n"
            f"## Root cause\n{analysis['text']}\n\n"
            f"## What changed\n{diff_stat}\n\n"
            f"## How to test\nRe-run the scenario that produced the original log line; confirm the WARN/ERROR no longer occurs.\n"
        )
        result = subprocess.run(
            [
                "gh", "pr", "create",
                "--title", f"fix: {name} ({fingerprint})",
                "--body", pr_body,
                "--label", "auto-fix",
                "--base", "main",
                "--head", branch,
            ],
            cwd=workspace_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        subprocess.run(["git", "checkout", "-B", "main", "origin/main"], cwd=workspace_dir, check=True)
        return result.stdout.strip()
