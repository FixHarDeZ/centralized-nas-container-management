"""Tests for scripts/render_env.py."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import render_env  # noqa: E402


def test_render_one_stack_with_env_and_literals(tmp_path: Path) -> None:
    vault = {
        "shared": {"llm": {"openrouter_api_key": "sk-or-test"}},
        "stacks": {"demo": {"admin_token": "admintok"}},
    }
    manifest = {
        "env": {
            "OPENROUTER_API_KEY": "shared.llm.openrouter_api_key",
            "ADMIN_TOKEN": "stacks.demo.admin_token",
        },
        "literals": {"DATA_DIR": "/data", "RETENTION_DAYS": "30"},
    }
    out = render_env.render_stack(vault, manifest)
    assert "OPENROUTER_API_KEY=sk-or-test" in out
    assert "ADMIN_TOKEN=admintok" in out
    assert "DATA_DIR=/data" in out
    assert "RETENTION_DAYS=30" in out


def test_render_missing_vault_path_raises(tmp_path: Path) -> None:
    vault = {"shared": {"llm": {}}}
    manifest = {"env": {"OPENROUTER_API_KEY": "shared.llm.openrouter_api_key"}}
    with pytest.raises(render_env.RenderError) as exc_info:
        render_env.render_stack(vault, manifest)
    assert "shared.llm.openrouter_api_key" in str(exc_info.value)


def test_render_empty_manifest_returns_only_header() -> None:
    out = render_env.render_stack({}, {})
    # Header lines start with '#', no key=value lines.
    non_comment_non_empty = [
        line for line in out.splitlines() if line.strip() and not line.startswith("#")
    ]
    assert non_comment_non_empty == []
