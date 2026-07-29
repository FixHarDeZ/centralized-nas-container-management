import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import config
import db
import httpx
from notify import Notifier, TgCreds

_TZ = ZoneInfo(config.TZ)

# Shared transport (plain text). send_test_message/get_updates keep their own
# httpx calls so they can return detailed diagnostics to the dashboard.
_N = Notifier(
    telegram=TgCreds(config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID),
    timeout=10,
)


def _now() -> str:
    return datetime.now(_TZ).strftime("%H:%M")


def _url(method: str) -> str:
    return f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/{method}"


async def _send(text: str):
    # Notifier is sync (stdlib urllib); run off the event loop.
    await asyncio.to_thread(_N.send, text)


def _item(t: dict) -> str:
    line = f"🎬 {t['title']}\n   🌱{t['seeds']}  📥{t['leeches']}"
    badges = db.badge_text(t)
    return f"{line}\n   {badges}" if badges else line


async def notify_keyword_matches(source_url: str, matches: list[dict]):
    """Push when new keyword-matched torrents are found."""
    if not matches:
        return
    from urllib.parse import urlparse

    label = urlparse(source_url).path.split("/")[-1] or source_url

    lines = [f"🎯 keyword match ใหม่! — {label}\n"]
    for t in matches[:10]:
        lines.append(_item(t))
    if len(matches) > 10:
        lines.append(f"...และอีก {len(matches) - 10} รายการ")
    lines.append(f"\n🕒 {_now()}")
    await _send("\n".join(lines))


async def notify_sticky_new(source_url: str, entries: list[dict]):
    """Push when new sticky/pinned torrents are first discovered."""
    if not entries:
        return
    from urllib.parse import urlparse

    label = urlparse(source_url).path.split("/")[-1] or source_url

    lines = [f"📌 Sticky ใหม่! — {label}\n"]
    for t in entries[:10]:
        lines.append(_item(t))
    if len(entries) > 10:
        lines.append(f"...และอีก {len(entries) - 10} รายการ")
    lines.append(f"\n🕒 {_now()}")
    await _send("\n".join(lines))


async def notify_all_free(count: int):
    """Push when every torrent posted today is 100% free-leech (sitewide free event)."""
    await _send(
        f"🎉 วันนี้ทุก torrent ฟรี 100%! ({count} รายการ)\nโหลดได้ไม่เสีย ratio 🟢\n\n🕒 {_now()}",
    )


async def notify_hr(body: str):
    """Push the Hit & Run risk digest (body built by hr.format_message)."""
    await _send(f"{body}\n\n🕒 {_now()}")


async def send_test_message() -> dict:
    """Send a test push and return {"ok": bool, "error": str}."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return {
            "ok": False,
            "error": "ยังไม่ได้ตั้งค่า TORRENTWATCH_TELEGRAM_BOT_TOKEN / TORRENTWATCH_TELEGRAM_CHAT_ID ใน .env",
        }
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            resp = await c.post(
                _url("sendMessage"),
                json={
                    "chat_id": config.TELEGRAM_CHAT_ID,
                    "text": f"🧪 TorrentWatch — ทดสอบการแจ้งเตือน Telegram\nหากเห็นข้อความนี้ แสดงว่าตั้งค่าถูกต้องแล้ว ✓\n🕒 {_now()}",
                },
            )
        if resp.status_code == 200:
            return {"ok": True}
        return {
            "ok": False,
            "error": f"Telegram API {resp.status_code}: {resp.text[:120]}",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def get_updates() -> dict:
    """Call getUpdates to help user discover their chat_id."""
    if not config.TELEGRAM_BOT_TOKEN:
        return {
            "ok": False,
            "error": "TORRENTWATCH_TELEGRAM_BOT_TOKEN ยังไม่ได้ตั้งค่าใน .env",
        }
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            resp = await c.get(_url("getUpdates"))
        data = resp.json()
        chats: list[dict] = []
        seen: set[int] = set()
        for update in data.get("result", []):
            msg = (
                update.get("message")
                or update.get("channel_post")
                or update.get("my_chat_member", {}).get("chat")
                or {}
            )
            chat = msg.get("chat") or msg
            chat_id = chat.get("id")
            if chat_id and chat_id not in seen:
                seen.add(chat_id)
                chats.append(
                    {
                        "chat_id": chat_id,
                        "type": chat.get("type", ""),
                        "name": chat.get("title") or chat.get("first_name", ""),
                    },
                )
        return {"ok": True, "chats": chats, "raw_count": len(data.get("result", []))}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── Interactive (inline buttons + long-poll) ─────────────────────────────────
# Used by hr_fix for the auto-fix confirm flow. Kept on httpx (async) rather than
# the stdlib Notifier because these need the JSON response back.

POLLER_ACTIVE = False  # getUpdates is single-consumer; see main.api_telegram_updates


async def send_buttons(text: str, buttons: list[list[dict]]) -> int | None:
    """Send a message with an InlineKeyboard. Returns message_id (None on failure)."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return None
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            resp = await c.post(
                _url("sendMessage"),
                json={
                    "chat_id": config.TELEGRAM_CHAT_ID,
                    "text": f"{text}\n\n🕒 {_now()}",
                    "reply_markup": {"inline_keyboard": buttons},
                },
            )
        return (resp.json().get("result") or {}).get("message_id")
    except Exception as e:
        print(f"[telegram] send_buttons error: {e}")
        return None


async def answer_callback(callback_id: str, text: str = ""):
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(
                _url("answerCallbackQuery"),
                json={"callback_query_id": callback_id, "text": text[:180]},
            )
    except Exception as e:
        print(f"[telegram] answer_callback error: {e}")


async def edit_message(message_id: int, text: str):
    """Rewrite a prompt after it is answered — also drops its buttons."""
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(
                _url("editMessageText"),
                json={
                    "chat_id": config.TELEGRAM_CHAT_ID,
                    "message_id": message_id,
                    "text": f"{text}\n\n🕒 {_now()}",
                },
            )
    except Exception as e:
        print(f"[telegram] edit_message error: {e}")


async def poll_callbacks(offset: int, timeout: int = 45) -> list[dict]:
    """Long-poll getUpdates for callback_query only. Raises on transport errors."""
    async with httpx.AsyncClient(timeout=timeout + 15) as c:
        resp = await c.get(
            _url("getUpdates"),
            params={
                "offset": offset,
                "timeout": timeout,
                "allowed_updates": '["callback_query"]',
            },
        )
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"getUpdates: {str(data)[:150]}")
    return data.get("result", [])
