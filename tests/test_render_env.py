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


def test_duplicate_env_keys_raise() -> None:
    # env-vs-literal collision in the same manifest is an error.
    vault = {"shared": {"x": {"a": "1", "b": "2"}}}
    manifest = {"env": {"FOO": "shared.x.a"}, "literals": {"FOO": "literal"}}
    with pytest.raises(render_env.RenderError) as exc_info:
        render_env.render_stack(vault, manifest)
    assert "FOO" in str(exc_info.value)


def test_literal_only_with_int_value_renders_unquoted() -> None:
    out = render_env.render_stack({}, {"literals": {"RETENTION_DAYS": 30}})
    assert "RETENTION_DAYS=30" in out


def test_literal_with_boolean_renders_lowercase() -> None:
    out = render_env.render_stack({}, {"literals": {"DEBUG": True}})
    assert "DEBUG=true" in out


def test_find_manifests_picks_up_stack_files(tmp_path: Path) -> None:
    (tmp_path / "foo").mkdir()
    (tmp_path / "foo" / "secrets.manifest.yaml").write_text("env: {}\n")
    (tmp_path / "bar").mkdir()
    (tmp_path / "bar" / "secrets.manifest.yaml").write_text("env: {}\n")
    (tmp_path / "skip").mkdir()
    (tmp_path / "skip" / "other.yaml").write_text("nope\n")

    paths = render_env.find_manifests(tmp_path)
    names = sorted(p.parent.name for p in paths)
    assert names == ["bar", "foo"]


def test_find_manifests_includes_root_deploy_manifest(tmp_path: Path) -> None:
    (tmp_path / "deploy.manifest.yaml").write_text("env: {}\n")
    paths = render_env.find_manifests(tmp_path)
    assert any(p.name == "deploy.manifest.yaml" for p in paths)


def test_find_manifests_recurses_one_level_for_secretary_substacks(tmp_path: Path) -> None:
    sub = tmp_path / "secretary" / "ingest"
    sub.mkdir(parents=True)
    (sub / "secrets.manifest.yaml").write_text("env: {}\n")
    paths = render_env.find_manifests(tmp_path)
    rel = [p.relative_to(tmp_path) for p in paths]
    assert Path("secretary/ingest/secrets.manifest.yaml") in rel


def test_load_decrypted_vault_from_plaintext_yaml(tmp_path: Path) -> None:
    """When vault is plaintext (no sops metadata), parse as YAML directly."""
    p = tmp_path / "vault.yaml"
    p.write_text("shared:\n  llm:\n    openrouter_api_key: sk-or-test\n")
    vault = render_env.load_vault(p)
    assert vault["shared"]["llm"]["openrouter_api_key"] == "sk-or-test"


def test_output_path_for_stack_manifest_is_sibling_env(tmp_path: Path) -> None:
    manifest_path = tmp_path / "newsfeed" / "secrets.manifest.yaml"
    assert render_env.output_path(manifest_path) == tmp_path / "newsfeed" / ".env"


def test_output_path_for_root_deploy_manifest_is_root_env_deploy(tmp_path: Path) -> None:
    manifest_path = tmp_path / "deploy.manifest.yaml"
    assert render_env.output_path(manifest_path) == tmp_path / ".env.deploy"


def test_integration_render_using_fixtures(tmp_path: Path) -> None:
    fixtures = Path(__file__).resolve().parent / "fixtures" / "render"
    vault = render_env.load_vault(fixtures / "vault.yaml")
    manifest = render_env.load_manifest(fixtures / "manifest.demo.yaml")
    out = render_env.render_stack(vault, manifest)
    assert "OPENROUTER_API_KEY=sk-or-fixture" in out
    assert "ADMIN_TOKEN=admintok-fixture" in out
    assert "DATA_DIR=/data" in out


def test_main_renders_all_manifests_in_repo(tmp_path: Path) -> None:
    (tmp_path / "vault.yaml").write_text(
        "shared:\n  k: v1\nstacks:\n  s:\n    a: v2\n"
    )
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "secrets.manifest.yaml").write_text(
        "env:\n  FOO: shared.k\n"
    )
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "secrets.manifest.yaml").write_text(
        "env:\n  BAR: stacks.s.a\n"
    )
    rc = render_env.main(
        ["--root", str(tmp_path), "--vault", str(tmp_path / "vault.yaml")]
    )
    assert rc == 0
    assert (tmp_path / "a" / ".env").read_text().splitlines()[-1] == "FOO=v1"
    assert (tmp_path / "b" / ".env").read_text().splitlines()[-1] == "BAR=v2"


def test_main_stack_filter_renders_only_named(tmp_path: Path) -> None:
    (tmp_path / "vault.yaml").write_text("shared:\n  k: v1\n")
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "secrets.manifest.yaml").write_text(
            "env:\n  FOO: shared.k\n"
        )
    rc = render_env.main(
        [
            "--root", str(tmp_path),
            "--vault", str(tmp_path / "vault.yaml"),
            "--stack", "a",
        ]
    )
    assert rc == 0
    assert (tmp_path / "a" / ".env").exists()
    assert not (tmp_path / "b" / ".env").exists()


def test_main_check_does_not_write(tmp_path: Path) -> None:
    (tmp_path / "vault.yaml").write_text("shared:\n  k: v1\n")
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "secrets.manifest.yaml").write_text(
        "env:\n  FOO: shared.k\n"
    )
    rc = render_env.main(
        [
            "--root", str(tmp_path),
            "--vault", str(tmp_path / "vault.yaml"),
            "--check",
        ]
    )
    assert rc == 0
    assert not (tmp_path / "a" / ".env").exists()


def test_main_returns_nonzero_on_missing_vault_path(tmp_path: Path) -> None:
    (tmp_path / "vault.yaml").write_text("shared: {}\n")
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "secrets.manifest.yaml").write_text(
        "env:\n  FOO: shared.missing\n"
    )
    rc = render_env.main(
        ["--root", str(tmp_path), "--vault", str(tmp_path / "vault.yaml")]
    )
    assert rc != 0


def test_main_with_suffix_writes_to_alternate_filename(tmp_path: Path) -> None:
    (tmp_path / "vault.yaml").write_text("shared:\n  k: v1\n")
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "secrets.manifest.yaml").write_text(
        "env:\n  FOO: shared.k\n"
    )
    rc = render_env.main(
        [
            "--root", str(tmp_path),
            "--vault", str(tmp_path / "vault.yaml"),
            "--suffix", ".new",
        ]
    )
    assert rc == 0
    assert (tmp_path / "a" / ".env.new").exists()
    assert not (tmp_path / "a" / ".env").exists()
