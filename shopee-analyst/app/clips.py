"""Product clips gaining views on YouTube TH — the source that needs no Shopee API.

The account has no Affiliate Open API access, so market demand is read from
the outside: Thai "ป้ายยา"/review Shorts whose views are climbing right now.
This is a demand + competitor signal, not Shopee sales.

Quota: the OAuth client is shorts-factory's, so this shares its YouTube Data
API project (10,000 units/day, reset at Pacific midnight) with real uploads.
`search.list` costs 100 units, so discovery runs once per Bangkok day and is
capped at `max_keywords`; every slot after that only re-reads view counts
with `videos.list` (1 unit per 50 ids). Momentum = view delta between our own
snapshots, the same idea as the Shopee sales delta.

mimo only names the product and suggests an angle. A name it returns must
appear in that clip's own title/description/tags or it is discarded — hashtag
soup is exactly where a model invents products. No mimo (no key, stall, bad
JSON) = the raw clip list goes out on time.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app import analyst

log = logging.getLogger(__name__)

DEFAULT_TOKEN_URL = "https://oauth2.googleapis.com/token"
DEFAULT_API_URL = "https://www.googleapis.com/youtube/v3"
SEARCH_UNITS = 100
THAI = re.compile(r"[฀-๿]")
LATIN = re.compile(r"[A-Za-z]")
ENV = ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")


def configured() -> bool:
    return all(os.environ.get(n, "").strip() for n in ENV)


def _fetch(
    url: str, data: dict | None = None, token: str | None = None
) -> dict[str, Any]:
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    request = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        # Reason only (quotaExceeded, invalid_grant…): never the URL or token.
        try:
            detail = json.load(exc)
            reason = detail.get("error")
            if isinstance(reason, dict):
                reason = (reason.get("errors") or [{}])[0].get("reason") or reason.get(
                    "message"
                )
        except Exception:
            reason = ""
        raise RuntimeError(f"YouTube API HTTP {exc.code} {reason}".strip()) from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"YouTube API {type(exc).__name__}") from None


class Api:
    def __init__(self):
        self.base = (os.environ.get("YOUTUBE_API_URL") or DEFAULT_API_URL).rstrip("/")
        self.units = 0
        self._token: str | None = None

    def token(self) -> str:
        if self._token is None:
            reply = _fetch(
                os.environ.get("GOOGLE_TOKEN_URL") or DEFAULT_TOKEN_URL,
                {
                    "client_id": analyst.env("YOUTUBE_CLIENT_ID"),
                    "client_secret": analyst.env("YOUTUBE_CLIENT_SECRET"),
                    "refresh_token": analyst.env("YOUTUBE_REFRESH_TOKEN"),
                    "grant_type": "refresh_token",
                },
            )
            self._token = reply["access_token"]
        return self._token

    def get(self, path: str, params: dict[str, Any], units: int) -> dict[str, Any]:
        self.units += units
        return _fetch(
            f"{self.base}/{path}?{urllib.parse.urlencode(params)}", token=self.token()
        )

    def search(self, query: str, since: datetime, limit: int) -> dict[str, str]:
        """{video_id: publishedAt} for recent short Thai clips, most viewed first."""
        reply = self.get(
            "search",
            {
                "part": "snippet",
                "q": query,
                "type": "video",
                "order": "viewCount",
                "publishedAfter": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "regionCode": "TH",
                "relevanceLanguage": "th",
                "videoDuration": "short",
                "maxResults": min(int(limit), 50),
            },
            SEARCH_UNITS,
        )
        return {
            item["id"]["videoId"]: item["snippet"]["publishedAt"]
            for item in reply.get("items", [])
            if item.get("id", {}).get("videoId")
        }

    def videos(self, ids: list[str]) -> list[dict[str, Any]]:
        out = []
        for start in range(0, len(ids), 50):
            chunk = ids[start : start + 50]
            reply = self.get(
                "videos", {"part": "snippet,statistics", "id": ",".join(chunk)}, 1
            )
            out += reply.get("items", [])
        return out


def thai_ratio(text: str) -> float:
    thai, latin = len(THAI.findall(text)), len(LATIN.findall(text))
    return thai / (thai + latin) if thai + latin else 0.0


def parse_time(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def to_clip(item: dict[str, Any]) -> dict[str, Any]:
    snippet = item.get("snippet", {})
    return {
        "item_id": item["id"],
        "title": snippet.get("title", ""),
        "description": snippet.get("description", ""),
        "tags": snippet.get("tags", []) or [],
        "channel": snippet.get("channelTitle", ""),
        "published": snippet.get("publishedAt", ""),
        "views": int(analyst.to_float(item.get("statistics", {}).get("viewCount"))),
    }


def haystack(clip: dict[str, Any]) -> str:
    return " ".join([clip["title"], clip["description"][:500], " ".join(clip["tags"])])


def discover(
    api: Api, pool: dict[str, Any], now: datetime, cfg: dict[str, Any]
) -> dict[str, Any]:
    """Search once per Bangkok day; keep ids published within `track_days`."""
    today = now.astimezone(analyst.BANGKOK).date().isoformat()
    ids = dict(pool.get("ids", {}))
    if pool.get("day") != today:
        since = now - timedelta(days=int(cfg["lookback_days"]))
        for keyword in cfg["keywords"][: int(cfg["max_keywords"])]:
            ids.update(api.search(keyword, since, int(cfg["per_keyword"])))
    cutoff = now - timedelta(days=int(cfg["track_days"]))
    kept = {k: v for k, v in ids.items() if parse_time(v) >= cutoff}
    newest = sorted(kept.items(), key=lambda kv: kv[1], reverse=True)[
        : int(cfg["max_tracked"])
    ]
    return {"day": today, "ids": dict(newest)}


def rank(
    clips: list[dict[str, Any]],
    baseline: dict[str, int] | None,
    baseline_hours: float | None,
    now: datetime,
    cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    ranked = []
    for clip in clips:
        if clip["views"] < int(cfg["min_views"]):
            continue
        if thai_ratio(haystack(clip)) < float(cfg["min_thai_ratio"]):
            continue
        item = dict(clip)
        if baseline is not None and baseline_hours and clip["item_id"] in baseline:
            gained = max(0, clip["views"] - int(baseline[clip["item_id"]]))
            item.update(per_hour=gained / baseline_hours, has_trend=True)
        else:
            age = (now - parse_time(clip["published"])).total_seconds() / 3600
            item.update(per_hour=clip["views"] / max(age, 1.0), has_trend=False)
        ranked.append(item)
    ranked.sort(
        key=lambda c: (c["has_trend"] and c["per_hour"] > 0, c["per_hour"]),
        reverse=True,
    )
    return ranked


def squash(text: str) -> str:
    return re.sub(r"[\s#_\-]+", "", text.lower())


def grounded(product: str, clip: dict[str, Any]) -> bool:
    name = squash(product)
    return len(name) >= 2 and name in squash(haystack(clip))


PROMPT = """คุณช่วยคนทำคลิป Shopee Affiliate คัดสินค้า
ด้านล่างเป็นคลิป YouTube Shorts ไทยที่ยอดวิวกำลังขึ้น (JSON)
สำหรับแต่ละคลิป ตอบว่าคลิปนั้นรีวิว/ป้ายยา "สินค้าที่จับต้องได้และซื้อใน Shopee ได้" อะไร

กติกา:
- product = ชื่อสินค้าที่ **ปรากฏตามตัวอักษรในข้อความของคลิปนั้น** (title/description/tags) ห้ามแต่งเอง ห้ามแปล
- คลิปที่ไม่ใช่สินค้า (อาหารทำเอง ซีรีส์ บันเทิง ข่าว) หรือบอกไม่ได้ว่าสินค้าอะไร ให้ product = ""
- angle = ไอเดียมุมคลิปของเราเอง 1 ประโยคสั้น ภาษาไทย (ว่างได้ถ้า product ว่าง)
- ตอบเป็น JSON array อย่างเดียว: [{"id": "...", "product": "...", "angle": "..."}]

คลิป:
"""


async def _ask(text: str, within: float) -> str:
    from app import mimo  # imported late: the openai package only matters here

    return await mimo.complete(
        mimo.client(), [{"role": "user", "content": text}], within=within
    )


def parse_answer(text: str) -> list[dict[str, Any]]:
    match = re.search(r"\[.*\]", text, re.S)
    if not match:
        raise ValueError("no JSON array in answer")
    rows = json.loads(match.group(0))
    if not isinstance(rows, list):
        raise ValueError("answer is not a list")
    return [r for r in rows if isinstance(r, dict)]


def enrich(
    candidates: list[dict[str, Any]], seconds: float
) -> dict[str, dict[str, str]] | None:
    """{id: {product, angle}} for grounded products only; None = mimo unavailable."""
    if not os.environ.get("MIMO_API_KEY", "").strip() or not candidates:
        return None
    payload = [
        {
            "id": c["item_id"],
            "title": c["title"],
            "description": c["description"][:300],
            "tags": c["tags"][:15],
        }
        for c in candidates
    ]
    try:
        answer = asyncio.run(
            _ask(PROMPT + json.dumps(payload, ensure_ascii=False), seconds)
        )
        rows = parse_answer(answer)
    except Exception as exc:
        log.warning("mimo enrich skipped: %s", exc)
        return None
    by_id = {c["item_id"]: c for c in candidates}
    out = {}
    for row in rows:
        clip = by_id.get(str(row.get("id")))
        product = str(row.get("product") or "").strip()
        if clip is None or not product:
            continue
        if not grounded(product, clip):
            log.info("dropped ungrounded product %r for %s", product, clip["item_id"])
            continue
        out[clip["item_id"]] = {
            "product": product[:80],
            "angle": str(row.get("angle") or "").strip()[:160],
        }
    return out


def build_messages(
    picks: list[dict[str, Any]], now: datetime, trend_ready: bool, ai: bool
) -> list[str]:
    local = now.astimezone(analyst.BANGKOK)
    header = f"📈 <b>คลิปสินค้ากำลังมา · YouTube TH</b>\n{local:%d/%m/%Y %H:%M} น. (วิว = ความสนใจ ไม่ใช่ยอดขาย)"
    if not trend_ready:
        header += "\n⚠️ ยังไม่มีรอบก่อนให้เทียบ รอบนี้ใช้วิวเฉลี่ยต่อชม. ตั้งแต่โพสต์"
    if not ai:
        header += "\n⚠️ แยกชื่อสินค้าด้วย AI ไม่สำเร็จ รอบนี้ส่งรายการคลิปดิบ"
    if not picks:
        return [header + "\n\nรอบนี้ไม่มีคลิปผ่านเกณฑ์"]
    blocks = []
    for index, clip in enumerate(picks, 1):
        product = clip.get("product")
        name = product or clip["title"][:80]
        speed = "วิวเพิ่ม" if clip["has_trend"] else "เฉลี่ย"
        lines = [
            f"<b>{index}. {html.escape(name)}</b>",
            f"▶️ {speed} {clip['per_hour']:,.0f}/ชม. (รวม {clip['views']:,}) · {html.escape(clip['channel'][:40])}",
        ]
        if product:
            lines.append(f"🎬 {html.escape(clip['title'][:80])}")
        if clip.get("angle"):
            lines.append(f"💡 {html.escape(clip['angle'])}")
        links = [
            f'<a href="https://youtu.be/{html.escape(clip["item_id"], quote=True)}">ดูคลิป</a>'
        ]
        if product:
            search = "https://shopee.co.th/search?keyword=" + urllib.parse.quote(
                product
            )
            links.append(f'<a href="{html.escape(search, quote=True)}">หาใน Shopee</a>')
        lines.append(" · ".join(links))
        blocks.append("\n".join(lines))
    return analyst.pack(header, blocks)


def run(now: datetime | None = None, config_path: Path = analyst.CONFIG_PATH) -> int:
    now = now or datetime.now(UTC)
    cfg = analyst.load_json(config_path, {})["youtube"]
    root = analyst.data_dir() / "youtube"
    snapshot_dir = root / "snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    api = Api()

    pool = discover(api, analyst.load_json(root / "pool.json", {}), now, cfg)
    # Saved before anything can fail: a retry must not spend search quota twice.
    analyst.write_json(root / "pool.json", pool)
    clips = [to_clip(item) for item in api.videos(list(pool["ids"]))]

    baseline_path = analyst.choose_baseline(snapshot_dir, now)
    baseline, hours = None, None
    if baseline_path:
        baseline = analyst.load_json(baseline_path, {})
        hours = (
            now - analyst.parse_snapshot_time(baseline_path)
        ).total_seconds() / 3600

    ranked = rank(clips, baseline, hours, now, cfg)
    sent = analyst.load_json(root / "sent.json", {})
    candidates = analyst.select_fresh(
        ranked,
        sent,
        now,
        {
            "top_n": cfg["candidates"],
            "repeat_cooldown_hours": cfg["repeat_cooldown_hours"],
        },
    )
    enriched = enrich(candidates, float(cfg["mimo_seconds"]))
    if enriched is None:
        picks = candidates[: int(cfg["top_n"])]
    else:
        picks = [
            {**c, **enriched[c["item_id"]]}
            for c in candidates
            if c["item_id"] in enriched
        ]
        picks = picks[: int(cfg["top_n"])]

    for message in build_messages(
        picks, now, baseline is not None, enriched is not None
    ):
        analyst.send_telegram(message)

    analyst.write_json(
        snapshot_dir / f"{now:%Y%m%dT%H%M%SZ}.json",
        {c["item_id"]: c["views"] for c in clips},
    )
    for pick in picks:
        sent[pick["item_id"]] = now.isoformat()
    retention = int(analyst.load_json(config_path, {}).get("retention_days", 30))
    analyst.write_json(
        root / "sent.json", analyst.prune(snapshot_dir, sent, now, retention)
    )
    log.info(
        "youtube tracked=%d ranked=%d sent=%d ai=%s units=%d",
        len(clips),
        len(ranked),
        len(picks),
        enriched is not None,
        api.units,
    )
    return len(picks)
