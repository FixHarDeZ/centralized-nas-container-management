"""Tests for scripts/diff_envs.py — used during Phase A Step 3."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import diff_envs


def test_identical_envs_match(tmp_path: Path) -> None:
    a = tmp_path / "a.env"
    b = tmp_path / "b.env"
    a.write_text("FOO=1\nBAR=hello\n")
    b.write_text("BAR=hello\nFOO=1\n")
    result = diff_envs.diff(a, b)
    assert result.equivalent is True
    assert result.missing == set()
    assert result.extra == set()
    assert result.changed == {}


def test_comments_and_blank_lines_ignored(tmp_path: Path) -> None:
    a = tmp_path / "a.env"
    b = tmp_path / "b.env"
    a.write_text("# header\n\nFOO=1\n")
    b.write_text("FOO=1\n")
    assert diff_envs.diff(a, b).equivalent is True


def test_missing_key_detected(tmp_path: Path) -> None:
    a = tmp_path / "a.env"
    b = tmp_path / "b.env"
    a.write_text("FOO=1\nBAR=2\n")
    b.write_text("FOO=1\n")
    result = diff_envs.diff(a, b)
    assert result.equivalent is False
    assert result.missing == {"BAR"}


def test_extra_key_detected(tmp_path: Path) -> None:
    a = tmp_path / "a.env"
    b = tmp_path / "b.env"
    a.write_text("FOO=1\n")
    b.write_text("FOO=1\nBAR=2\n")
    result = diff_envs.diff(a, b)
    assert result.equivalent is False
    assert result.extra == {"BAR"}


def test_value_change_detected(tmp_path: Path) -> None:
    a = tmp_path / "a.env"
    b = tmp_path / "b.env"
    a.write_text("FOO=1\n")
    b.write_text("FOO=2\n")
    result = diff_envs.diff(a, b)
    assert result.equivalent is False
    assert result.changed == {"FOO": ("1", "2")}


def test_quoted_value_normalized_for_compare(tmp_path: Path) -> None:
    # Source has unquoted, renderer outputs single-quoted because of a space.
    a = tmp_path / "a.env"
    b = tmp_path / "b.env"
    a.write_text("MSG=hello world\n")
    b.write_text("MSG='hello world'\n")
    assert diff_envs.diff(a, b).equivalent is True
