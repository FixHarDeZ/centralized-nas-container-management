import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
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
def api_titles(status: str | None = None):
    return {"titles": db.list_titles(status=status)}


@app.post("/api/titles/{tid}/keep")
def api_keep(tid: int):
    if not db.keep_title(tid):
        raise HTTPException(404)
    return {"ok": True}


@app.post("/api/titles/{tid}/delete")
def api_delete(tid: int):
    if not db.purge_title(tid):
        raise HTTPException(404)
    return {"ok": True}


@app.post("/api/scrape")
def api_scrape():
    threading.Thread(target=scraper.scrape_cycle, daemon=True).start()
    return {"started": True}


@app.get("/api/status")
def api_status():
    return {"stats": db.stats(), "last_scrape": db.last_scrape()}


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


@app.get("/covers/{tid}.jpg")
def get_cover(tid: int):
    return _file_response(db.cover_path(tid), "image/jpeg")


@app.get("/opds")
def opds_root():
    return Response(opds.root_feed(), media_type="application/atom+xml")


@app.get("/opds/{status}")
def opds_titles(status: str):
    if status not in ("new", "kept"):
        raise HTTPException(404)
    return Response(opds.titles_feed(status), media_type="application/atom+xml")
