"""Notifier — broadcast a text message to LINE and/or Telegram.

SINGLE SOURCE OF TRUTH: shared/notify.py. This file is vendored into each stack
directory by `make sync-shared`; the copies are committed and guarded by a
hash-equality test (tests/test_shared_sync.py). DO NOT edit the vendored copies —
edit this file and re-run `make sync-shared`.

Why a hand-vendored single file instead of a package: each stack builds its own
Docker image with `build: .`, so the build context is the stack directory and a
Dockerfile cannot COPY a file living above it. stdlib `urllib` only, so the
module works whether a stack pins `requests` (game-codes) or `httpx` (the rest).

The Notifier never raises: a notification failure must not crash a poller. Each
channel's error is caught and logged; the channel is omitted from the returned
list of successes. Message *formatting* is intentionally NOT here — it stays
local to each stack.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_LINE_URL = "https://api.line.me/v2/bot/message/push"
_TG_URL = "https://api.telegram.org/bot{token}/sendMessage"


@dataclass
class LineCreds:
    token: str
    to: str  # user id OR group id — both use the /push endpoint identically


@dataclass
class TgCreds:
    token: str
    chat: str
    parse_mode: str | None = None      # "HTML" for stacks that send HTML markup
    disable_preview: bool = False      # game-codes suppresses link previews


def _urllib_post(url: str, payload: dict, headers: dict, timeout: float) -> int:
    """Default transport. POST JSON, return HTTP status. Injected for tests."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code  # 4xx/5xx — let the caller log it as a non-200


class Notifier:
    """Broadcast text to every configured channel. Construct once per stack."""

    def __init__(
        self,
        line: LineCreds | None = None,
        telegram: TgCreds | None = None,
        post=None,
        timeout: float = 15.0,
    ):
        self._line = line
        self._telegram = telegram
        # call-time lookup of the module default so tests can monkeypatch
        # `<module>._urllib_post`; pass `post=` to inject a fake directly.
        self._post = post if post is not None else _urllib_post
        self._timeout = timeout

    def send(self, text: str) -> list[str]:
        """Send to all configured+credentialed channels. Returns those that succeeded."""
        sent: list[str] = []
        if self._line and self._line.token and self._line.to and self._send_line(text):
            sent.append("line")
        if self._telegram and self._telegram.token and self._telegram.chat and self._send_telegram(text):
            sent.append("telegram")
        return sent

    def _send_line(self, text: str) -> bool:
        c = self._line
        try:
            status = self._post(
                _LINE_URL,
                {"to": c.to, "messages": [{"type": "text", "text": text}]},
                {"Authorization": f"Bearer {c.token}"},
                self._timeout,
            )
            if status != 200:
                logger.error("LINE send failed: HTTP %s", status)
                return False
            return True
        except Exception as exc:  # noqa: BLE001 — never propagate
            logger.error("LINE send error: %s", exc)
            return False

    def _send_telegram(self, text: str) -> bool:
        c = self._telegram
        payload: dict = {"chat_id": c.chat, "text": text}
        if c.parse_mode:
            payload["parse_mode"] = c.parse_mode
        if c.disable_preview:
            payload["disable_web_page_preview"] = True
        try:
            status = self._post(_TG_URL.format(token=c.token), payload, {}, self._timeout)
            if status != 200:
                logger.error("Telegram send failed: HTTP %s", status)
                return False
            return True
        except Exception as exc:  # noqa: BLE001 — never propagate
            logger.error("Telegram send error: %s", exc)
            return False
