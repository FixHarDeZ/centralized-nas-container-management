import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
import db
import scraper
import scheduler

_STATIC_DIR = Path(__file__).parent / "static"


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


# ─── Sources ─────────────────────────────────────────────────────────────────

class SourceIn(BaseModel):
    url: str

class SourceToggle(BaseModel):
    enabled: bool

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


# ─── Torrents ─────────────────────────────────────────────────────────────────

from datetime import datetime
from zoneinfo import ZoneInfo

_TZ = ZoneInfo(config.TZ)


def _today() -> str:
    return datetime.now(_TZ).strftime("%Y-%m-%d")


def _with_keyword_flag(torrents: list[dict], keywords: list[str]) -> list[dict]:
    kw_lower = [k.lower() for k in keywords]
    for t in torrents:
        t["keyword_match"] = any(k in t["title"].lower() for k in kw_lower)
    return torrents


@app.get("/api/torrents")
def api_get_torrents(source_id: int, sort: str = "seeds", filter: str = "all"):
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


# ─── Download ─────────────────────────────────────────────────────────────────

def _content_disposition(title: str) -> str:
    """Build Content-Disposition with RFC 5987 UTF-8 encoding for Thai filenames.

    filename*= comes FIRST (RFC 6266 §4.3) so browsers with proper RFC 5987 support
    (Chrome, Safari, Firefox, Edge) display the Thai title correctly.
    """
    import re
    from urllib.parse import quote

    clean = title.strip()[:100]
    utf8_encoded = quote(clean + ".torrent", encoding="utf-8", safe="")
    ascii_only   = re.sub(r'[^\x20-\x7E]+', ' ', clean).strip()[:60]
    fallback     = (ascii_only or "torrent") + ".torrent"

    # filename*= FIRST — browsers that support RFC 5987 use this and show Thai
    return f"attachment; filename*=UTF-8''{utf8_encoded}; filename=\"{fallback}\""


def _torrent_filename(title: str) -> str:
    """Filesystem-safe ASCII filename for writing to NAS disk."""
    import re
    safe = re.sub(r'[^\x00-\x7F]', '_', title).strip("_ ")[:80]
    return (safe or "torrent") + ".torrent"


@app.get("/api/download/local/{torrent_id}")
async def api_download_local(torrent_id: int):
    t = db.get_torrent(torrent_id)
    if not t:
        raise HTTPException(404, "Torrent not found")

    data = await scraper.fetch_torrent_bytes(t["torrent_url"], t.get("detail_url", ""))
    if not data:
        raise HTTPException(502, "Failed to fetch torrent file from site")

    db.mark_downloaded_local(torrent_id)
    return Response(
        content=data,
        media_type="application/x-bittorrent",
        headers={"Content-Disposition": _content_disposition(t["title"])},
    )


@app.post("/api/download/nas/{torrent_id}")
async def api_download_nas(torrent_id: int):
    t = db.get_torrent(torrent_id)
    if not t:
        raise HTTPException(404, "Torrent not found")

    # Read nas_path from settings — must be within the /downloads mount
    settings  = db.get_settings()
    nas_path  = settings.get("nas_path", config.NAS_DOWNLOADS_DIR).strip() or config.NAS_DOWNLOADS_DIR
    # Ensure the path stays inside the container mount point
    mount     = config.NAS_DOWNLOADS_DIR   # "/downloads"
    if not nas_path.startswith(mount):
        nas_path = mount + "/" + nas_path.lstrip("/")
    nas_dir = Path(nas_path)

    if not Path(mount).exists():
        raise HTTPException(503, f"NAS volume (/downloads) not mounted — uncomment the volume line in docker-compose.yml")
    nas_dir.mkdir(parents=True, exist_ok=True)

    data = await scraper.fetch_torrent_bytes(t["torrent_url"], t.get("detail_url", ""))
    if not data:
        raise HTTPException(502, "Failed to fetch torrent file from site")

    filename = _torrent_filename(t["title"])
    dest = nas_dir / filename
    dest.write_bytes(data)
    db.mark_downloaded_nas(torrent_id)
    return {"filename": filename, "path": str(dest)}


# ─── Proxy detail page (bypass bearbit anti-hotlink check) ────────────────────

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
    if "scrape_interval" in body or "scrape_all_day" in body:
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


@app.delete("/api/debug/clear-today/{source_id}", status_code=204)
def api_clear_today(source_id: int):
    """Delete torrent rows for today in a source."""
    today = datetime.now(_TZ).strftime("%Y-%m-%d")
    with db._conn() as c:
        c.execute("DELETE FROM torrents WHERE source_id=? AND date_posted=?", (source_id, today))


@app.delete("/api/debug/clear-all/{source_id}", status_code=204)
def api_clear_all(source_id: int):
    """Delete ALL torrent rows for a source — full reset."""
    with db._conn() as c:
        c.execute("DELETE FROM torrents WHERE source_id=?", (source_id,))


# ─── SPA static files ─────────────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

@app.get("/{full_path:path}")
def spa_fallback(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(404, f"API endpoint not found: /{full_path}")
    return FileResponse(str(_STATIC_DIR / "index.html"))
