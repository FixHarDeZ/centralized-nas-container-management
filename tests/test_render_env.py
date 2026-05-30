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


def test_simple_value_unquoted() -> None:
    assert render_env.compose_quote("hello") == "hello"
    assert render_env.compose_quote("sk-or-abc123") == "sk-or-abc123"
    assert render_env.compose_quote("U1234567890abcdef") == "U1234567890abcdef"


def test_value_with_space_is_single_quoted() -> None:
    assert render_env.compose_quote("hello world") == "'hello world'"


def test_value_with_hash_is_single_quoted() -> None:
    assert render_env.compose_quote("path#frag") == "'path#frag'"


def test_value_with_double_quote_is_single_quoted() -> None:
    assert render_env.compose_quote('say "hi"') == "'say \"hi\"'"


def test_value_with_single_quote_uses_double_quotes_and_escapes() -> None:
    # Has a literal ' so cannot use single quotes; wrap in " and escape \ and "
    assert render_env.compose_quote("it's a test") == "\"it's a test\""


def test_value_with_backslash_in_double_quoted_form_is_escaped() -> None:
    # Cannot use single quotes (input has '), must use double quotes, escape backslash.
    assert render_env.compose_quote("a\\b'c") == "\"a\\\\b'c\""


def test_value_with_dollar_sign_stays_literal_single_quoted() -> None:
    # $ is literal in .env; single-quote to keep it from looking like interpolation.
    assert render_env.compose_quote("$ecret") == "'$ecret'"


def test_value_with_leading_whitespace_is_quoted() -> None:
    assert render_env.compose_quote(" leading") == "' leading'"


def test_multiline_value_raises() -> None:
    with pytest.raises(render_env.RenderError) as exc_info:
        render_env.compose_quote("line1\nline2")
    assert "newline" in str(exc_info.value).lower() or "multiline" in str(exc_info.value).lower()


def test_numeric_value_serialized_as_string() -> None:
    # YAML may give us int/bool from literals; ensure they become strings.
    assert render_env.compose_quote(30) == "30"
    assert render_env.compose_quote(True) == "true"
    assert render_env.compose_quote(False) == "false"
