"""Telegram transport for a single-chat bot: long-poll in, messages out.

SINGLE SOURCE OF TRUTH: shared/telegram.py. Vendored into each stack's `app/`
by `make sync-shared`; copies are committed and guarded by a hash-equality
test (tests/test_shared_sync.py). DO NOT edit vendored copies.

Nothing about what a message *says* lives here. What does live here is every
transport rule that has cost an outage:

  * `sendMessage` over 4096 characters is answered with 400 and delivers
    NOTHING — not a truncated message, no message. shorts-factory's /help grew
    past the limit and the bot went silent for days (2026-09-08). `say()`
    splits on paragraph breaks;
  * buttons and the returned message_id belong to the LAST piece only. A
    keyboard under a middle piece has text posted beneath it, and the caller
    keeps one id to edit later;
  * `parse_mode` goes on EVERY piece, or piece one shows `<pre>` literally and
    piece two carries an unbalanced tag into another 400;
  * `editMessageText` fires no notification, so anything the human must see
    goes out as a fresh message after the edit (torrentwatch's rule);
  * the chat id filter is the whole trust boundary of a bot with no HTTP
    surface. `mine()` is it; every update goes through it before `handle`.

Credentials are read when `Bot.from_env()` is called, never at import: a
module that reads `os.environ[...]` at the top cannot be imported by a test or
by a container that is missing the token, and dies with a KeyError before it
can say why.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# httpx logs every request URL at INFO, and a Telegram URL *is* the bot token:
# `POST https://api.telegram.org/bot<TOKEN>/sendMessage`. A bot that turns on
# INFO logging (both factories do) would print its own credential into
# `docker logs` on every message. Seen on the NAS 2026-09-15. Muted here, at
# import, because every process that imports this module talks to Telegram.
logging.getLogger("httpx").setLevel(logging.WARNING)

TEXT_LIMIT = 4096
CAPTION_LIMIT = 1024


def chunks(text: str, limit: int = TEXT_LIMIT) -> list[str]:
    """`text` cut into pieces Telegram will accept, on blank lines by choice.

    Paragraph breaks first, then single lines: a help page split mid-sentence
    reads as a bug. A single line longer than the limit is cut where it falls,
    which nothing here produces.
    """
    parts: list[str] = []
    buffer = ""
    for block in text.split("\n\n"):
        joined = f"{buffer}\n\n{block}" if buffer else block
        if len(joined) <= limit:
            buffer = joined
            continue
        if buffer:
            parts.append(buffer)
        buffer = ""
        for line in block.split("\n"):
            joined = f"{buffer}\n{line}" if buffer else line
            if len(joined) <= limit:
                buffer = joined
                continue
            if buffer:
                parts.append(buffer)
            buffer = line[:limit]
    if buffer:
        parts.append(buffer)
    return parts or [text[:limit]]


def chat_of(update: dict) -> int | None:
    """The chat an update came from, for messages and callback taps alike."""
    message = update.get("message") or (update.get("callback_query") or {}).get("message") or {}
    return (message.get("chat") or {}).get("id")


class Bot:
    def __init__(self, client: httpx.AsyncClient, token: str, chat_id: int):
        self.client = client
        self.chat_id = chat_id
        self._base = f"https://api.telegram.org/bot{token}"

    @classmethod
    def from_env(cls, client: httpx.AsyncClient) -> "Bot":
        return cls(client, os.environ["TELEGRAM_BOT_TOKEN"], int(os.environ["TELEGRAM_CHAT_ID"]))

    # --- raw ------------------------------------------------------------------

    async def api(self, method: str, **payload):
        reply = await self.client.post(f"{self._base}/{method}", json=payload, timeout=60)
        body = reply.json()
        if not body.get("ok"):
            logger.error("telegram %s: %s", method, body.get("description"))
        return body.get("result")

    async def updates(self, offset: int, timeout: int = 30) -> list[dict]:
        reply = await self.client.get(
            f"{self._base}/getUpdates",
            params={"offset": offset, "timeout": timeout},
            timeout=timeout + 30,
        )
        return reply.json().get("result", []) or []

    def mine(self, update: dict) -> bool:
        return chat_of(update) == self.chat_id

    # --- out ------------------------------------------------------------------

    async def say(self, text: str, **extra):
        """Send `text` in as many pieces as it takes. Returns the last piece's
        message, which is the one the keyboard is on."""
        markup = {key: extra.pop(key) for key in ("reply_markup",) if key in extra}
        result = None
        pieces = chunks(text)
        for index, piece in enumerate(pieces):
            tail = index == len(pieces) - 1
            result = await self.api(
                "sendMessage", chat_id=self.chat_id, text=piece,
                **extra, **(markup if tail else {}),
            )
        return result

    async def edit(self, message_id: int | None, text: str, **extra) -> None:
        """Retire a message's buttons in place. Silent — follow with `say()`
        for anything the human must notice."""
        if message_id and text:
            await self.api("editMessageText", chat_id=self.chat_id,
                           message_id=message_id, text=text, **extra)

    async def answer(self, callback: dict) -> None:
        await self.api("answerCallbackQuery", callback_query_id=callback["id"])

    async def _upload(self, method: str, field: str, path: Path, mime: str,
                      caption: str, timeout: float, **extra) -> dict | None:
        with path.open("rb") as handle:
            data = {"chat_id": self.chat_id, "caption": caption[:CAPTION_LIMIT]}
            data.update({k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
                         for k, v in extra.items()})
            reply = await self.client.post(
                f"{self._base}/{method}",
                data=data,
                files={field: (path.name, handle, mime)},
                timeout=timeout,
            )
        body = reply.json()
        if not body.get("ok"):
            logger.error("%s: %s", method, reply.text[:400])
            return None
        return body.get("result")

    async def send_document(self, path: Path, caption: str = "", **extra) -> dict | None:
        return await self._upload("sendDocument", "document", path,
                                  "application/octet-stream", caption, 120, **extra)

    async def send_video(self, path: Path, caption: str = "", **extra) -> dict | None:
        # 50 MB ceiling for bots; the caller decides what to do about a file
        # that is bigger, this only reports the refusal.
        return await self._upload("sendVideo", "video", path, "video/mp4",
                                  caption, 600, supports_streaming="true", **extra)
