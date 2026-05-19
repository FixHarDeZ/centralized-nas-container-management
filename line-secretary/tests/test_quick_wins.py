import agent


# ── URL in context ────────────────────────────────────────────────

def test_rank_context_preserves_url():
    pages = [
        {"id": "abc-123", "title": "API Token", "content": "groq key here", "url": "https://notion.so/abc123"}
    ]
    result = agent._rank_context({"pages": pages, "databases": []}, ["groq"], 50000)
    assert result["pages"][0].get("url") == "https://notion.so/abc123"


def test_rank_context_preserves_db_url():
    dbs = [
        {"id": "db-1", "title": "Passwords", "rows": [], "url": "https://notion.so/db1"}
    ]
    result = agent._rank_context({"pages": [], "databases": dbs}, ["pass"], 50000)
    assert result["databases"][0].get("url") == "https://notion.so/db1"


def test_system_prompt_has_url_instruction():
    assert "🔗" in agent.SYSTEM_PROMPT


# ── /refresh ─────────────────────────────────────────────────────

import pytest
from cache import PageCache


@pytest.mark.asyncio
async def test_force_refresh_calls_rebuild_and_returns_count():
    c = PageCache()
    c._token = "test_token"

    async def mock_rebuild(self=None):
        c._pages = [{"id": "p1"}, {"id": "p2"}, {"id": "p3"}]

    c._rebuild = mock_rebuild
    n = await c.force_refresh()

    assert n == 3


@pytest.mark.asyncio
async def test_force_refresh_replaces_stale_pages():
    c = PageCache()
    c._token = "test_token"
    c._pages = [{"id": "old"}]

    async def mock_rebuild(self=None):
        c._pages = [{"id": "new1"}, {"id": "new2"}]

    c._rebuild = mock_rebuild
    n = await c.force_refresh()

    assert n == 2
    assert c._pages[0]["id"] == "new1"
