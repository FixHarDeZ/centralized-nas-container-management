import httpx
from datetime import datetime
from zoneinfo import ZoneInfo
import config

_TZ  = ZoneInfo(config.TZ)
_URL = "https://api.line.me/v2/bot/message/push"


def _now() -> str:
    return datetime.now(_TZ).strftime("%H:%M")


def _headers() -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.LINE_ACCESS_TOKEN}",
    }


async def _push(text: str):
    if not config.LINE_ACCESS_TOKEN or not config.LINE_USER_ID:
        return
    async with httpx.AsyncClient(timeout=10) as c:
        try:
            resp = await c.post(
                _URL,
                headers=_headers(),
                json={"to": config.LINE_USER_ID, "messages": [{"type": "text", "text": text}]},
            )
            if resp.status_code != 200:
                print(f"[LINE] push failed {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            print(f"[LINE] push error: {e}")


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


async def notify_round_summary(results: list[dict]):
    """Push round summary after each scrape cycle."""
    lines = [f"📡 TorrentWatch — รอบ {_now()}\n"]
    for r in results:
        from urllib.parse import urlparse
        label = urlparse(r["source_url"]).path.split("/")[-1] or r["source_url"]
        kw_part = f", keyword {r['keyword_count']} รายการ" if r["keyword_count"] else ""
        lines.append(f"• {label}: {r['total_count']} รายการ{kw_part}")
    await _push("\n".join(lines))
