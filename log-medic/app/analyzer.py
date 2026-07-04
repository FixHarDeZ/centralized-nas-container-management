from __future__ import annotations

import json
import os
import subprocess

PHASE1_ALLOWED_TOOLS = "Read,Grep,Glob,Bash(git log:*),Bash(git diff:*)"
PHASE1_TIMEOUT_SECONDS = 600

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
    try:
        payload = json.loads(result.stdout or "{}")
        text = payload.get("result", result.stdout.strip())
    except json.JSONDecodeError:
        text = result.stdout.strip()
    return {"text": text, "excerpt": excerpt}


def run_fix(*a, **k):
    raise NotImplementedError
