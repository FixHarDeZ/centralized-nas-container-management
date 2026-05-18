import httpx
from datetime import datetime
from zoneinfo import ZoneInfo
import config

_TZ = ZoneInfo(config.TZ)


def _now() -> str:
    return datetime.now(_TZ).strftime("%H:%M")


def _url(method: str) -> str:
    return f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/{method}"


async def _send(text: str):
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return
    async with httpx.AsyncClient(timeout=10) as c:
        try:
            resp = await c.post(
                _url("sendMessage"),
                json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text},
            )
            if resp.status_code != 200:
                print(f"[Telegram] send failed {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            print(f"[Telegram] send error: {e}")


async def notify_keyword_matches(source_url: str, matches: list[dict]):
    """Push when new keyword-matched torrents are found."""
    if not matches:
        return
    from urllib.parse import urlparse
    label = urlparse(source_url).path.split("/")[-1] or source_url

    lines = [f"🎯 keyword match ใหม่! — {label}\n"]
    for t in matches[:10]:
        lines.append(f"🎬 {t['title']}\n   🌱{t['seeds']}  📥{t['leeches']}")
    if len(matches) > 10:
        lines.append(f"...และอีก {len(matches) - 10} รายการ")
    lines.append(f"\n🕒 {_now()}")
    await _send("\n".join(lines))


async def send_test_message() -> dict:
    """Send a test push and return {"ok": bool, "error": str}."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return {"ok": False, "error": "ยังไม่ได้ตั้งค่า TORRENTWATCH_TELEGRAM_BOT_TOKEN / TORRENTWATCH_TELEGRAM_CHAT_ID ใน .env"}
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
        return {"ok": False, "error": f"Telegram API {resp.status_code}: {resp.text[:120]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def get_updates() -> dict:
    """Call getUpdates to help user discover their chat_id."""
    if not config.TELEGRAM_BOT_TOKEN:
        return {"ok": False, "error": "TORRENTWATCH_TELEGRAM_BOT_TOKEN ยังไม่ได้ตั้งค่าใน .env"}
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            resp = await c.get(_url("getUpdates"))
        data = resp.json()
        chats: list[dict] = []
        seen: set[int] = set()
        for update in data.get("result", []):
            msg = (update.get("message")
                   or update.get("channel_post")
                   or update.get("my_chat_member", {}).get("chat")
                   or {})
            chat = msg.get("chat") or msg
            chat_id = chat.get("id")
            if chat_id and chat_id not in seen:
                seen.add(chat_id)
                chats.append({
                    "chat_id": chat_id,
                    "type": chat.get("type", ""),
                    "name": chat.get("title") or chat.get("first_name", ""),
                })
        return {"ok": True, "chats": chats, "raw_count": len(data.get("result", []))}
    except Exception as e:
        return {"ok": False, "error": str(e)}
