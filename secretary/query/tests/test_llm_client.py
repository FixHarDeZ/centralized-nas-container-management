import importlib
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _reload(monkeypatch, provider: str):
    """Reload llm_client with the given LLM_PROVIDER env var."""
    monkeypatch.setenv("LLM_PROVIDER", provider)
    import llm_client as m
    importlib.reload(m)
    m._anthropic_client = None
    m._openrouter_client = None
    return m


@pytest.mark.asyncio
async def test_anthropic_returns_text(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-test")
    m = _reload(monkeypatch, "anthropic")

    fake_content = MagicMock()
    fake_content.text = "hello from anthropic"
    fake_msg = MagicMock()
    fake_msg.content = [fake_content]
    fake_client = MagicMock()
    fake_client.messages.create = AsyncMock(return_value=fake_msg)

    with patch.object(m, "_anthropic_client", fake_client):
        result = await m.get_llm_response("system", "user")

    assert result == "hello from anthropic"
    fake_client.messages.create.assert_awaited_once()
    call_kwargs = fake_client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == "claude-test"
    assert call_kwargs["system"] == "system"
    assert call_kwargs["messages"] == [{"role": "user", "content": "user"}]


@pytest.mark.asyncio
async def test_openrouter_returns_text(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("OPENROUTER_MODEL", "anthropic/claude-test")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    m = _reload(monkeypatch, "openrouter")

    fake_choice = MagicMock()
    fake_choice.message.content = "hello from openrouter"
    fake_resp = MagicMock()
    fake_resp.choices = [fake_choice]
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(return_value=fake_resp)

    with patch.object(m, "_openrouter_client", fake_client):
        result = await m.get_llm_response("system", "user")

    assert result == "hello from openrouter"
    fake_client.chat.completions.create.assert_awaited_once()
    call_kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "anthropic/claude-test"
    assert call_kwargs["messages"][0] == {"role": "system", "content": "system"}
    assert call_kwargs["messages"][1] == {"role": "user", "content": "user"}


@pytest.mark.asyncio
async def test_unknown_provider_raises(monkeypatch):
    m = _reload(monkeypatch, "unknown-xyz")
    with pytest.raises(ValueError, match="unknown-xyz"):
        await m.get_llm_response("system", "user")
