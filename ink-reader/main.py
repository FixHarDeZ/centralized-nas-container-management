import os
import threading
import zipfile
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response

import config
import db
import opds
import scraper


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    for d in (config.LIBRARY_DIR, config.COVERS_DIR, config.BACKUP_DIR):
        os.makedirs(d, exist_ok=True)
    if os.environ.get("INK_DISABLE_SCHEDULER") != "1":
        import scheduler
        scheduler.start()
        yield
        scheduler.shutdown()
    else:
        yield


app = FastAPI(title="ink-reader", lifespan=lifespan)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/titles")
def api_titles(status: str | None = None, source: str | None = None):
    return {"titles": db.list_titles(status=status, source=source)}


@app.post("/api/titles/{tid}/delete")
def api_delete(tid: int):
    if not db.purge_title(tid):
        raise HTTPException(404)
    return {"ok": True}


@app.post("/api/titles/{tid}/like")
def api_like(tid: int, payload: dict):
    liked = bool(payload.get("liked"))
    if not db.set_liked(tid, liked):
        raise HTTPException(404)
    return {"id": tid, "liked": liked}


@app.post("/api/scrape")
def api_scrape():
    threading.Thread(target=scraper.scrape_cycle, daemon=True).start()
    return {"started": True}


@app.get("/api/status")
def api_status():
    return {
        "stats": db.stats(),
        "last_scrape": db.last_scrape(),
        "sources": db.source_stats(),
    }


@app.get("/api/settings")
def api_settings():
    return db.get_settings()


@app.put("/api/settings")
def api_update_settings(payload: dict):
    try:
        return db.update_settings(payload)
    except ValueError as e:
        raise HTTPException(400, str(e))


def _file_response(path: str, media_type: str, filename: str | None = None):
    if not os.path.exists(path):
        raise HTTPException(404)
    return FileResponse(path, media_type=media_type, filename=filename)


@app.get("/files/{tid}.cbz")
def get_cbz(tid: int):
    row = db.get_title(tid)
    if not row:
        raise HTTPException(404)
    return _file_response(db.cbz_path(tid), "application/vnd.comicbook+zip",
                          filename=f"{row['title']}.cbz")


IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
               ".webp": "image/webp", ".gif": "image/gif", ".avif": "image/avif"}


def _cbz_pages(tid: int) -> tuple[str, list[str]]:
    """Image members of a title's CBZ in reading order. 404 when title or file is gone."""
    path = db.cbz_path(tid)
    if not db.get_title(tid) or not os.path.exists(path):
        raise HTTPException(404)
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist()
                 if os.path.splitext(n)[1].lower() in IMAGE_TYPES]
    return path, sorted(names)


@app.get("/api/titles/{tid}/pages")
def api_pages(tid: int):
    _, names = _cbz_pages(tid)
    row = db.get_title(tid)
    return {"id": tid, "title": row["title"], "count": len(names),
            "liked": bool(row["liked"])}


@app.get("/read/{tid}")
def reader(tid: int):
    return FileResponse(os.path.join(STATIC_DIR, "reader.html"))


@app.get("/read/{tid}/{n}")
def read_page(tid: int, n: int):
    path, names = _cbz_pages(tid)
    if not 1 <= n <= len(names):
        raise HTTPException(404)
    name = names[n - 1]
    with zipfile.ZipFile(path) as z:
        data = z.read(name)
    # CBZ content never changes under a given id; let the phone cache it.
    return Response(data, media_type=IMAGE_TYPES[os.path.splitext(name)[1].lower()],
                    headers={"Cache-Control": "private, max-age=604800"})


@app.get("/covers/{tid}.jpg")
def get_cover(tid: int):
    return _file_response(db.cover_path(tid), "image/jpeg")


def _opds_base_url(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto", "http")
    host = request.headers.get("host", "localhost")
    return f"{proto}://{host}"


@app.get("/opds")
def opds_root(request: Request):
    return Response(opds.root_feed(_opds_base_url(request)),
                    media_type="application/atom+xml")


@app.get("/opds/{section}")
def opds_titles(section: str, request: Request):
    if section not in opds.SECTION_NAMES:
        raise HTTPException(404)
    return Response(opds.titles_feed(section, _opds_base_url(request)),
                    media_type="application/atom+xml")
