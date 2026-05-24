import agent
from unittest.mock import AsyncMock, patch
import pytest
import main


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


# ── _push_long ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_push_long_short_text_single_call():
    mock_push = AsyncMock()
    await main._push_long("สั้นๆ", mock_push)
    mock_push.assert_called_once_with("สั้นๆ")


@pytest.mark.asyncio
async def test_push_long_exactly_at_limit_single_call():
    mock_push = AsyncMock()
    text = "x" * 4000
    await main._push_long(text, mock_push, max_len=4000)
    mock_push.assert_called_once()
    assert len(mock_push.call_args[0][0]) == 4000


@pytest.mark.asyncio
async def test_push_long_over_limit_splits():
    mock_push = AsyncMock()
    text = "x" * 8001
    await main._push_long(text, mock_push, max_len=4000)
    assert mock_push.call_count == 3
    assert len(mock_push.call_args_list[0][0][0]) == 4000
    assert len(mock_push.call_args_list[1][0][0]) == 4000
    assert len(mock_push.call_args_list[2][0][0]) == 1


@pytest.mark.asyncio
async def test_push_long_empty_string():
    mock_push = AsyncMock()
    await main._push_long("", mock_push)
    mock_push.assert_called_once_with("")
