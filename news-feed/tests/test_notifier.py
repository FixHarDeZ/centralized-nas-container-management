"""news-feed digest/alert formatting + dispatch, tested through the Notifier seam.

Transport itself is covered once in shared/tests/test_notify.py. Here we only
verify news-feed wires creds + formatting into the Notifier correctly, by
monkeypatching the vendored transport (app.notify._urllib_post).
"""

from app.notifier import send_digest, send_summarizer_alert


class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, url, payload, headers, timeout):
        self.calls.append({"url": url, "payload": payload})
        return 200


def _set_creds(monkeypatch):
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("LINE_USER_ID", "Uabc")
    monkeypatch.setenv("NEWS_FEED_TELEGRAM_BOT_TOKEN", "bot:token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")


def test_send_digest_sends_to_both_channels(monkeypatch, base_config):
    rec = _Recorder()
    monkeypatch.setattr("app.notify._urllib_post", rec)
    _set_creds(monkeypatch)
    articles = [{"title": "AI News", "summary_th": "สรุปข่าว", "url": "https://x.com/1"}]
    sent = send_digest(articles, base_config)
    assert "line" in sent and "telegram" in sent
    assert len(rec.calls) == 2
    tg = next(c for c in rec.calls if "telegram" in c["url"])
    assert tg["payload"]["parse_mode"] == "HTML"


def test_send_digest_skips_when_no_credentials(monkeypatch, base_config):
    rec = _Recorder()
    monkeypatch.setattr("app.notify._urllib_post", rec)
    for k in (
        "LINE_CHANNEL_ACCESS_TOKEN",
        "LINE_USER_ID",
        "NEWS_FEED_TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
    ):
        monkeypatch.delenv(k, raising=False)
    sent = send_digest(
        [{"title": "X", "summary_th": "Y", "url": "https://x.com"}],
        base_config,
    )
    assert sent == []
    assert rec.calls == []


def test_send_digest_empty_articles(base_config):
    assert send_digest([], base_config) == []


def test_send_summarizer_alert_sends_to_both(monkeypatch, base_config):
    rec = _Recorder()
    monkeypatch.setattr("app.notify._urllib_post", rec)
    _set_creds(monkeypatch)
    sent = send_summarizer_alert(base_config)
    assert "line" in sent and "telegram" in sent
    assert len(rec.calls) == 2
