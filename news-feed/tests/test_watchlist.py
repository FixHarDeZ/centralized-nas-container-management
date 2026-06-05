import pytest
from app.models import get_watchlist, set_watchlist, toggle_watchlist

_NOW = "2026-06-05T00:00:00Z"


# ── model layer ──────────────────────────────────────────────────────────────

def test_get_watchlist_empty(db):
    assert get_watchlist(db) == []


def test_toggle_watchlist_add(db):
    result = toggle_watchlist(db, "openai/gpt-4o", _NOW)
    assert result is True
    assert get_watchlist(db) == ["openai/gpt-4o"]


def test_toggle_watchlist_remove(db):
    toggle_watchlist(db, "openai/gpt-4o", _NOW)
    result = toggle_watchlist(db, "openai/gpt-4o", _NOW)
    assert result is False
    assert get_watchlist(db) == []


def test_set_watchlist_replaces(db):
    toggle_watchlist(db, "openai/gpt-4o", _NOW)
    set_watchlist(db, ["anthropic/claude-3", "google/gemini-pro"], _NOW)
    ids = get_watchlist(db)
    assert "anthropic/claude-3" in ids
    assert "google/gemini-pro" in ids
    assert "openai/gpt-4o" not in ids


def test_set_watchlist_empty(db):
    toggle_watchlist(db, "openai/gpt-4o", _NOW)
    set_watchlist(db, [], _NOW)
    assert get_watchlist(db) == []


# ── API layer ────────────────────────────────────────────────────────────────

def test_api_get_watchlist_empty(client):
    r = client.get("/api/watchlist")
    assert r.status_code == 200
    assert r.json()["model_ids"] == []


def test_api_post_watchlist(client):
    r = client.post("/api/watchlist", json={"model_ids": ["openai/gpt-4o", "anthropic/claude-3"]})
    assert r.status_code == 200
    assert set(r.json()["model_ids"]) == {"openai/gpt-4o", "anthropic/claude-3"}


def test_api_post_watchlist_replaces(client):
    client.post("/api/watchlist", json={"model_ids": ["openai/gpt-4o"]})
    r = client.post("/api/watchlist", json={"model_ids": ["anthropic/claude-3"]})
    assert r.json()["model_ids"] == ["anthropic/claude-3"]


def test_api_patch_toggle_add(client):
    r = client.patch("/api/watchlist/openai%2Fgpt-4o")
    assert r.status_code == 200
    assert r.json()["in_watchlist"] is True
    assert r.json()["model_id"] == "openai/gpt-4o"


def test_api_patch_toggle_remove(client):
    client.patch("/api/watchlist/openai%2Fgpt-4o")
    r = client.patch("/api/watchlist/openai%2Fgpt-4o")
    assert r.json()["in_watchlist"] is False


def test_api_get_reflects_toggle(client):
    client.patch("/api/watchlist/openai%2Fgpt-4o")
    r = client.get("/api/watchlist")
    assert "openai/gpt-4o" in r.json()["model_ids"]
