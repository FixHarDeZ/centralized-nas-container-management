# Env / Secrets Management Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace scattered `<stack>/.env` files + aspirational `sync_env.py` with an encrypted sops+age vault + per-stack manifest + generator pipeline that produces per-stack `.env` files containing only the keys each stack declares.

**Architecture:** Single encrypted YAML vault (`secrets/vault.sops.yaml`) is the source of truth, organized as `shared:` (cross-stack values) + `stacks:` (stack-private values). Each stack has a `secrets.manifest.yaml` that maps vault paths → ENV names (Phase A keeps current ENV names verbatim). `scripts/render_env.py` decrypts vault + reads manifests + writes `<stack>/.env` + root `.env.deploy`. Existing `deploy.sh` (tar+ssh) consumes generated files unchanged; NAS never installs sops/age.

**Tech Stack:** Python 3.14 (PyYAML, jsonschema, pytest), sops, age, GNU Make, Bash, GitHub Actions.

**Spec reference:** `docs/superpowers/specs/2026-05-30-env-secrets-management-redesign-design.md`

**Scope of this plan:** Phase A only (vault + manifests + generator + cutover). Phase B (rename ENV keys to upstream conventions per stack) is explicitly deferred per spec §11.3 — it can be its own plan later, one PR per stack. Phase A delivers all four pain-point fixes on its own.

---

## Task 1: Install tooling and bootstrap workstation age key

**Files:**
- Create: `~/.config/sops/age/keys.txt` (private — NEVER committed)
- Create: `secrets/.sops.yaml`

- [ ] **Step 1: Install sops and age via Homebrew**

Run:
```bash
brew install sops age
sops --version && age --version
```
Expected: both report a version (e.g., `sops 3.9.x`, `age 1.2.x`). If install fails on macOS, abort and surface the error.

- [ ] **Step 2: Generate the workstation age key**

Run:
```bash
mkdir -p ~/.config/sops/age
test -f ~/.config/sops/age/keys.txt || age-keygen -o ~/.config/sops/age/keys.txt
chmod 600 ~/.config/sops/age/keys.txt
grep -E '^# public key:' ~/.config/sops/age/keys.txt
```
Expected: prints one line `# public key: age1xxxxxxxxxxxxxxxxxxxxx`. Copy that public key string for Step 3.

If `~/.config/sops/age/keys.txt` already exists, do NOT overwrite — reuse it.

- [ ] **Step 3: Create `secrets/.sops.yaml` with the workstation key as the only recipient**

Create directory and file:
```bash
mkdir -p secrets
```

Write `secrets/.sops.yaml` (replace `AGE_PUBLIC_KEY_FROM_STEP_2` with the actual public key from Step 2):
```yaml
creation_rules:
  - path_regex: secrets/vault\.sops\.yaml$
    age: AGE_PUBLIC_KEY_FROM_STEP_2
    encrypted_regex: '^(.*)$'
  - path_regex: secrets/test-vault\.sops\.yaml$
    age: AGE_PUBLIC_KEY_FROM_STEP_2
    encrypted_regex: '^(.*)$'
```
(The CI test-vault recipient will be added in Task 20; for now both rules point to the workstation so local tests work.)

- [ ] **Step 4: Verify sops picks up the config**

Run:
```bash
echo "test_value: hello" > /tmp/_sops_check.yaml
SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops --config secrets/.sops.yaml -e /tmp/_sops_check.yaml > /tmp/_sops_check.sops.yaml
grep -q "ENC\[" /tmp/_sops_check.sops.yaml && echo "OK: value is encrypted"
SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops -d /tmp/_sops_check.sops.yaml
rm -f /tmp/_sops_check.yaml /tmp/_sops_check.sops.yaml
```
Expected: prints `OK: value is encrypted`, then the decrypt step prints `test_value: hello`.

- [ ] **Step 5: Commit `.sops.yaml`**

```bash
git add secrets/.sops.yaml
git commit -m "chore(secrets): add sops config with workstation age recipient"
```

---

## Task 2: Bootstrap Python test infrastructure for the scripts module

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `pyproject.toml` (only if it does not exist at repo root — verify first)
- Modify: `.venv` (install dev deps)

- [ ] **Step 1: Verify Python 3.14 venv is usable**

Run:
```bash
.venv/bin/python --version
.venv/bin/pip list 2>/dev/null | head
```
Expected: `Python 3.14.x`. If not, halt and ask user.

- [ ] **Step 2: Install required dependencies**

Run:
```bash
.venv/bin/pip install pytest pyyaml jsonschema
```
Expected: all three install successfully.

- [ ] **Step 3: Create `tests/` package**

Create `tests/__init__.py` as an empty file.

- [ ] **Step 4: Create `tests/conftest.py`**

Create `tests/conftest.py`:
```python
"""Shared pytest fixtures for repo-level script tests."""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def scripts_dir() -> Path:
    return SCRIPTS_DIR


@pytest.fixture
def tmp_vault(tmp_path: Path) -> Path:
    """A plaintext YAML mimicking a decrypted vault, for unit tests."""
    return tmp_path / "vault.yaml"


@pytest.fixture
def tmp_manifest(tmp_path: Path) -> Path:
    return tmp_path / "secrets.manifest.yaml"
```

- [ ] **Step 5: Check root pytest configuration**

Run:
```bash
[ -f pyproject.toml ] && cat pyproject.toml || echo "NO_PYPROJECT"
```
If output is `NO_PYPROJECT`, create `pyproject.toml`:
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
```

If `pyproject.toml` already exists, add the section above only if it is missing a `[tool.pytest.ini_options]` block. Otherwise leave it alone.

- [ ] **Step 6: Confirm pytest collects nothing yet (sanity)**

Run:
```bash
.venv/bin/pytest tests/ -v
```
Expected: `no tests ran` (collection succeeds, zero tests).

- [ ] **Step 7: Commit**

```bash
git add tests/ pyproject.toml
git commit -m "chore(tests): bootstrap repo-level pytest infrastructure"
```

---

## Task 3: Define the manifest JSON Schema

**Files:**
- Create: `secrets/manifest.schema.json`
- Create: `tests/test_manifest_schema.py`

- [ ] **Step 1: Write the failing schema-validation tests first**

Create `tests/test_manifest_schema.py`:
```python
"""Validate that secrets/manifest.schema.json enforces the spec rules."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "secrets" / "manifest.schema.json"


@pytest.fixture
def validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def test_minimal_valid_manifest_passes(validator: Draft202012Validator) -> None:
    doc = {"env": {"FOO": "shared.llm.openrouter_api_key"}}
    assert list(validator.iter_errors(doc)) == []


def test_env_only_manifest_passes(validator: Draft202012Validator) -> None:
    doc = {"env": {"FOO": "stacks.news_feed.telegram.bot_token"}}
    assert list(validator.iter_errors(doc)) == []


def test_literals_only_manifest_passes(validator: Draft202012Validator) -> None:
    doc = {"literals": {"DATA_DIR": "/data", "RETENTION_DAYS": "30"}}
    assert list(validator.iter_errors(doc)) == []


def test_both_sections_pass(validator: Draft202012Validator) -> None:
    doc = {
        "env": {"OPENROUTER_API_KEY": "shared.llm.openrouter_api_key"},
        "literals": {"DATA_DIR": "/data"},
    }
    assert list(validator.iter_errors(doc)) == []


def test_unknown_top_level_key_fails(validator: Draft202012Validator) -> None:
    doc = {"env": {"FOO": "shared.llm.x"}, "extra": "nope"}
    errors = list(validator.iter_errors(doc))
    assert any("extra" in str(e.message) or "additional" in str(e.message).lower() for e in errors)


def test_env_value_must_start_with_allowed_prefix(validator: Draft202012Validator) -> None:
    doc = {"env": {"FOO": "random.path.thing"}}
    errors = list(validator.iter_errors(doc))
    assert errors, "expected validation error for non-shared/stacks/deploy prefix"


def test_env_key_must_be_uppercase_envvar(validator: Draft202012Validator) -> None:
    doc = {"env": {"lowercase_name": "shared.llm.openrouter_api_key"}}
    errors = list(validator.iter_errors(doc))
    assert errors, "expected validation error for lowercase ENV name"


def test_literal_value_must_be_scalar(validator: Draft202012Validator) -> None:
    doc = {"literals": {"FOO": {"nested": "object"}}}
    errors = list(validator.iter_errors(doc))
    assert errors, "expected literal nested object to fail"


def test_empty_manifest_passes(validator: Draft202012Validator) -> None:
    # An empty manifest is permitted (no secrets, no literals — stack reads nothing).
    assert list(validator.iter_errors({})) == []
```

- [ ] **Step 2: Run tests to verify they all fail (schema file missing)**

Run:
```bash
.venv/bin/pytest tests/test_manifest_schema.py -v
```
Expected: all tests fail with `FileNotFoundError` on `manifest.schema.json`.

- [ ] **Step 3: Create the schema file**

Create `secrets/manifest.schema.json`:
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://example.com/secrets/manifest.schema.json",
  "title": "Per-stack secrets manifest",
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "env": {
      "type": "object",
      "description": "Mapping of ENV name to vault path",
      "patternProperties": {
        "^[A-Z][A-Z0-9_]*$": {
          "type": "string",
          "pattern": "^(shared|stacks|deploy)\\.[A-Za-z0-9_.]+$"
        }
      },
      "additionalProperties": false
    },
    "literals": {
      "type": "object",
      "description": "Plain config values written as-is to the generated .env",
      "patternProperties": {
        "^[A-Z][A-Z0-9_]*$": {
          "type": ["string", "number", "boolean"]
        }
      },
      "additionalProperties": false
    }
  }
}
```

- [ ] **Step 4: Run tests to verify they all pass**

Run:
```bash
.venv/bin/pytest tests/test_manifest_schema.py -v
```
Expected: all 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add secrets/manifest.schema.json tests/test_manifest_schema.py
git commit -m "feat(secrets): add manifest JSON schema with validation tests"
```

---

## Task 4: render_env.py — minimal vault load + manifest application

**Files:**
- Create: `scripts/render_env.py`
- Create: `tests/test_render_env.py`

This task implements the simplest happy-path: load a plaintext vault (we'll add sops decryption in Task 5), load a manifest, look up paths, write a `.env`. Quoting, validation, and CLI come in later tasks.

- [ ] **Step 1: Write the failing minimal-render test**

Create `tests/test_render_env.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
.venv/bin/pytest tests/test_render_env.py -v
```
Expected: ImportError or all 3 tests fail because `render_env` does not exist yet.

- [ ] **Step 3: Implement minimal `scripts/render_env.py`**

Create `scripts/render_env.py`:
```python
#!/usr/bin/env python3
"""Render per-stack .env files from sops-encrypted vault + per-stack manifests.

This is the entry point invoked by `make secrets`. See
docs/superpowers/specs/2026-05-30-env-secrets-management-redesign-design.md
for the design.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping


class RenderError(Exception):
    """Raised when a manifest references a missing vault path or violates rules."""


def lookup(vault: Mapping[str, Any], dotted_path: str) -> Any:
    """Walk a dotted path through nested dicts. Returns None if any segment is missing."""
    node: Any = vault
    for segment in dotted_path.split("."):
        if not isinstance(node, Mapping) or segment not in node:
            return None
        node = node[segment]
    return node


def render_stack(vault: Mapping[str, Any], manifest: Mapping[str, Any]) -> str:
    """Render a single stack's .env contents from a decrypted vault + manifest dict.

    Returns the file contents as a string (no I/O). Caller writes to disk.
    """
    lines: list[str] = [
        "# GENERATED by scripts/render_env.py — DO NOT EDIT",
        "# Regenerate: make secrets",
    ]

    env_map = manifest.get("env") or {}
    literals = manifest.get("literals") or {}

    for env_name, vault_path in env_map.items():
        value = lookup(vault, vault_path)
        if value is None:
            raise RenderError(
                f"manifest references missing vault path '{vault_path}' "
                f"for ENV '{env_name}'"
            )
        lines.append(f"{env_name}={value}")

    for env_name, value in literals.items():
        lines.append(f"{env_name}={value}")

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    # Real CLI comes in Task 8.
    print("render_env: CLI not yet implemented; see Task 8.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
.venv/bin/pytest tests/test_render_env.py -v
```
Expected: all 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/render_env.py tests/test_render_env.py
git commit -m "feat(secrets): render_env minimal core (vault lookup + manifest application)"
```

---

## Task 5: render_env.py — compose-`.env` quoting

**Files:**
- Modify: `scripts/render_env.py`
- Modify: `tests/test_render_env.py`

Docker compose's `.env` parser differs from generic shell — see https://docs.docker.com/compose/environment-variables/env-file/. Key rules:

- Values are taken literally up to end-of-line.
- Surrounding double quotes are stripped; inside double quotes, `\n` `\r` `\t` `\"` `\\` are interpreted.
- Surrounding single quotes are stripped; contents are literal (no escapes).
- `$` is literal in `.env` (unlike interpolation in the compose file itself).
- Newlines inside a value are NOT supported.

Our generator therefore:
- Returns the value unquoted if it has no special chars and no leading/trailing whitespace.
- Single-quotes the value if it contains spaces, `#`, `"`, `\`, or starts/ends with whitespace.
- If the value already contains a literal single quote (`'`), wrap in double quotes and escape `"` `\` only.
- Multiline values raise `RenderError`.

- [ ] **Step 1: Add the failing quoting tests**

Append to `tests/test_render_env.py`:
```python
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


def test_multiline_value_raises(tmp_path: Path) -> None:
    with pytest.raises(render_env.RenderError) as exc_info:
        render_env.compose_quote("line1\nline2")
    assert "newline" in str(exc_info.value).lower() or "multiline" in str(exc_info.value).lower()


def test_numeric_value_serialized_as_string() -> None:
    # YAML may give us int/bool from literals; ensure they become strings.
    assert render_env.compose_quote(30) == "30"
    assert render_env.compose_quote(True) == "true"
    assert render_env.compose_quote(False) == "false"
```

- [ ] **Step 2: Run tests to verify the new tests fail**

Run:
```bash
.venv/bin/pytest tests/test_render_env.py -v
```
Expected: the 10 new tests fail with `AttributeError: module 'render_env' has no attribute 'compose_quote'`.

- [ ] **Step 3: Implement `compose_quote` and wire it into `render_stack`**

Modify `scripts/render_env.py` — add `compose_quote` near the top and use it in `render_stack`:

```python
def compose_quote(value: Any) -> str:
    """Render a Python value as a docker-compose .env-safe string.

    Rules (matching docker-compose .env parser semantics):
      - bool/int → 'true'/'false'/str(int) unquoted
      - str with no special chars and no leading/trailing whitespace → unquoted
      - str with special chars (space, #, ", \\, $, leading/trailing whitespace)
        but no literal single quote → wrapped in single quotes
      - str containing single quote → wrapped in double quotes with \\ and "
        escaped (the only escapes compose interprets inside double quotes that
        we need here)
      - str containing newline → RenderError (multiline values not supported)
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)

    s = str(value)
    if "\n" in s or "\r" in s:
        raise RenderError(
            "value contains a newline; docker-compose .env does not support "
            "multiline values — base64-encode or split into multiple keys"
        )

    needs_quoting = (
        s != s.strip()
        or any(ch in s for ch in (" ", "#", '"', "\\", "$"))
    )
    if not needs_quoting:
        return s

    if "'" not in s:
        return f"'{s}'"

    # Has a literal single quote — use double quotes; escape \ and ".
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
```

Then in `render_stack`, change the two append loops to use `compose_quote`:
```python
    for env_name, vault_path in env_map.items():
        value = lookup(vault, vault_path)
        if value is None:
            raise RenderError(
                f"manifest references missing vault path '{vault_path}' "
                f"for ENV '{env_name}'"
            )
        lines.append(f"{env_name}={compose_quote(value)}")

    for env_name, value in literals.items():
        lines.append(f"{env_name}={compose_quote(value)}")
```

- [ ] **Step 4: Run tests to verify all pass**

Run:
```bash
.venv/bin/pytest tests/test_render_env.py -v
```
Expected: all 13 tests pass (3 from Task 4 + 10 from Task 5).

- [ ] **Step 5: Commit**

```bash
git add scripts/render_env.py tests/test_render_env.py
git commit -m "feat(secrets): compose-.env-compliant value quoting in render_env"
```

---

## Task 6: render_env.py — validation (duplicates, literal/env collisions)

**Files:**
- Modify: `scripts/render_env.py`
- Modify: `tests/test_render_env.py`

- [ ] **Step 1: Add the failing validation tests**

Append to `tests/test_render_env.py`:
```python
def test_duplicate_env_keys_raise() -> None:
    # YAML parsers usually dedupe at load time, but we still defend against it
    # when manifests are constructed programmatically.
    vault = {"shared": {"x": {"a": "1", "b": "2"}}}
    # Simulate post-load dict with same key by constructing manually
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
```

- [ ] **Step 2: Run tests to verify the duplicate-key test fails**

Run:
```bash
.venv/bin/pytest tests/test_render_env.py -v
```
Expected: `test_duplicate_env_keys_raise` fails (currently the literal silently shadows the env entry). The two scalar tests may already pass (already covered by compose_quote).

- [ ] **Step 3: Enforce env/literal collision in `render_stack`**

Modify `render_stack` in `scripts/render_env.py`:
```python
def render_stack(vault: Mapping[str, Any], manifest: Mapping[str, Any]) -> str:
    lines: list[str] = [
        "# GENERATED by scripts/render_env.py — DO NOT EDIT",
        "# Regenerate: make secrets",
    ]

    env_map = manifest.get("env") or {}
    literals = manifest.get("literals") or {}

    seen: set[str] = set()

    for env_name, vault_path in env_map.items():
        if env_name in seen:
            raise RenderError(f"duplicate ENV name '{env_name}' in manifest")
        seen.add(env_name)
        value = lookup(vault, vault_path)
        if value is None:
            raise RenderError(
                f"manifest references missing vault path '{vault_path}' "
                f"for ENV '{env_name}'"
            )
        lines.append(f"{env_name}={compose_quote(value)}")

    for env_name, value in literals.items():
        if env_name in seen:
            raise RenderError(
                f"literal '{env_name}' collides with env mapping in same manifest"
            )
        seen.add(env_name)
        lines.append(f"{env_name}={compose_quote(value)}")

    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run tests to verify all pass**

Run:
```bash
.venv/bin/pytest tests/test_render_env.py -v
```
Expected: all 16 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/render_env.py tests/test_render_env.py
git commit -m "feat(secrets): reject duplicate ENV names and env/literal collisions"
```

---

## Task 7: render_env.py — sops decryption + manifest file loading

**Files:**
- Modify: `scripts/render_env.py`
- Modify: `tests/test_render_env.py`
- Create: `tests/fixtures/render/vault.yaml` (plaintext fixture for round-trip test)
- Create: `tests/fixtures/render/manifest.demo.yaml`

This task wires real file I/O: read encrypted vault via `sops` subprocess, parse YAML, find and parse all `secrets.manifest.yaml` files, write `<stack>/.env`.

- [ ] **Step 1: Write the failing file-discovery + write test**

Append to `tests/test_render_env.py`:
```python
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


def test_load_decrypted_vault_from_plaintext_yaml(tmp_path: Path) -> None:
    """When vault filename does not match .sops.yaml, render_env should still
    accept a plaintext YAML — useful for fixtures and for local edits before
    initial encryption."""
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
```

- [ ] **Step 2: Run tests to confirm they fail**

Run:
```bash
.venv/bin/pytest tests/test_render_env.py -v
```
Expected: 5 new tests fail with `AttributeError` for the new functions.

- [ ] **Step 3: Implement file I/O helpers in `scripts/render_env.py`**

Add imports + new functions to `scripts/render_env.py`:

At the top, add imports:
```python
import subprocess
import yaml
```

Then add helper functions before `main`:
```python
def find_manifests(repo_root: Path) -> list[Path]:
    """Return all manifest files: every <stack>/secrets.manifest.yaml plus
    the root deploy.manifest.yaml if it exists."""
    result: list[Path] = []
    deploy = repo_root / "deploy.manifest.yaml"
    if deploy.exists():
        result.append(deploy)
    for child in sorted(repo_root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        manifest = child / "secrets.manifest.yaml"
        if manifest.exists():
            result.append(manifest)
        # secretary/ has sub-stacks (ingest, query); recurse one level
        for sub in sorted(child.iterdir()) if child.is_dir() else []:
            if not sub.is_dir():
                continue
            sub_manifest = sub / "secrets.manifest.yaml"
            if sub_manifest.exists():
                result.append(sub_manifest)
    return result


def output_path(manifest_path: Path) -> Path:
    """Map a manifest file to the .env file it produces."""
    if manifest_path.name == "deploy.manifest.yaml":
        return manifest_path.parent / ".env.deploy"
    return manifest_path.parent / ".env"


def load_vault(path: Path) -> dict:
    """Load a vault file. If it appears to be sops-encrypted (has a 'sops:' key
    at the top level), shell out to `sops -d`. Otherwise parse as plaintext YAML."""
    text = path.read_text()
    if "\nsops:\n" in text or text.startswith("sops:\n"):
        result = subprocess.run(
            ["sops", "-d", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RenderError(f"sops decrypt failed for {path}: {result.stderr.strip()}")
        return yaml.safe_load(result.stdout) or {}
    return yaml.safe_load(text) or {}


def load_manifest(path: Path) -> dict:
    return yaml.safe_load(path.read_text()) or {}
```

- [ ] **Step 4: Run tests to verify file-discovery tests pass**

Run:
```bash
.venv/bin/pytest tests/test_render_env.py -v
```
Expected: all 21 tests pass.

- [ ] **Step 5: Create fixtures for an integration-style test**

Create `tests/fixtures/render/vault.yaml`:
```yaml
shared:
  llm:
    openrouter_api_key: sk-or-fixture
    anthropic_api_key: sk-ant-fixture
stacks:
  demo:
    admin_token: admintok-fixture
```

Create `tests/fixtures/render/manifest.demo.yaml`:
```yaml
env:
  OPENROUTER_API_KEY: shared.llm.openrouter_api_key
  ADMIN_TOKEN: stacks.demo.admin_token
literals:
  DATA_DIR: /data
```

- [ ] **Step 6: Add an integration test that ties vault + manifest + output**

Append to `tests/test_render_env.py`:
```python
def test_integration_render_using_fixtures(tmp_path: Path) -> None:
    fixtures = Path(__file__).resolve().parent / "fixtures" / "render"
    vault = render_env.load_vault(fixtures / "vault.yaml")
    manifest = render_env.load_manifest(fixtures / "manifest.demo.yaml")
    out = render_env.render_stack(vault, manifest)
    assert "OPENROUTER_API_KEY=sk-or-fixture" in out
    assert "ADMIN_TOKEN=admintok-fixture" in out
    assert "DATA_DIR=/data" in out
```

- [ ] **Step 7: Run all tests**

Run:
```bash
.venv/bin/pytest tests/test_render_env.py -v
```
Expected: all 22 tests pass.

- [ ] **Step 8: Commit**

```bash
git add scripts/render_env.py tests/test_render_env.py tests/fixtures/
git commit -m "feat(secrets): wire vault loading (sops + plaintext) and manifest discovery"
```

---

## Task 8: render_env.py — CLI (`--stack`, `--check`, `--dry-run`)

**Files:**
- Modify: `scripts/render_env.py`
- Modify: `tests/test_render_env.py`

- [ ] **Step 1: Add CLI behaviour tests**

Append to `tests/test_render_env.py`:
```python
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
```

- [ ] **Step 2: Run tests to confirm they fail**

Run:
```bash
.venv/bin/pytest tests/test_render_env.py -v
```
Expected: 4 new tests fail (`main` currently prints stub and returns 1).

- [ ] **Step 3: Implement the real CLI in `scripts/render_env.py`**

Replace the stub `main` with:
```python
import argparse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render per-stack .env files from sops vault + manifests"
    )
    parser.add_argument(
        "--root",
        default=str(Path(__file__).resolve().parent.parent),
        help="Repo root (default: parent of scripts/)",
    )
    parser.add_argument(
        "--vault",
        default=None,
        help="Path to vault file (default: <root>/secrets/vault.sops.yaml)",
    )
    parser.add_argument(
        "--stack",
        action="append",
        default=None,
        help="Render only the named stack (may be repeated). Use the directory "
        "name (e.g. 'news-feed' or 'secretary/ingest').",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate without writing. Exits non-zero on any error.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print rendered output to stdout instead of writing files.",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    vault_path = Path(args.vault) if args.vault else root / "secrets" / "vault.sops.yaml"

    if not vault_path.exists():
        print(f"error: vault not found at {vault_path}", file=sys.stderr)
        return 2

    try:
        vault = load_vault(vault_path)
    except RenderError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    manifests = find_manifests(root)

    if args.stack:
        wanted: set[str] = set(args.stack)
        def stack_label(p: Path) -> str:
            if p.name == "deploy.manifest.yaml":
                return "deploy"
            return str(p.parent.relative_to(root))
        manifests = [m for m in manifests if stack_label(m) in wanted]
        if not manifests:
            print(f"error: no manifests matched --stack {args.stack}", file=sys.stderr)
            return 2

    failures: list[str] = []
    for manifest_path in manifests:
        try:
            manifest = load_manifest(manifest_path)
            rendered = render_stack(vault, manifest)
        except RenderError as e:
            failures.append(f"{manifest_path}: {e}")
            continue
        if args.dry_run:
            print(f"--- {manifest_path} ---")
            print(rendered)
            continue
        if args.check:
            continue
        out_path = output_path(manifest_path)
        out_path.write_text(rendered)
        print(f"  wrote {out_path.relative_to(root)}")

    if failures:
        print(f"\n{len(failures)} error(s):", file=sys.stderr)
        for line in failures:
            print(f"  {line}", file=sys.stderr)
        return 1
    return 0
```

- [ ] **Step 4: Run all tests**

Run:
```bash
.venv/bin/pytest tests/test_render_env.py -v
```
Expected: all 26 tests pass.

- [ ] **Step 5: Make the script executable and smoke-test from the CLI**

Run:
```bash
chmod +x scripts/render_env.py
.venv/bin/python scripts/render_env.py --help
```
Expected: prints the argparse help.

- [ ] **Step 6: Commit**

```bash
git add scripts/render_env.py tests/test_render_env.py
git commit -m "feat(secrets): render_env CLI with --stack, --check, --dry-run"
```

---

## Task 9: Create `deploy.manifest.yaml` (root)

**Files:**
- Create: `deploy.manifest.yaml`

- [ ] **Step 1: Write the deploy manifest**

Create `deploy.manifest.yaml` at repo root:
```yaml
# Drives generation of ./.env.deploy for scripts/deploy.sh.
# Read by scripts/render_env.py alongside per-stack manifests.
env:
  NAS_USER:          shared.nas.user
  NAS_HOST:          shared.nas.host
  NAS_PORT:          shared.nas.port
  NAS_SSH_KEY:       shared.nas.ssh_key
  NAS_TARGET_PATH:   shared.nas.target_path
  NAS_SUDO_PASSWORD: shared.nas.sudo_password

literals:
  NAS_SSH_ALIAS: nas
```

- [ ] **Step 2: Validate the manifest against the schema**

Run:
```bash
.venv/bin/python -c "
import json, yaml
from pathlib import Path
from jsonschema import Draft202012Validator
schema = json.loads(Path('secrets/manifest.schema.json').read_text())
doc = yaml.safe_load(Path('deploy.manifest.yaml').read_text())
errors = list(Draft202012Validator(schema).iter_errors(doc))
if errors:
    for e in errors: print('FAIL:', e.message)
    raise SystemExit(1)
print('deploy.manifest.yaml: schema OK')
"
```
Expected: `deploy.manifest.yaml: schema OK`.

- [ ] **Step 3: Commit**

```bash
git add deploy.manifest.yaml
git commit -m "feat(secrets): add root deploy.manifest.yaml for .env.deploy generation"
```

---

## Task 10: Author plaintext vault from current `.env` files

**Files:**
- Create: `secrets/vault.yaml` (PLAINTEXT, will be encrypted in Task 11; gitignored — added in Task 17)

This task is hand-work: collect every secret from existing `.env` files and `.env` (root) into one structured YAML following spec §3. The plaintext vault never gets committed — Task 11 encrypts it, Task 17 adds the plaintext name to `.gitignore`.

- [ ] **Step 1: Inventory current secret values into a working scratch file**

Run (this dumps masked key names so you can see structure, then read each file individually to grab values into the vault):
```bash
for f in $(find . -maxdepth 3 -name '.env' -not -path './.git/*'); do
  echo "=== $f ==="
  grep -E '^[A-Z_]+=' "$f" | sed 's/=.*/=…/'
done
```
This prints the key inventory per file. The real values stay in your editor — do not echo them.

- [ ] **Step 2: Create `secrets/vault.yaml` (plaintext) from the spec §3 template**

Open `secrets/vault.yaml` in your editor and fill in real values from the current `.env` files. Use the schema below verbatim; replace each `<value-from-...>` placeholder with the actual value. Some stacks may not need every field — leave a field out if no current `.env` has it.

```yaml
shared:
  llm:
    openrouter_api_key: <value-from-news-feed/.env OPENROUTER_API_KEY>
    anthropic_api_key:  <value-from-news-feed/.env ANTHROPIC_API_KEY>
    cohere_api_key:     <value-from-secretary/query/.env COHERE_API_KEY>
  notion:
    secretary_token:    <value-from-secretary/ingest/.env SECRETARY_NOTION_TOKEN>
  nas:
    user:               <value-from-./.env NAS_USER>
    host:               <value-from-./.env NAS_HOST>
    port:               "2222"
    ssh_key:            "~/.ssh/id_ed25519"
    target_path:        /volume2/docker
    sudo_password:      <ROTATED-value-not-the-leaked-one>

stacks:
  homepage:
    nas_volume_root:     /volume2
    nas_volume_storage:  /volume1
    allowed_hosts:       <value-from-homepage/.env HOMEPAGE_ALLOWED_HOSTS>
    var_ddns_base_http:  <value-from-homepage/.env HOMEPAGE_VAR_DDNS_BASE_HTTP>
    var_ddns_base_https: <value-from-homepage/.env HOMEPAGE_VAR_DDNS_BASE_HTTPS>
    var_quickconnect_url: <value-from-homepage/.env HOMEPAGE_VAR_QUICKCONNECT_URL>
    var_nas_url:         <value-from-homepage/.env HOMEPAGE_VAR_NAS_URL>
    var_nas_username:    <value-from-homepage/.env HOMEPAGE_VAR_NAS_USERNAME>
    var_nas_password:    <value-from-homepage/.env HOMEPAGE_VAR_NAS_PASSWORD>
    var_jellyfin_url:    <value-from-homepage/.env HOMEPAGE_VAR_JELLYFIN_URL>
    var_jellyfin_key:    <value-from-homepage/.env HOMEPAGE_VAR_JELLYFIN_KEY>
    var_plex_url:        <value-from-homepage/.env HOMEPAGE_VAR_PLEX_URL>
    var_plex_key:        <value-from-homepage/.env HOMEPAGE_VAR_PLEX_KEY>
    var_portainer_url:   <value-from-homepage/.env HOMEPAGE_VAR_PORTAINER_URL>
    var_portainer_key:   <value-from-homepage/.env HOMEPAGE_VAR_PORTAINER_KEY>
    var_uptime_kuma_url: <value-from-homepage/.env HOMEPAGE_VAR_UPTIME_KUMA_URL>
    var_uptime_kuma_slug: <value-from-homepage/.env HOMEPAGE_VAR_UPTIME_KUMA_SLUG>
    var_maid_tracker_url: <value-from-homepage/.env HOMEPAGE_VAR_MAID_TRACKER_URL>
    var_torrentwatch_url: <value-from-homepage/.env HOMEPAGE_VAR_TORRENTWATCH_URL>
    var_news_feed_http:  <value-from-homepage/.env HOMEPAGE_VAR_NEWS_FEED_HTTP>
    var_news_feed_https: <value-from-homepage/.env HOMEPAGE_VAR_NEWS_FEED_HTTPS>
    var_hermes_http:     <value-from-homepage/.env HOMEPAGE_VAR_HERMES_HTTP>
    var_hermes_https:    <value-from-homepage/.env HOMEPAGE_VAR_HERMES_HTTPS>
    var_n8n_http:        <value-from-homepage/.env HOMEPAGE_VAR_N8N_HTTP>
    var_n8n_https:       <value-from-homepage/.env HOMEPAGE_VAR_N8N_HTTPS>

  news_feed:
    line:
      channel_access_token: <value-from-news-feed/.env LINE_CHANNEL_ACCESS_TOKEN>
      user_id:              <value-from-news-feed/.env LINE_USER_ID>
    telegram:
      bot_token: <value-from-news-feed/.env NEWS_FEED_TELEGRAM_BOT_TOKEN>
      chat_id:   <value-from-news-feed/.env TELEGRAM_CHAT_ID>
    admin_token: <value-from-news-feed/.env ADMIN_TOKEN>

  hermes_agent:
    telegram:
      bot_token:       <value-from-hermes-agent/.env HERMES_TELEGRAM_BOT_TOKEN>
      allowed_users:   <value-from-hermes-agent/.env TELEGRAM_ALLOWED_USERS>
    discord:
      bot_token:       <value-from-hermes-agent/.env DISCORD_BOT_TOKEN>
      allowed_guilds:  <value-from-hermes-agent/.env DISCORD_ALLOWED_GUILDS>
    openrouter_api_key: <value-from-hermes-agent/.env OPENROUTER_API_KEY>
    uid: "1000"
    gid: "100"

  watchtower:
    line:
      channel_access_token: <value-from-watchtower/.env WATCHTOWER_LINE_CHANNEL_ACCESS_TOKEN>
      user_id:              <value-from-watchtower/.env WATCHTOWER_LINE_USER_ID>
    telegram:
      bot_token: <value-from-watchtower/.env WATCHTOWER_TELEGRAM_BOT_TOKEN>
      chat_id:   <value-from-watchtower/.env TELEGRAM_CHAT_ID>

  torrentwatch:
    site:
      username: <value-from-torrentwatch/.env TORRENTWATCH_SITE_USERNAME>
      password: <value-from-torrentwatch/.env TORRENTWATCH_SITE_PASSWORD>
    default_urls:  <value-from-torrentwatch/.env TORRENTWATCH_DEFAULT_URLS>
    torrent_path:  <value-from-torrentwatch/.env NAS_TORRENT_PATH>
    line:
      access_token: <value-from-torrentwatch/.env TORRENTWATCH_LINE_ACCESS_TOKEN>
      user_id:      <value-from-torrentwatch/.env TORRENTWATCH_LINE_USER_ID>
    telegram:
      bot_token: <value-from-torrentwatch/.env TORRENTWATCH_TELEGRAM_BOT_TOKEN>
      chat_id:   <value-from-torrentwatch/.env TORRENTWATCH_TELEGRAM_CHAT_ID>
    nginx_basic_auth:
      user: <value-from-torrentwatch/.env NGINX_BASIC_AUTH_USER>
      pass: <value-from-torrentwatch/.env NGINX_BASIC_AUTH_PASS>

  maid_tracker:
    line:
      channel_access_token: <value-from-maid-tracker/.env MAID_LINE_CHANNEL_ACCESS_TOKEN>
      channel_secret:       <value-from-maid-tracker/.env MAID_LINE_CHANNEL_SECRET>
      group_id:             <value-from-maid-tracker/.env MAID_LINE_GROUP_ID>
    nginx_basic_auth:
      user: <value-from-maid-tracker/.env NGINX_BASIC_AUTH_USER>
      pass: <value-from-maid-tracker/.env NGINX_BASIC_AUTH_PASS>

  secretary:
    n8n:
      basic_auth_user:     <value-from-secretary/.env N8N_BASIC_AUTH_USER>
      basic_auth_password: <value-from-secretary/.env N8N_BASIC_AUTH_PASSWORD>
      webhook_url:         <value-from-secretary/.env N8N_WEBHOOK_URL>
    ingest:
      qdrant_url:        <value-from-secretary/ingest/.env QDRANT_URL>
      collection_name:   <value-from-secretary/ingest/.env COLLECTION_NAME>
      state_db:          <value-from-secretary/ingest/.env STATE_DB>
      notion_source_type: <value-from-secretary/ingest/.env NOTION_SOURCE_TYPE>
      notion_database_id: <value-from-secretary/ingest/.env NOTION_DATABASE_ID>
      notion_root_page_id: <value-from-secretary/ingest/.env NOTION_ROOT_PAGE_ID>
    query:
      qdrant_url:           <value-from-secretary/query/.env QDRANT_URL>
      collection_name:      <value-from-secretary/query/.env COLLECTION_NAME>
      llm_provider:         <value-from-secretary/query/.env LLM_PROVIDER>
      anthropic_api_key:    <value-from-secretary/query/.env ANTHROPIC_API_KEY>
      anthropic_model:      <value-from-secretary/query/.env ANTHROPIC_MODEL>
      openrouter_api_key:   <value-from-secretary/query/.env OPENROUTER_API_KEY>
      openrouter_model:     <value-from-secretary/query/.env OPENROUTER_MODEL>
      openrouter_base_url:  <value-from-secretary/query/.env OPENROUTER_BASE_URL>
      nous_model:           <value-from-secretary/query/.env NOUS_MODEL>
      cohere_rerank_model:  <value-from-secretary/query/.env COHERE_RERANK_MODEL>

  uptime_kuma:
    nas_volume_root: /volume2

  jellyfin:
    nas_volume_root: /volume2
    nas_media_root:  /volume1
```

- [ ] **Step 3: Validate the vault is well-formed YAML**

Run:
```bash
.venv/bin/python -c "
import yaml; doc = yaml.safe_load(open('secrets/vault.yaml')); 
print('OK' if isinstance(doc, dict) else 'FAIL')
"
```
Expected: `OK`.

- [ ] **Step 4: Do NOT commit yet — Task 11 encrypts before committing**

Verify there is no `secrets/vault.yaml` in `git status` after Task 17 sets the gitignore. For now, leave it on disk for Task 11.

---

## Task 11: Encrypt the vault

**Files:**
- Create: `secrets/vault.sops.yaml` (encrypted, committed)
- Delete (after encrypting): `secrets/vault.yaml`

- [ ] **Step 1: Encrypt with sops using the config from Task 1**

Run:
```bash
SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt \
  sops --config secrets/.sops.yaml -e secrets/vault.yaml > secrets/vault.sops.yaml
grep -q 'sops:' secrets/vault.sops.yaml && echo "OK: encrypted with sops metadata"
```
Expected: `OK: encrypted with sops metadata`.

- [ ] **Step 2: Round-trip-decrypt to verify integrity**

Run:
```bash
SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops -d secrets/vault.sops.yaml | head -5
```
Expected: prints the first few lines of the plaintext vault (e.g., `shared:\n  llm:\n    openrouter_api_key: sk-...`).

- [ ] **Step 3: Delete the plaintext file**

Run:
```bash
rm secrets/vault.yaml
ls secrets/
```
Expected: `secrets/` contains `.sops.yaml`, `manifest.schema.json`, `vault.sops.yaml` and nothing else.

- [ ] **Step 4: Commit the encrypted vault**

```bash
git add secrets/vault.sops.yaml
git commit -m "feat(secrets): add encrypted vault.sops.yaml (sops+age)"
```

---

## Task 12: Author per-stack manifests

**Files:** create one `secrets.manifest.yaml` per stack listed below.

Each manifest is a **mechanical translation** of the current `<stack>/.env` keys. Phase A keeps the current ENV name on the LEFT of every mapping (no rename). The RIGHT is the vault path you authored in Task 10.

After every manifest file is created, the equivalence check in Task 15 verifies the output matches the existing `.env`.

- [ ] **Step 1: Create `homepage/secrets.manifest.yaml`**

```yaml
env:
  NAS_VOLUME_ROOT:                  stacks.homepage.nas_volume_root
  NAS_VOLUME_STORAGE:               stacks.homepage.nas_volume_storage
  HOMEPAGE_ALLOWED_HOSTS:           stacks.homepage.allowed_hosts
  HOMEPAGE_VAR_DDNS_BASE_HTTP:      stacks.homepage.var_ddns_base_http
  HOMEPAGE_VAR_DDNS_BASE_HTTPS:     stacks.homepage.var_ddns_base_https
  HOMEPAGE_VAR_QUICKCONNECT_URL:    stacks.homepage.var_quickconnect_url
  HOMEPAGE_VAR_NAS_URL:             stacks.homepage.var_nas_url
  HOMEPAGE_VAR_NAS_USERNAME:        stacks.homepage.var_nas_username
  HOMEPAGE_VAR_NAS_PASSWORD:        stacks.homepage.var_nas_password
  HOMEPAGE_VAR_JELLYFIN_URL:        stacks.homepage.var_jellyfin_url
  HOMEPAGE_VAR_JELLYFIN_KEY:        stacks.homepage.var_jellyfin_key
  HOMEPAGE_VAR_PLEX_URL:            stacks.homepage.var_plex_url
  HOMEPAGE_VAR_PLEX_KEY:            stacks.homepage.var_plex_key
  HOMEPAGE_VAR_PORTAINER_URL:       stacks.homepage.var_portainer_url
  HOMEPAGE_VAR_PORTAINER_KEY:       stacks.homepage.var_portainer_key
  HOMEPAGE_VAR_UPTIME_KUMA_URL:     stacks.homepage.var_uptime_kuma_url
  HOMEPAGE_VAR_UPTIME_KUMA_SLUG:    stacks.homepage.var_uptime_kuma_slug
  HOMEPAGE_VAR_MAID_TRACKER_URL:    stacks.homepage.var_maid_tracker_url
  HOMEPAGE_VAR_TORRENTWATCH_URL:    stacks.homepage.var_torrentwatch_url
  HOMEPAGE_VAR_NEWS_FEED_HTTP:      stacks.homepage.var_news_feed_http
  HOMEPAGE_VAR_NEWS_FEED_HTTPS:     stacks.homepage.var_news_feed_https
  HOMEPAGE_VAR_HERMES_HTTP:         stacks.homepage.var_hermes_http
  HOMEPAGE_VAR_HERMES_HTTPS:        stacks.homepage.var_hermes_https
  HOMEPAGE_VAR_N8N_HTTP:            stacks.homepage.var_n8n_http
  HOMEPAGE_VAR_N8N_HTTPS:           stacks.homepage.var_n8n_https
```

- [ ] **Step 2: Create `news-feed/secrets.manifest.yaml`**

```yaml
env:
  ANTHROPIC_API_KEY:              shared.llm.anthropic_api_key
  OPENROUTER_API_KEY:             shared.llm.openrouter_api_key
  LINE_CHANNEL_ACCESS_TOKEN:      stacks.news_feed.line.channel_access_token
  LINE_USER_ID:                   stacks.news_feed.line.user_id
  NEWS_FEED_TELEGRAM_BOT_TOKEN:   stacks.news_feed.telegram.bot_token
  TELEGRAM_CHAT_ID:               stacks.news_feed.telegram.chat_id
  ADMIN_TOKEN:                    stacks.news_feed.admin_token

literals:
  SUMMARIZER_PROVIDER: anthropic
  SUMMARIZER_MODEL:    claude-sonnet-4-6
  DIGEST_TIMES:        "07:00,12:00,18:00"
  ENABLED_SOURCES:     techcrunch_ai,venturebeat,theverge,arstechnica,gsmarena,9to5mac,android_authority
  RETENTION_DAYS:      "30"
  DATA_DIR:            /data
```

> Verify these `literals:` exactly match the values currently in `news-feed/.env` (open the existing file and copy them across). If any differ, defer to the existing `.env` value to keep Phase 3 equivalence passing.

- [ ] **Step 3: Create `hermes-agent/secrets.manifest.yaml`**

```yaml
env:
  OPENROUTER_API_KEY:      stacks.hermes_agent.openrouter_api_key
  HERMES_TELEGRAM_BOT_TOKEN: stacks.hermes_agent.telegram.bot_token
  TELEGRAM_ALLOWED_USERS:  stacks.hermes_agent.telegram.allowed_users
  DISCORD_BOT_TOKEN:       stacks.hermes_agent.discord.bot_token
  DISCORD_ALLOWED_GUILDS:  stacks.hermes_agent.discord.allowed_guilds

literals:
  HERMES_UID: "1000"
  HERMES_GID: "100"
```

- [ ] **Step 4: Create `watchtower/secrets.manifest.yaml`**

```yaml
env:
  WATCHTOWER_LINE_CHANNEL_ACCESS_TOKEN: stacks.watchtower.line.channel_access_token
  WATCHTOWER_LINE_USER_ID:              stacks.watchtower.line.user_id
  WATCHTOWER_TELEGRAM_BOT_TOKEN:        stacks.watchtower.telegram.bot_token
  TELEGRAM_CHAT_ID:                     stacks.watchtower.telegram.chat_id
```

- [ ] **Step 5: Create `torrentwatch/secrets.manifest.yaml`**

```yaml
env:
  NAS_TORRENT_PATH:               stacks.torrentwatch.torrent_path
  TORRENTWATCH_SITE_USERNAME:     stacks.torrentwatch.site.username
  TORRENTWATCH_SITE_PASSWORD:     stacks.torrentwatch.site.password
  TORRENTWATCH_DEFAULT_URLS:      stacks.torrentwatch.default_urls
  NGINX_BASIC_AUTH_USER:          stacks.torrentwatch.nginx_basic_auth.user
  NGINX_BASIC_AUTH_PASS:          stacks.torrentwatch.nginx_basic_auth.pass
  TORRENTWATCH_LINE_ACCESS_TOKEN: stacks.torrentwatch.line.access_token
  TORRENTWATCH_LINE_USER_ID:      stacks.torrentwatch.line.user_id
  TORRENTWATCH_TELEGRAM_BOT_TOKEN: stacks.torrentwatch.telegram.bot_token
  TORRENTWATCH_TELEGRAM_CHAT_ID:  stacks.torrentwatch.telegram.chat_id
```

- [ ] **Step 6: Create `maid-tracker/secrets.manifest.yaml`**

```yaml
env:
  MAID_LINE_CHANNEL_ACCESS_TOKEN: stacks.maid_tracker.line.channel_access_token
  MAID_LINE_CHANNEL_SECRET:       stacks.maid_tracker.line.channel_secret
  MAID_LINE_GROUP_ID:             stacks.maid_tracker.line.group_id
  NGINX_BASIC_AUTH_USER:          stacks.maid_tracker.nginx_basic_auth.user
  NGINX_BASIC_AUTH_PASS:          stacks.maid_tracker.nginx_basic_auth.pass

literals:
  MONTHLY_REPORT_TIME: "20:00"
```

Cross-check `MONTHLY_REPORT_TIME` against the live `maid-tracker/.env` and adjust if it differs.

- [ ] **Step 7: Create `secretary/secrets.manifest.yaml`**

```yaml
env:
  N8N_BASIC_AUTH_USER:     stacks.secretary.n8n.basic_auth_user
  N8N_BASIC_AUTH_PASSWORD: stacks.secretary.n8n.basic_auth_password
  N8N_WEBHOOK_URL:         stacks.secretary.n8n.webhook_url
```

- [ ] **Step 8: Create `secretary/ingest/secrets.manifest.yaml`**

```yaml
env:
  SECRETARY_NOTION_TOKEN: shared.notion.secretary_token

literals:
  QDRANT_URL:           http://qdrant:6333
  COLLECTION_NAME:      secretary_notes
  STATE_DB:             /data/ingest_state.db
  NOTION_SOURCE_TYPE:   search
  NOTION_DATABASE_ID:   ""
  NOTION_ROOT_PAGE_ID:  ""
```

Cross-check every `literals:` value against `secretary/ingest/.env` and adjust if it differs.

- [ ] **Step 9: Create `secretary/query/secrets.manifest.yaml`**

```yaml
env:
  ANTHROPIC_API_KEY:   stacks.secretary.query.anthropic_api_key
  OPENROUTER_API_KEY:  stacks.secretary.query.openrouter_api_key
  COHERE_API_KEY:      shared.llm.cohere_api_key

literals:
  QDRANT_URL:          http://qdrant:6333
  COLLECTION_NAME:     secretary_notes
  LLM_PROVIDER:        openrouter
  ANTHROPIC_MODEL:     claude-sonnet-4-20250514
  OPENROUTER_MODEL:    google/gemini-2.5-flash
  OPENROUTER_BASE_URL: https://openrouter.ai/api/v1
  NOUS_MODEL:          Hermes-4-70B
  COHERE_RERANK_MODEL: rerank-multilingual-v3.0
```

Cross-check every `literals:` value against `secretary/query/.env` and adjust if it differs.

- [ ] **Step 10: Create `uptime-kuma/secrets.manifest.yaml`**

```yaml
literals:
  NAS_VOLUME_ROOT: /volume2
```

(Treat NAS_VOLUME_ROOT as a literal here because it's a hard-coded path, not a secret. If the current `uptime-kuma/.env` derives it elsewhere, mirror that.)

- [ ] **Step 11: Create `jellyfin/secrets.manifest.yaml`**

```yaml
literals:
  NAS_VOLUME_ROOT: /volume2
  NAS_MEDIA_ROOT:  /volume1
```

- [ ] **Step 12: Validate every new manifest against the schema**

Run:
```bash
.venv/bin/python -c "
import json, yaml, sys
from pathlib import Path
from jsonschema import Draft202012Validator
schema = json.loads(Path('secrets/manifest.schema.json').read_text())
v = Draft202012Validator(schema)
fail = False
for p in sorted(Path('.').rglob('secrets.manifest.yaml')):
    doc = yaml.safe_load(p.read_text()) or {}
    errors = list(v.iter_errors(doc))
    if errors:
        fail = True
        for e in errors:
            print(f'{p}: {e.message}')
    else:
        print(f'{p}: OK')
sys.exit(1 if fail else 0)
"
```
Expected: every manifest prints `OK`. Fix any failures before the commit step.

- [ ] **Step 13: Commit all manifests**

```bash
git add -- homepage/secrets.manifest.yaml news-feed/secrets.manifest.yaml \
  hermes-agent/secrets.manifest.yaml watchtower/secrets.manifest.yaml \
  torrentwatch/secrets.manifest.yaml maid-tracker/secrets.manifest.yaml \
  secretary/secrets.manifest.yaml secretary/ingest/secrets.manifest.yaml \
  secretary/query/secrets.manifest.yaml uptime-kuma/secrets.manifest.yaml \
  jellyfin/secrets.manifest.yaml
git commit -m "feat(secrets): add per-stack manifests (Phase A — current ENV names preserved)"
```

---

## Task 13: diff_envs.py — semantic equivalence checker

**Files:**
- Create: `scripts/diff_envs.py`
- Create: `tests/test_diff_envs.py`

- [ ] **Step 1: Write the failing semantic-diff tests**

Create `tests/test_diff_envs.py`:
```python
"""Tests for scripts/diff_envs.py — used during Phase A Step 3."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import diff_envs  # noqa: E402


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
.venv/bin/pytest tests/test_diff_envs.py -v
```
Expected: ImportError or all tests fail.

- [ ] **Step 3: Implement `scripts/diff_envs.py`**

Create `scripts/diff_envs.py`:
```python
#!/usr/bin/env python3
"""Semantic .env diff used during Phase A migration verification.

Two .env files are equivalent when, after unquoting and ignoring comments and
blank lines, they yield the same {key: value} mapping.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DiffResult:
    equivalent: bool
    missing: set[str] = field(default_factory=set)
    extra: set[str] = field(default_factory=set)
    changed: dict[str, tuple[str, str]] = field(default_factory=dict)


def _unquote(value: str) -> str:
    """Reverse the simple cases of compose-quote: strip surrounding ' or ".
    Multi-line/escaped values are out of scope (rejected by render_env)."""
    s = value
    if len(s) >= 2:
        if s[0] == s[-1] == "'":
            return s[1:-1]
        if s[0] == s[-1] == '"':
            return s[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return s


def parse(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        out[key] = _unquote(value.strip())
    return out


def diff(a: Path, b: Path) -> DiffResult:
    ma = parse(a)
    mb = parse(b)
    keys_a = set(ma)
    keys_b = set(mb)
    missing = keys_a - keys_b
    extra = keys_b - keys_a
    changed: dict[str, tuple[str, str]] = {}
    for k in keys_a & keys_b:
        if ma[k] != mb[k]:
            changed[k] = (ma[k], mb[k])
    return DiffResult(
        equivalent=not (missing or extra or changed),
        missing=missing,
        extra=extra,
        changed=changed,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("a", type=Path, help="first .env file")
    p.add_argument("b", type=Path, help="second .env file")
    args = p.parse_args(argv)
    r = diff(args.a, args.b)
    if r.equivalent:
        print(f"EQUIVALENT: {args.a} == {args.b}")
        return 0
    print(f"DIFFER: {args.a} vs {args.b}")
    if r.missing:
        print(f"  Only in {args.a.name}: {sorted(r.missing)}")
    if r.extra:
        print(f"  Only in {args.b.name}: {sorted(r.extra)}")
    if r.changed:
        for k, (va, vb) in sorted(r.changed.items()):
            print(f"  {k}: '{va}'  →  '{vb}'")
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run all tests**

Run:
```bash
.venv/bin/pytest tests/test_diff_envs.py -v
```
Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
chmod +x scripts/diff_envs.py
git add scripts/diff_envs.py tests/test_diff_envs.py
git commit -m "feat(secrets): add diff_envs.py for migration equivalence verification"
```

---

## Task 14: Phase 3 equivalence — backup current `.env` files and verify rendered output

**Files:**
- Create: `backup-pre-vault/` (working backup, not committed — will be deleted after verification)

This is the safety net: render the new pipeline, compare against the existing live `.env` files key-by-key. We do NOT overwrite the live files during this task — we render to a side path.

- [ ] **Step 1: Back up every current `.env` file**

Run:
```bash
mkdir -p backup-pre-vault
for f in $(find . -maxdepth 4 -name '.env' -not -path './.git/*' -not -path './.venv/*' -not -path './backup-pre-vault/*'); do
  dest="backup-pre-vault/${f#./}"
  mkdir -p "$(dirname "$dest")"
  cp "$f" "$dest"
done
find backup-pre-vault -type f | sort
```
Expected: prints a list ending with around a dozen `.env` paths under `backup-pre-vault/`.

- [ ] **Step 2: Render every stack to a side-by-side `.env.new` instead of clobbering**

Add `--suffix` support to `render_env.py` so verification doesn't overwrite live files yet. **First** add tests:

Append to `tests/test_render_env.py`:
```python
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
```

- [ ] **Step 3: Run the test to see it fail**

Run:
```bash
.venv/bin/pytest tests/test_render_env.py::test_main_with_suffix_writes_to_alternate_filename -v
```
Expected: fail with `unrecognized arguments: --suffix`.

- [ ] **Step 4: Implement `--suffix`**

In `scripts/render_env.py`, in `main`, add the argparse flag:
```python
    parser.add_argument(
        "--suffix",
        default="",
        help="Append this suffix to the output filename (e.g. '.new') — used "
        "for safe side-by-side rendering during migration.",
    )
```

And change the write call:
```python
        out_path = output_path(manifest_path)
        if args.suffix:
            out_path = out_path.with_name(out_path.name + args.suffix)
        out_path.write_text(rendered)
```

- [ ] **Step 5: Run all render_env tests**

Run:
```bash
.venv/bin/pytest tests/test_render_env.py -v
```
Expected: all 27 tests pass.

- [ ] **Step 6: Render every stack to `.env.new`**

Run:
```bash
SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt \
  .venv/bin/python scripts/render_env.py --suffix .new
```
Expected: prints `wrote …/.env.new` for every stack and `wrote .env.deploy.new`.

- [ ] **Step 7: Diff every rendered file against its backup**

Run:
```bash
fail=0
for new in $(find . -name '.env.new' -not -path './.git/*'); do
  old="backup-pre-vault/${new#./}"
  old="${old%.new}"  # strip the .new suffix to find the backed-up original
  if [ ! -f "$old" ]; then
    echo "WARN: no backup for $new"
    continue
  fi
  if ! .venv/bin/python scripts/diff_envs.py "$old" "$new" > /dev/null; then
    echo "DIFFER: $new"
    .venv/bin/python scripts/diff_envs.py "$old" "$new"
    fail=1
  fi
done
# .env.deploy.new vs the current root .env
if ! .venv/bin/python scripts/diff_envs.py backup-pre-vault/.env .env.deploy.new > /dev/null; then
  echo "DIFFER: .env.deploy.new"
  .venv/bin/python scripts/diff_envs.py backup-pre-vault/.env .env.deploy.new
  fail=1
fi
[ "$fail" = "0" ] && echo "ALL EQUIVALENT" || echo "FIXES NEEDED"
```
Expected: `ALL EQUIVALENT`.

If any stack differs:
- If a key is **missing** from the new output: that key isn't in the stack's `secrets.manifest.yaml` — add it (Task 12 revisit).
- If a key is **extra** in the new output: the manifest declared something not in the live `.env` — remove from manifest.
- If a key **changed value**: the vault has the wrong value — re-open vault with `make edit-vault` (or `sops secrets/vault.sops.yaml`) and fix.

Loop Step 6 → Step 7 until you see `ALL EQUIVALENT`.

- [ ] **Step 8: Clean up the `.env.new` side files**

Run:
```bash
find . -name '.env.new' -not -path './.git/*' -delete
rm -f .env.deploy.new
```

- [ ] **Step 9: Commit the `--suffix` flag**

```bash
git add scripts/render_env.py tests/test_render_env.py
git commit -m "feat(secrets): add --suffix flag for side-by-side render verification"
```

The `backup-pre-vault/` directory stays uncommitted (will be deleted after cutover succeeds in Task 19).

---

## Task 15: Makefile

**Files:**
- Create: `Makefile`

- [ ] **Step 1: Create the Makefile**

Create `Makefile` at repo root:
```makefile
AGE_KEY ?= $(HOME)/.config/sops/age/keys.txt
export SOPS_AGE_KEY_FILE = $(AGE_KEY)
PY = .venv/bin/python

.PHONY: secrets check edit-vault rotate-key clean-env test help

help:           ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-14s %s\n", $$1, $$2}'

secrets:        ## Render <stack>/.env + .env.deploy from vault + manifests
	@$(PY) scripts/render_env.py

check:          ## Validate manifests + vault consistency without writing
	@$(PY) scripts/render_env.py --check

edit-vault:     ## Open vault in $$EDITOR (sops decrypts on read, re-encrypts on save)
	@sops secrets/vault.sops.yaml

rotate-key:     ## Re-encrypt vault for current .sops.yaml recipients
	@sops updatekeys secrets/vault.sops.yaml

clean-env:      ## Remove all generated .env files (does not touch vault)
	@find . -name '.env' -not -path './.git/*' -not -path './.venv/*' -delete
	@rm -f .env.deploy

test:           ## Run repo-level pytest suite
	@$(PY) -m pytest tests/ -v
```

- [ ] **Step 2: Smoke-test the help target**

Run:
```bash
make help
```
Expected: prints the target list.

- [ ] **Step 3: Smoke-test `make check`**

Run:
```bash
make check
```
Expected: exit 0, no errors (it validates vault + manifests).

- [ ] **Step 4: Commit**

```bash
git add Makefile
git commit -m "feat(secrets): add Makefile entry points (secrets, check, edit-vault, etc.)"
```

---

## Task 16: `.gitignore` additions

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Append new ignore patterns**

Modify `.gitignore` — append:
```
.env.deploy
secrets/vault.yaml
```

The existing `.env` rule already covers every `<stack>/.env`. The two new lines guard:
- the generated root file `.env.deploy`
- the transient unencrypted intermediate at `secrets/vault.yaml` (used during edits)

- [ ] **Step 2: Verify nothing important becomes ignored**

Run:
```bash
git status --ignored | grep -E '(vault|env)' | head
```
Expected: only generated artifacts (e.g., `.env.deploy`, per-stack `.env`) show as ignored.

- [ ] **Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore(gitignore): add .env.deploy and secrets/vault.yaml"
```

---

## Task 17: deploy.sh modifications

**Files:**
- Modify: `scripts/deploy.sh`

Two changes:
1. Source `.env.deploy` instead of `.env`.
2. Add a fail-fast block to verify every stack has a rendered `.env` before tar.

- [ ] **Step 1: Change `ENV_FILE` to `.env.deploy`**

In `scripts/deploy.sh`, find this line near the top:
```bash
ENV_FILE="${PROJECT_ROOT}/.env"
```

Replace with:
```bash
ENV_FILE="${PROJECT_ROOT}/.env.deploy"
```

Also update the missing-file error message a few lines below:
```bash
if [[ ! -f "$ENV_FILE" ]]; then
  err "Config file not found: $ENV_FILE"
  echo "  Run 'make secrets' to generate it from secrets/vault.sops.yaml"
  exit 1
fi
```

- [ ] **Step 2: Add the pre-upload verification block**

In `scripts/deploy.sh`, find the start of the UPLOAD section (around line 124, right after the comment `# UPLOAD`):
```bash
if [[ "$RESTART_ONLY" == false ]]; then
```

Immediately after the matching opening `{`, before `printf "${C_BOLD}Source :${C_RESET} %s/\n" "${PROJECT_ROOT}"`, insert:
```bash
  # Pre-upload: every stack with a manifest must have a rendered .env
  log "Verifying generated .env files ..."
  MISSING=()
  for stack in "${ALL_STACKS[@]}"; do
    manifest="${PROJECT_ROOT}/${stack}/secrets.manifest.yaml"
    envfile="${PROJECT_ROOT}/${stack}/.env"
    if [[ -f "$manifest" && ! -f "$envfile" ]]; then
      MISSING+=("$stack")
    fi
  done
  if [[ ${#MISSING[@]} -gt 0 ]]; then
    err "Missing .env for: ${MISSING[*]}"
    echo "  Run 'make secrets' to regenerate from secrets/vault.sops.yaml"
    exit 1
  fi
  ok "All .env files present"
```

- [ ] **Step 3: Smoke-test the script's `--help`**

Run:
```bash
bash scripts/deploy.sh --help
```
Expected: prints usage, no errors. (Do NOT run a real deploy yet — that's Task 21.)

- [ ] **Step 4: Confirm the verification trips when an `.env` is missing**

Run:
```bash
rm -f uptime-kuma/.env
# Trigger only the verification step by mocking the connect check away —
# easiest: run a dry-run which still hits the verify block.
bash scripts/deploy.sh --dry-run -y 2>&1 | grep -E "(Missing|All .env)"
```
Expected: prints `✘ Missing .env for: uptime-kuma`.

Restore the file:
```bash
make secrets
ls uptime-kuma/.env
```

- [ ] **Step 5: Commit**

```bash
git add scripts/deploy.sh
git commit -m "feat(deploy): source .env.deploy and verify per-stack .env exist pre-upload"
```

---

## Task 18: Generate first real `.env` files and `.env.deploy` (in-place)

**Files:**
- Generated: `<stack>/.env`, `./.env.deploy` (all gitignored)

This task is the actual cutover for files — it overwrites the existing manually-maintained `.env` files with rendered output. Task 14 already proved equivalence with `--suffix`, so this is now safe.

- [ ] **Step 1: Render everything to live paths**

Run:
```bash
make secrets
```
Expected: prints `wrote …/.env` for every manifest plus `.env.deploy`.

- [ ] **Step 2: Spot-check one stack**

Run:
```bash
diff <(sort backup-pre-vault/news-feed/.env | grep -E '^[A-Z]') \
     <(sort news-feed/.env | grep -E '^[A-Z]')
```
Expected: no output (or only comment/header differences).

If you see real differences, fix the manifest (Task 12) or vault (`make edit-vault`) and re-render. Loop until clean.

- [ ] **Step 3: Verify deploy.sh dry-run passes the pre-upload check**

Run:
```bash
bash scripts/deploy.sh --dry-run -y 2>&1 | tail -20
```
Expected: includes `✔ All .env files present` and `Dry run complete`.

- [ ] **Step 4: No git commit needed — `.env` files are gitignored.**

---

## Task 19: Cutover — delete old artifacts

**Files:**
- Delete: `scripts/sync_env.py`
- Delete: `.env` (root, no longer used)
- Delete: `.env.example` (root)
- Delete: every `<stack>/.env.example`
- Delete: `backup-pre-vault/` (no longer needed once production deploy succeeds)

Only execute this task **after** Task 18 succeeded and you have confirmed the rendered `.env` files match the prior live values.

- [ ] **Step 1: Remove `sync_env.py`**

Run:
```bash
git rm scripts/sync_env.py
```

- [ ] **Step 2: Remove root `.env.example`**

Run:
```bash
git rm .env.example
```

- [ ] **Step 3: Remove the root plaintext `.env`**

The root `.env` is gitignored (already not in the index). Just delete it from disk:
```bash
rm .env
```

- [ ] **Step 4: Remove every `<stack>/.env.example`**

Run:
```bash
git rm $(find . -maxdepth 3 -name '.env.example' -not -path './.git/*')
```

- [ ] **Step 5: Commit the deletions**

```bash
git commit -m "refactor(secrets): remove sync_env.py and all .env.example after vault cutover"
```

- [ ] **Step 6: Hold off deleting `backup-pre-vault/` until Task 21 production rollout succeeds**

(Do not delete the backup directory yet — keep it as a rollback safety net through the production smoke test. It is uncommitted and won't pollute git.)

---

## Task 20: CI workflow and test vault

**Files:**
- Create: `secrets/test-vault.sops.yaml`
- Create: `.github/workflows/secrets.yml`

The CI vault holds dummy values and is encrypted with a **separate** age recipient — never the prod recipient list.

- [ ] **Step 1: Generate a CI-only age key**

Run on your workstation:
```bash
age-keygen 2>/tmp/_ci_pub | tee /tmp/_ci_priv > /dev/null
echo "Public key (add to .sops.yaml):"; cat /tmp/_ci_pub
echo "Private key (add to GitHub Actions secret SOPS_AGE_KEY):"
cat /tmp/_ci_priv
```
Expected: prints a public key starting with `age1…` and a private key block starting with `AGE-SECRET-KEY-…`.

Copy the **private** key into your GitHub repo secrets as `SOPS_AGE_KEY`. Copy the **public** key for Step 2.

Then delete the temp files:
```bash
rm /tmp/_ci_priv /tmp/_ci_pub
```

- [ ] **Step 2: Update `secrets/.sops.yaml` to map the CI public key to the test vault only**

In `secrets/.sops.yaml`, replace the `secrets/test-vault.sops.yaml` rule with the CI key:
```yaml
creation_rules:
  - path_regex: secrets/vault\.sops\.yaml$
    age: AGE_PUBLIC_KEY_FROM_TASK_1
    encrypted_regex: '^(.*)$'
  - path_regex: secrets/test-vault\.sops\.yaml$
    age: CI_AGE_PUBLIC_KEY_FROM_STEP_1
    encrypted_regex: '^(.*)$'
```
The prod vault recipient list stays unchanged; only the test vault uses the CI key.

- [ ] **Step 3: Create a plaintext dummy vault**

Create `secrets/test-vault.yaml` (will be encrypted in Step 4, then deleted):
```yaml
shared:
  llm:
    openrouter_api_key: DUMMY_OPENROUTER
    anthropic_api_key:  DUMMY_ANTHROPIC
    cohere_api_key:     DUMMY_COHERE
  notion:
    secretary_token: DUMMY_NOTION
  nas:
    user:          dummy
    host:          dummy.example
    port:          "2222"
    ssh_key:       "~/.ssh/id_ed25519"
    target_path:   /volume2/docker
    sudo_password: DUMMY_SUDO
stacks:
  homepage:
    nas_volume_root: /volume2
    nas_volume_storage: /volume1
    allowed_hosts: dummy.example
    var_ddns_base_http: http://dummy.example
    var_ddns_base_https: https://dummy.example
    var_quickconnect_url: https://dummy.quickconnect.to
    var_nas_url: http://dummy.example:5000
    var_nas_username: ""
    var_nas_password: ""
    var_jellyfin_url: http://dummy.example:8096
    var_jellyfin_key: ""
    var_plex_url: http://dummy.example:32400
    var_plex_key: ""
    var_portainer_url: http://dummy.example:9000
    var_portainer_key: ""
    var_uptime_kuma_url: http://dummy.example:3001
    var_uptime_kuma_slug: nas-status
    var_maid_tracker_url: https://dummy.example:15055
    var_torrentwatch_url: http://dummy.example:5059
    var_news_feed_http: http://dummy.example:5064
    var_news_feed_https: https://dummy.example:15064
    var_hermes_http: http://dummy.example:5063
    var_hermes_https: https://dummy.example:15063
    var_n8n_http: http://dummy.example:5678
    var_n8n_https: https://dummy.example:15678
  news_feed:
    line:     { channel_access_token: dummy, user_id: dummy }
    telegram: { bot_token: dummy, chat_id: dummy }
    admin_token: dummy
  hermes_agent:
    telegram: { bot_token: dummy, allowed_users: dummy }
    discord:  { bot_token: dummy, allowed_guilds: dummy }
    openrouter_api_key: DUMMY_OPENROUTER
  watchtower:
    line:     { channel_access_token: dummy, user_id: dummy }
    telegram: { bot_token: dummy, chat_id: dummy }
  torrentwatch:
    site: { username: dummy, password: dummy }
    default_urls: https://dummy.example
    torrent_path: /tmp/torrents
    line: { access_token: dummy, user_id: dummy }
    telegram: { bot_token: dummy, chat_id: dummy }
    nginx_basic_auth: { user: dummy, pass: dummy }
  maid_tracker:
    line: { channel_access_token: dummy, channel_secret: dummy, group_id: dummy }
    nginx_basic_auth: { user: dummy, pass: dummy }
  secretary:
    n8n: { basic_auth_user: dummy, basic_auth_password: dummy, webhook_url: https://dummy }
    query:
      anthropic_api_key:  DUMMY_ANTHROPIC
      openrouter_api_key: DUMMY_OPENROUTER
```

- [ ] **Step 4: Encrypt the test vault and delete the plaintext**

Run:
```bash
SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt \
  sops --config secrets/.sops.yaml -e secrets/test-vault.yaml > secrets/test-vault.sops.yaml
rm secrets/test-vault.yaml
```

- [ ] **Step 5: Create the CI workflow**

Create `.github/workflows/secrets.yml`:
```yaml
name: secrets

on:
  pull_request:
    paths:
      - 'secrets/**'
      - 'scripts/render_env.py'
      - 'scripts/diff_envs.py'
      - 'tests/**'
      - '**/secrets.manifest.yaml'
      - 'deploy.manifest.yaml'
  push:
    branches: [main]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install sops + age
        run: |
          curl -sLo /tmp/sops "https://github.com/getsops/sops/releases/latest/download/sops-v3.9.4.linux.amd64"
          sudo install -m 0755 /tmp/sops /usr/local/bin/sops
          curl -sL "https://github.com/FiloSottile/age/releases/latest/download/age-v1.2.0-linux-amd64.tar.gz" | tar -xz -C /tmp
          sudo install -m 0755 /tmp/age/age /usr/local/bin/age

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.14'

      - name: Install Python deps
        run: pip install pytest pyyaml jsonschema

      - name: Load CI age key
        env:
          SOPS_AGE_KEY: ${{ secrets.SOPS_AGE_KEY }}
        run: |
          mkdir -p ~/.config/sops/age
          echo "$SOPS_AGE_KEY" > ~/.config/sops/age/keys.txt
          chmod 600 ~/.config/sops/age/keys.txt

      - name: Run unit tests
        run: pytest tests/ -v

      - name: Render test vault and validate manifests
        run: |
          python scripts/render_env.py --check --vault secrets/test-vault.sops.yaml
```

- [ ] **Step 6: Commit**

```bash
git add secrets/.sops.yaml secrets/test-vault.sops.yaml .github/workflows/secrets.yml
git commit -m "ci(secrets): add CI workflow with separate test vault and age key"
```

- [ ] **Step 7: Push and verify CI passes**

```bash
git push origin main
gh run watch --interval 5 2>/dev/null || echo "Manual check needed — open Actions tab"
```
Expected: workflow run succeeds. If it fails, read the logs, fix, push again.

---

## Task 21: Documentation — CLAUDE.md and README.md

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`

- [ ] **Step 1: Update CLAUDE.md "Environment & Deployment Gotchas" section**

In `CLAUDE.md`, locate the "## 🛠️ Environment & Deployment Gotchas" section. Replace the `**Per-Stack .env**` and `**.env.example**` bullets with:

```markdown
*   **Secrets vault:** ทุก secret ทั้ง project อยู่ใน `secrets/vault.sops.yaml` (encrypted ด้วย sops+age, commit ใน git ได้). แต่ละ stack มี `secrets.manifest.yaml` บอกว่าตัวเองใช้ key อะไร mapped จาก vault path ไหน — generator `scripts/render_env.py` (เรียกผ่าน `make secrets`) สร้าง `<stack>/.env` (gitignored) ก่อน deploy
*   **Workflow:** `make edit-vault` (sops decrypts on read, re-encrypts on save) → `make secrets` → `./scripts/deploy.sh`
*   **NAS ไม่ต้องลง sops/age:** decryption เกิดที่ workstation, NAS รับ `<stack>/.env` plaintext เหมือนเดิม
*   **Portability:** ไปเครื่องใหม่ → `age-keygen`, เพิ่ม public key ใน `secrets/.sops.yaml`, รัน `sops updatekeys secrets/vault.sops.yaml`, commit → เครื่องใหม่ใช้ `make secrets` ได้
*   **Root `.env.deploy`:** generator สร้างจาก `deploy.manifest.yaml` + `shared.nas.*` ใน vault, `deploy.sh` source ไฟล์นี้ (ทดแทน root `.env` เดิม) — ไม่ commit
```

Also remove the old paragraphs about `Per-Stack .env`, `.env.example`, and the `sync_env.py` reference (search for `sync_env`).

- [ ] **Step 2: Update CLAUDE.md "Release & Security Process" section**

In the "🚀 Release & Security Process" section, add a new bullet under "Security Guardrail":

```markdown
4. **Vault Guardrail:** ห้าม commit `secrets/vault.yaml` (plaintext intermediate). ใช้ `make edit-vault` แก้ในที่ — sops จัดการ encrypt/decrypt ให้. `secrets/vault.sops.yaml` commit ได้เพราะ encrypted แล้ว
```

- [ ] **Step 3: Update README.md quick-start**

In `README.md`, locate the setup / quick-start section. Replace the env-setup steps (something like "Copy .env.example to .env") with:

```markdown
## Setup

1. Install tools:
   ```bash
   brew install sops age
   ```

2. Import your age private key (one-time per machine):
   ```bash
   mkdir -p ~/.config/sops/age
   # Either generate a new key and ask the vault maintainer to add it:
   age-keygen -o ~/.config/sops/age/keys.txt
   # …or paste an existing key (e.g., from your password manager):
   $EDITOR ~/.config/sops/age/keys.txt
   chmod 600 ~/.config/sops/age/keys.txt
   ```

3. Generate `.env` files and deploy:
   ```bash
   make secrets       # decrypts vault, writes <stack>/.env and .env.deploy
   ./scripts/deploy.sh
   ```

To edit a secret: `make edit-vault` (opens the vault in $EDITOR with transparent decrypt/re-encrypt).
```

Remove any leftover references to root `.env`, `.env.example`, or `sync_env.py`.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: replace per-stack .env setup with sops vault + manifest workflow"
```

---

## Task 22: Production smoke test (uptime-kuma)

**Files:** none modified

uptime-kuma has the smallest manifest (single literal, no real secrets), so it's the safest target for the first real deploy.

- [ ] **Step 1: Render fresh `.env` files just before deploy**

Run:
```bash
make secrets
```

- [ ] **Step 2: Deploy uptime-kuma only**

Run:
```bash
./scripts/deploy.sh -s uptime-kuma -y
```
Expected: tar transfers, ssh executes `docker compose up -d --build` against `/volume2/docker/uptime-kuma`, prints `✔ uptime-kuma restarted`.

- [ ] **Step 3: Verify container health**

Run:
```bash
ssh nas "docker ps --filter name=uptime-kuma --format '{{.Names}} {{.Status}}'"
```
Expected: `uptime-kuma Up …` with a healthy status.

If container fails to start: open `secrets/vault.sops.yaml` with `sops`, double-check `stacks.uptime_kuma.nas_volume_root` (or whatever value the stack consumes). Fix, `make secrets`, redeploy.

- [ ] **Step 4: Do not commit anything (no source changes here).**

---

## Task 23: Full production rollout

**Files:** none modified

- [ ] **Step 1: Render and deploy all stacks**

Run:
```bash
make secrets
./scripts/deploy.sh -s all -y
```
Expected: each stack reports `✔ <stack> restarted`. If any fails, read the compose output, fix the vault or manifest, re-run targeted: `./scripts/deploy.sh -s <stack> -y`.

- [ ] **Step 2: Monitor for 30 minutes**

Run:
```bash
ssh nas "docker ps --format '{{.Names}}\t{{.Status}}'" | sort
```
Expected: every stack listed as `Up …` (healthy). Hit the dashboards (homepage, uptime-kuma, news-feed, hermes-agent) and verify they respond.

- [ ] **Step 3: After 24h of clean run, delete the backup directory**

Run (only after 24h with no incidents):
```bash
rm -rf backup-pre-vault
echo "Migration complete."
```

- [ ] **Step 4: No commits in this task.**

---

## Spec Coverage Self-Check

| Spec section | Implemented by |
|--------------|----------------|
| §1 Goals (5 pain points) | Tasks 4–12 (vault + manifest + generator) + Task 11 (encryption) + Task 1 (portability via sops/age) |
| §2 Architecture | Tasks 4–8, 15 |
| §3 Vault Schema | Task 10, Task 11 |
| §4 Per-stack manifest | Task 3 (schema), Task 12 (manifests) |
| §5 sops + age | Task 1, Task 11, Task 20 |
| §6 Generator (render_env.py) | Tasks 4–8, 14 |
| §7 deploy.sh integration | Task 9 (deploy.manifest.yaml), Task 17 (deploy.sh edits) |
| §8 Makefile | Task 15 |
| §9 Schema validation | Task 3 |
| §10 Testing (unit, schema, equivalence) | Task 2, 3, 4–8, 13, 14 |
| §11 Migration phases | Tasks 10–14, 18, 19 (Phase A); Phase B deferred per spec |
| §12 .gitignore | Task 16 |
| §13 Docs updates | Task 21 |
| §14 Out of scope | n/a |
| §15 Security note (pre-spec incident) | called out separately — rotate leaked NAS_SUDO_PASSWORD + SYNC_NOTION_TOKEN before this plan starts |

## Post-Migration Verification Checklist

After Task 23 succeeds:

- [ ] Every stack listed in `CLAUDE.md` shows `Up` in `docker ps` on the NAS
- [ ] `make check` exits 0
- [ ] `make test` exits 0 (all repo-level tests pass)
- [ ] CI workflow `secrets` runs green on `main`
- [ ] `scripts/sync_env.py` is deleted (`ls scripts/`)
- [ ] No `.env.example` files exist (`find . -name '.env.example' -not -path './.git/*'`)
- [ ] Root `.env` does not exist (`ls .env 2>&1 | grep -q "No such"`)
- [ ] `secrets/vault.sops.yaml` is encrypted (`grep -q sops: secrets/vault.sops.yaml`)
- [ ] `backup-pre-vault/` is deleted after 24h of clean run
