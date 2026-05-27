import asyncio
import base64
import os
import re
import secrets
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
import db
import line_notify
import telegram_notify
import scraper
import scheduler

_STATIC_DIR = Path(__file__).parent / "static"

_AUTH_ENABLED = bool(config.BASIC_AUTH_USER and config.BASIC_AUTH_PASS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    db.init_db()
    db.seed_default_sources(config.DEFAULT_URLS)
    await scraper.init()
    scheduler.start()
    yield
    scheduler.stop()
    await scraper.close()


app = FastAPI(title="TorrentWatch", lifespan=lifespan)


_AUTH_BYPASS_PATHS = {"/api/status"}


@app.middleware("http")
async def basic_auth_middleware(request: Request, call_next):
    if not _AUTH_ENABLED or request.url.path in _AUTH_BYPASS_PATHS:
        return await call_next(request)
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth[6:]).decode("utf-8")
            user, _, password = decoded.partition(":")
            if (secrets.compare_digest(user, config.BASIC_AUTH_USER) and
                    secrets.compare_digest(password, config.BASIC_AUTH_PASS)):
                return await call_next(request)
        except Exception:
            pass
    return Response(
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="TorrentWatch"'},
    )


# ─── Sources ─────────────────────────────────────────────────────────────────

class SourceIn(BaseModel):
    url: str

class SourceToggle(BaseModel):
    enabled: bool

class SourceRename(BaseModel):
    label: str

class SourceReorder(BaseModel):
    direction: Literal["up", "down"]

@app.get("/api/sources")
def api_get_sources():
    return db.get_sources()

@app.post("/api/sources", status_code=201)
def api_add_source(body: SourceIn):
    url = body.url.strip()
    if not url.startswith("http"):
        raise HTTPException(400, "URL must start with http(s)://")
    try:
        return db.add_source(url)
    except Exception:
        raise HTTPException(409, "Source URL already exists")

@app.delete("/api/sources/{source_id}", status_code=204)
def api_remove_source(source_id: int):
    db.remove_source(source_id)

@app.patch("/api/sources/{source_id}", status_code=204)
def api_toggle_source(source_id: int, body: SourceToggle):
    db.toggle_source(source_id, body.enabled)

@app.patch("/api/sources/{source_id}/label", status_code=204)
def api_rename_source(source_id: int, body: SourceRename):
    db.rename_source(source_id, body.label)

@app.post("/api/sources/{source_id}/reorder", status_code=200)
def api_reorder_source(source_id: int, body: SourceReorder):
    db.reorder_source(source_id, body.direction)
    return db.get_sources()


# ─── Categories ──────────────────────────────────────────────────────────────

@app.get("/api/categories")
def api_get_categories():
    """Return the current cat_id → name mapping (pre-seeded + live-extracted)."""
    return scraper.get_cat_cache()


# ─── Torrents ─────────────────────────────────────────────────────────────────

_TZ = ZoneInfo(config.TZ)


def _today() -> str:
    return datetime.now(_TZ).strftime("%Y-%m-%d")


def _with_keyword_flag(torrents: list[dict], keywords: list[str]) -> list[dict]:
    kw_lower = [k.lower() for k in keywords]
    for t in torrents:
        t["keyword_match"] = any(k in t["title"].lower() for k in kw_lower)
    return torrents


@app.get("/api/torrents")
def api_get_torrents(source_id: int, sort: str = "seeds", filter: str = "all"):  # noqa: A002
    today = _today()
    rows = db.get_today_torrents(source_id, today, sort)
    keywords = db.get_keywords_for_source(source_id)
    rows = _with_keyword_flag(rows, keywords)
    if filter == "keyword":
        rows = [r for r in rows if r["keyword_match"]]
    return {"date": today, "torrents": rows}


@app.get("/api/history")
def api_get_history(source_id: int, date: str, sort: str = "seeds"):
    rows = db.get_history_torrents(source_id, date, sort)
    keywords = db.get_keywords_for_source(source_id)
    rows = _with_keyword_flag(rows, keywords)
    return {"date": date, "torrents": rows}


@app.get("/api/history/dates")
def api_history_dates(source_id: int):
    return db.get_history_dates(source_id)


@app.get("/api/search")
def api_search(source_id: int, q: str, limit: int = 50):
    if not q or len(q.strip()) < 2:
        raise HTTPException(400, "Query must be at least 2 characters")
    rows = db.search_torrents(source_id, q.strip(), min(limit, 200))
    keywords = db.get_keywords_for_source(source_id)
    rows = _with_keyword_flag(rows, keywords)
    return {"query": q, "count": len(rows), "torrents": rows}


# ─── Download ─────────────────────────────────────────────────────────────────

def _content_disposition(title: str) -> str:
    """Build Content-Disposition header using ASCII-safe filename only.

    Deliberately avoids RFC 5987 filename*= UTF-8 encoding — some reverse
    proxies (including DSM Application Portal) may struggle to parse it,
    causing the response to stall. Thai characters are replaced with underscores;
    the browser/torrent client recognises the file by its .torrent extension.
    """
    ascii_only = re.sub(r'[^\x20-\x7E]+', '_', title.strip())[:80].strip('_')
    safe = (ascii_only or "torrent") + ".torrent"
    return f'attachment; filename="{safe}"'




@app.get("/api/download/local/{torrent_id}")
async def api_download_local(torrent_id: int):
    t = db.get_torrent(torrent_id)
    if not t:
        raise HTTPException(404, "Torrent not found")

    data = await scraper.fetch_torrent_bytes(t["torrent_url"], t.get("detail_url", ""))
    if not data:
        raise HTTPException(502, "Failed to fetch torrent file from site")

    db.mark_downloaded_local(torrent_id)
    # Use StreamingResponse (Transfer-Encoding: chunked, no Content-Length) +
    # application/octet-stream to avoid DSM reverse proxy content-type filtering
    # and response buffering that stalls fetch() for binary downloads.
    return StreamingResponse(
        iter([data]),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": _content_disposition(t["title"]),
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-store",
        },
    )


@app.post("/api/download/nas/{torrent_id}")
async def api_download_nas(torrent_id: int):
    t = db.get_torrent(torrent_id)
    if not t:
        raise HTTPException(404, "Torrent not found")

    nas_dir = Path(config.NAS_DOWNLOADS_DIR)
    if not nas_dir.exists():
        raise HTTPException(503, "NAS volume (/downloads) not mounted — uncomment the volume line in docker-compose.yml")
    nas_dir.mkdir(parents=True, exist_ok=True)

    data = await scraper.fetch_torrent_bytes(t["torrent_url"], t.get("detail_url", ""))
    if not data:
        raise HTTPException(502, "Failed to fetch torrent file from site")

    filename = db.torrent_filename(t["title"])
    dest = nas_dir / filename
    dest.write_bytes(data)
    db.mark_downloaded_nas(torrent_id)
    return {"filename": filename, "path": str(dest)}


# ─── Proxy detail page (bypass bearbit anti-hotlink check) ────────────────────

@app.get("/api/cover/{torrent_id}")
async def api_cover(torrent_id: int):
    """Proxy cover image through authenticated scraper session (fixes CDN session-expire breaks)."""
    t = db.get_torrent(torrent_id)
    if not t or not t.get("cover_url"):
        raise HTTPException(404, "No cover image")
    data = await scraper.fetch_cover_bytes(t["cover_url"])
    if not data:
        raise HTTPException(502, "Failed to fetch cover image")
    url_lower = t["cover_url"].lower()
    ct = "image/jpeg"
    if ".png" in url_lower: ct = "image/png"
    elif ".gif" in url_lower: ct = "image/gif"
    elif ".webp" in url_lower: ct = "image/webp"
    return Response(content=data, media_type=ct, headers={"Cache-Control": "max-age=3600"})


@app.get("/api/stats")
def api_stats(source_id: int | None = None):
    return db.get_stats(source_id)


class TorrentStatusBody(BaseModel):
    status: int  # 0=normal, 1=watched, 2=skip

@app.post("/api/torrents/{torrent_id}/status", status_code=204)
def api_set_torrent_status(torrent_id: int, body: TorrentStatusBody):
    if body.status not in (0, 1, 2):
        raise HTTPException(400, "status must be 0, 1, or 2")
    db.mark_torrent_status(torrent_id, body.status)


@app.get("/api/detail/{torrent_id}")
async def api_proxy_detail(torrent_id: int):
    """Proxy the torrent detail page through our backend so bearbit's Referer check passes."""
    t = db.get_torrent(torrent_id)
    if not t:
        raise HTTPException(404, "Torrent not found")

    html_bytes = await scraper.fetch_detail_html(t["detail_url"])
    if html_bytes is None:
        raise HTTPException(502, "Failed to fetch detail page")

    # Inject <base href> so relative resources (images, CSS, links) resolve to bearbit
    base_tag = f'<base href="{config.SITE_BASE_URL}/">'.encode("ascii")
    if b"<head>" in html_bytes:
        html_bytes = html_bytes.replace(b"<head>", b"<head>" + base_tag, 1)
    else:
        html_bytes = base_tag + html_bytes

    # bearbit serves as TIS-620 — preserve charset
    return Response(content=html_bytes, media_type="text/html; charset=tis-620")


# ─── Keywords ─────────────────────────────────────────────────────────────────

class KeywordIn(BaseModel):
    source_id: int
    keyword: str

@app.get("/api/keywords")
def api_get_keywords(source_id: int):
    return db.get_keywords(source_id)

@app.post("/api/keywords", status_code=201)
def api_add_keyword(body: KeywordIn):
    kw = body.keyword.strip()
    if not kw:
        raise HTTPException(400, "Keyword cannot be empty")
    try:
        return db.add_keyword(body.source_id, kw)
    except Exception:
        raise HTTPException(409, "Keyword already exists for this source")

@app.delete("/api/keywords/{keyword_id}", status_code=204)
def api_remove_keyword(keyword_id: int):
    db.remove_keyword(keyword_id)


# ─── Settings ─────────────────────────────────────────────────────────────────

@app.get("/api/settings")
def api_get_settings():
    return db.get_settings()

@app.put("/api/settings", status_code=204)
def api_update_settings(body: dict):
    db.update_settings(body)
    scheduler.reload_scrape_job()


# ─── Scrape / Status ─────────────────────────────────────────────────────────

@app.post("/api/scrape")
async def api_scrape(background_tasks: BackgroundTasks):
    if scheduler._scrape_status == "running":
        return {"status": "already_running"}
    background_tasks.add_task(scheduler.trigger_now)
    return {"status": "started"}

@app.get("/api/status")
def api_status():
    return scheduler.status()


# ─── Debug ───────────────────────────────────────────────────────────────────

@app.get("/api/debug/html")
async def api_debug_html(source_id: int):
    sources = db.get_sources()
    src = next((s for s in sources if s["id"] == source_id), None)
    if not src:
        raise HTTPException(404, "Source not found")
    html = await scraper.fetch_raw_html(src["url"])
    if html is None:
        raise HTTPException(502, "Failed to fetch page — check login credentials")
    return Response(content=html, media_type="text/html")


@app.get("/api/debug/download-test/{torrent_id}")
async def api_debug_download_test(torrent_id: int):
    """Probe the download URL for a torrent — returns diagnostic info without saving."""
    t = db.get_torrent(torrent_id)
    if not t:
        raise HTTPException(404, "Torrent not found")
    result = await scraper.probe_download_url(t["torrent_url"])
    result["stored_url"]  = t["torrent_url"]
    result["detail_url"]  = t.get("detail_url", "")
    result["title"] = t["title"][:60]
    return result


@app.get("/api/debug/login-page")
async def api_debug_login_page():
    """Return raw HTML of the login page — use to inspect form field names."""
    html = await scraper.fetch_login_page_html()
    if html is None:
        raise HTTPException(502, "Failed to fetch login page")
    return Response(content=html, media_type="text/html")


@app.post("/api/debug/relogin")
async def api_debug_relogin():
    """Force re-login and report result with details."""
    ok = await scraper._login()
    scraper._login_ok = ok
    return {"login_ok": ok, "scraper_ready": scraper.is_ready()}


# ─── LINE Test ─────────────────────────────────────────────────────────────────

@app.post("/api/line/test")
async def api_line_test():
    """Send a test LINE message to verify the configuration."""
    result = await line_notify.send_test_message()
    if result["ok"]:
        return {"status": "ok", "message": "Test message sent"}
    else:
        raise HTTPException(400, result.get("error", "LINE send failed"))


# ─── Telegram ─────────────────────────────────────────────────────────────────

@app.post("/api/telegram/test")
async def api_telegram_test():
    """Send a test Telegram message to verify the configuration."""
    result = await telegram_notify.send_test_message()
    if result["ok"]:
        return {"status": "ok", "message": "Test message sent"}
    else:
        raise HTTPException(400, result.get("error", "Telegram send failed"))


@app.get("/api/telegram/get-chat-id")
async def api_telegram_get_chat_id():
    """Call getUpdates to help user discover their Telegram chat_id."""
    return await telegram_notify.get_updates()


@app.delete("/api/debug/clear-today/{source_id}", status_code=204)
def api_clear_today(source_id: int):
    db.clear_source_today(source_id, _today())


@app.delete("/api/debug/clear-all/{source_id}", status_code=204)
def api_clear_all(source_id: int):
    db.clear_source_all(source_id)


# ─── SPA static files ─────────────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

@app.get("/{full_path:path}")
def spa_fallback(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(404, f"API endpoint not found: /{full_path}")
    return FileResponse(str(_STATIC_DIR / "index.html"))
