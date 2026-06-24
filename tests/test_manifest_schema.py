"""Validate that secrets/manifest.schema.json enforces the spec rules."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent / "secrets" / "manifest.schema.json"
)


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
    assert any(
        "extra" in str(e.message) or "additional" in str(e.message).lower()
        for e in errors
    )


def test_env_value_must_start_with_allowed_prefix(
    validator: Draft202012Validator,
) -> None:
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
