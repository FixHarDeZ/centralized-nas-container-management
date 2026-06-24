from unittest.mock import MagicMock, patch

import pytest
from app.summarizer import summarize


@patch("app.summarizer.anthropic.Anthropic")
def test_summarize_anthropic(mock_cls, base_config):
    mock_client = MagicMock()
    mock_cls.return_value = mock_client
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="สรุปทดสอบ")],
    )
    result = summarize("Title", "Body text", base_config)
    assert result == "สรุปทดสอบ"
    mock_client.messages.create.assert_called_once()


@patch("app.summarizer.http_post")
def test_summarize_openrouter(mock_post, base_config):
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"choices": [{"message": {"content": "สรุป OR"}}]}
    mock_post.return_value = mock_resp

    config = {
        **base_config,
        "summarizer_provider": "openrouter",
        "summarizer_model": "deepseek/deepseek-chat",
    }
    result = summarize("Title", "Body text", config)
    assert result == "สรุป OR"
    assert mock_post.call_args[0][0] == "https://openrouter.ai/api/v1/chat/completions"


@patch("app.summarizer.time.sleep")
@patch("app.summarizer.anthropic.Anthropic")
def test_summarize_retries_on_failure(mock_cls, mock_sleep, base_config):
    mock_client = MagicMock()
    mock_cls.return_value = mock_client
    mock_client.messages.create.side_effect = [
        Exception("rate limit"),
        MagicMock(content=[MagicMock(text="สรุปหลัง retry")]),
    ]
    result = summarize("Title", "Body", base_config)
    assert result == "สรุปหลัง retry"
    assert mock_client.messages.create.call_count == 2


@patch("app.summarizer.http_post")
@patch("app.summarizer.time.sleep")
@patch("app.summarizer.anthropic.Anthropic")
def test_summarize_fallback_on_primary_failure(
    mock_cls,
    mock_sleep,
    mock_post,
    base_config,
):
    """Primary (anthropic) fails all retries → fallback (openrouter) succeeds."""
    mock_client = MagicMock()
    mock_cls.return_value = mock_client
    mock_client.messages.create.side_effect = Exception("API key invalid")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "สรุปจาก fallback"}}],
    }
    mock_post.return_value = mock_resp

    config = {
        **base_config,
        "summarizer_fallback": [
            {"provider": "openrouter", "model": "deepseek/deepseek-chat"},
        ],
    }
    result = summarize("Title", "Body", config)
    assert result == "สรุปจาก fallback"
    assert mock_post.called


@patch("app.summarizer.time.sleep")
@patch("app.summarizer.anthropic.Anthropic")
def test_summarize_raises_when_all_fail(mock_cls, mock_sleep, base_config):
    """All providers fail → raises last exception."""
    mock_client = MagicMock()
    mock_cls.return_value = mock_client
    mock_client.messages.create.side_effect = Exception("all broken")

    config = {
        **base_config,
        "summarizer_fallback": [
            {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
        ],
    }
    with pytest.raises(Exception, match="all broken"):
        summarize("Title", "Body", config)


def test_summarize_no_fallback_raises_on_failure(base_config):
    """No fallback configured → original behavior: raises on primary failure."""
    with (
        patch("app.summarizer.anthropic.Anthropic") as mock_cls,
        patch("app.summarizer.time.sleep"),
    ):
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.side_effect = Exception("boom")
        with pytest.raises(Exception, match="boom"):
            summarize("Title", "Body", base_config)
