from unittest.mock import MagicMock, patch
from app.notifier import send_digest, send_summarizer_alert


def _ok_response():
    m = MagicMock()
    m.raise_for_status = MagicMock()
    return m


@patch("app.notifier.httpx.post")
def test_send_digest_sends_to_both_channels(mock_post, monkeypatch, base_config):
    mock_post.return_value = _ok_response()
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("LINE_USER_ID", "Uabc")
    monkeypatch.setenv("NEWS_FEED_TELEGRAM_BOT_TOKEN", "bot:token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    articles = [{"title": "AI News", "summary_th": "สรุปข่าว", "url": "https://x.com/1"}]
    sent = send_digest(articles, base_config)
    assert "line" in sent
    assert "telegram" in sent
    assert mock_post.call_count == 2


def test_send_digest_skips_when_no_credentials(monkeypatch, base_config):
    monkeypatch.delenv("LINE_CHANNEL_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("LINE_USER_ID", raising=False)
    monkeypatch.delenv("NEWS_FEED_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    sent = send_digest([{"title": "X", "summary_th": "Y", "url": "https://x.com"}], base_config)
    assert sent == []


def test_send_digest_empty_articles(base_config):
    sent = send_digest([], base_config)
    assert sent == []


@patch("app.notifier.httpx.post")
def test_send_summarizer_alert_sends_to_both(mock_post, monkeypatch, base_config):
    mock_post.return_value = _ok_response()
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("LINE_USER_ID", "Uabc")
    monkeypatch.setenv("NEWS_FEED_TELEGRAM_BOT_TOKEN", "bot:token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    sent = send_summarizer_alert(base_config)
    assert "line" in sent
    assert "telegram" in sent
    assert mock_post.call_count == 2


def test_send_summarizer_alert_skips_no_credentials(monkeypatch, base_config):
    monkeypatch.delenv("LINE_CHANNEL_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("LINE_USER_ID", raising=False)
    monkeypatch.delenv("NEWS_FEED_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    sent = send_summarizer_alert(base_config)
    assert sent == []
