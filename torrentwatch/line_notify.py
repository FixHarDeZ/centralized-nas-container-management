import asyncio
import httpx
from datetime import datetime
from zoneinfo import ZoneInfo
import config
from notify import LineCreds, Notifier

_TZ  = ZoneInfo(config.TZ)
_URL = "https://api.line.me/v2/bot/message/push"

# Shared transport; send_test_message/get_updates keep their own httpx calls so
# they can return detailed diagnostics to the dashboard.
_N = Notifier(line=LineCreds(config.LINE_ACCESS_TOKEN, config.LINE_USER_ID), timeout=10)


def _now() -> str:
    return datetime.now(_TZ).strftime("%H:%M")


def _headers() -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.LINE_ACCESS_TOKEN}",
    }


async def _push(text: str):
    # Notifier is sync (stdlib urllib); run off the event loop.
    await asyncio.to_thread(_N.send, text)


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
    await _push("\n".join(lines))


async def notify_sticky_new(source_url: str, entries: list[dict]):
    """Push when new sticky/pinned torrents are first discovered."""
    if not entries:
        return
    from urllib.parse import urlparse
    label = urlparse(source_url).path.split("/")[-1] or source_url

    lines = [f"📌 Sticky ใหม่! — {label}\n"]
    for t in entries[:10]:
        lines.append(f"🎬 {t['title']}\n   🌱{t['seeds']}  📥{t['leeches']}")
    if len(entries) > 10:
        lines.append(f"...และอีก {len(entries) - 10} รายการ")
    lines.append(f"\n🕒 {_now()}")
    await _push("\n".join(lines))


async def notify_round_summary(results: list[dict]):
    """Push round summary after each scrape cycle."""
    lines = [f"📡 TorrentWatch — รอบ {_now()}\n"]
    for r in results:
        from urllib.parse import urlparse
        label = urlparse(r["source_url"]).path.split("/")[-1] or r["source_url"]
        kw_part = f", keyword {r['keyword_count']} รายการ" if r["keyword_count"] else ""
        lines.append(f"• {label}: {r['total_count']} รายการ{kw_part}")
    await _push("\n".join(lines))


async def notify_all_free(count: int):
    """Push when every torrent posted today is 100% free-leech (sitewide free event)."""
    await _push(f"🎉 วันนี้ทุก torrent ฟรี 100%! ({count} รายการ)\nโหลดได้ไม่เสีย ratio 🟢\n\n🕒 {_now()}")


async def send_test_message() -> dict:
    """Send a test push and return {"ok": bool, "error": str}. Checks response directly."""
    if not config.LINE_ACCESS_TOKEN or not config.LINE_USER_ID:
        return {"ok": False, "error": "ยังไม่ได้ตั้งค่า TORRENTWATCH_LINE_ACCESS_TOKEN / TORRENTWATCH_LINE_USER_ID ใน .env"}
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            resp = await c.post(
                _URL,
                headers=_headers(),
                json={"to": config.LINE_USER_ID, "messages": [{"type": "text", "text": f"🧪 TorrentWatch — ทดสอบการแจ้งเตือน LINE\nหากเห็นข้อความนี้ แสดงว่าตั้งค่าถูกต้องแล้ว ✓\n🕒 {_now()}"}]},
            )
        if resp.status_code == 200:
            return {"ok": True}
        return {"ok": False, "error": f"LINE API {resp.status_code}: {resp.text[:120]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
