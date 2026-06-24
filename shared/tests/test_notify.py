"""Tests for the Notifier deep module — the interface is the test surface.

A fake `post` is injected at the internal transport seam so no network is hit.
This single suite replaces the per-copy transport tests across stacks.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from notify import LineCreds, Notifier, TgCreds


class RecordingPost:
    """Fake transport. Records every call; returns a configurable status."""

    def __init__(self, status=200):
        self.status = status
        self.calls = []

    def __call__(self, url, payload, headers, timeout):
        self.calls.append({"url": url, "payload": payload, "headers": headers})
        if callable(self.status):
            return self.status(url)
        return self.status


def test_send_to_both_channels():
    post = RecordingPost()
    n = Notifier(
        line=LineCreds("ltok", "Uabc"),
        telegram=TgCreds("btok", "123", parse_mode="HTML"),
        post=post,
    )
    assert n.send("hello") == ["line", "telegram"]
    assert len(post.calls) == 2
    line_call, tg_call = post.calls
    assert "api.line.me" in line_call["url"]
    assert line_call["headers"]["Authorization"] == "Bearer ltok"
    assert line_call["payload"]["to"] == "Uabc"
    assert line_call["payload"]["messages"][0]["text"] == "hello"
    assert "btok" in tg_call["url"]
    assert tg_call["payload"]["chat_id"] == "123"
    assert tg_call["payload"]["parse_mode"] == "HTML"


def test_telegram_only():
    post = RecordingPost()
    n = Notifier(telegram=TgCreds("btok", "123"), post=post)
    assert n.send("hi") == ["telegram"]
    assert len(post.calls) == 1
    assert "parse_mode" not in post.calls[0]["payload"]  # plain text by default
    assert "disable_web_page_preview" not in post.calls[0]["payload"]


def test_disable_preview_flag():
    post = RecordingPost()
    n = Notifier(telegram=TgCreds("btok", "123", disable_preview=True), post=post)
    n.send("hi")
    assert post.calls[0]["payload"]["disable_web_page_preview"] is True


def test_missing_credentials_skip_channel():
    post = RecordingPost()
    n = Notifier(line=LineCreds("", ""), telegram=TgCreds("btok", "123"), post=post)
    assert n.send("x") == ["telegram"]  # LINE skipped, no creds


def test_no_channels_returns_empty():
    post = RecordingPost()
    assert Notifier(post=post).send("x") == []
    assert post.calls == []


def test_non_200_excluded_from_result():
    post = RecordingPost(status=lambda url: 200 if "line" in url else 500)
    n = Notifier(line=LineCreds("l", "U"), telegram=TgCreds("b", "c"), post=post)
    assert n.send("x") == ["line"]  # telegram 500 dropped


def test_transport_exception_never_propagates():
    def boom(*a):
        raise RuntimeError("network down")

    n = Notifier(line=LineCreds("l", "U"), telegram=TgCreds("b", "c"), post=boom)
    assert n.send("x") == []  # both fail, nothing raised


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
