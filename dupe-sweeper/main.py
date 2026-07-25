import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
import db
import dedup
import recycle


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    db.init_db()
    yield


app = FastAPI(title="dupe-sweeper", lifespan=lifespan)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _run_scan(job_id: int, root: str):
    try:
        files = dedup.scan(root, dedup.DEFAULT_EXTS)
        codes = {}
        for f in files:
            if f["code"]:
                codes[f["code"]] = codes.get(f["code"], 0) + 1
        dup_groups = sum(1 for c in codes.values() if c >= 2)
        db.finish_job(job_id, files, dup_groups)
    except Exception as e:  # noqa: BLE001 — surface any failure to the job row
        db.fail_job(job_id, str(e))


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/roots")
def api_roots():
    return {"roots": config.SCAN_ROOTS}


class ScanRequest(BaseModel):
    root: str
    subpath: str | None = None


def _resolve_under_roots(target: str) -> str:
    real = os.path.realpath(target)
    for r in config.SCAN_ROOTS:
        rr = os.path.realpath(r)
        if real == rr or real.startswith(rr + os.sep):
            return real
    raise HTTPException(400, "path is not under an allowed scan root")


@app.post("/api/scan")
def api_scan(req: ScanRequest):
    if req.root not in config.SCAN_ROOTS:
        raise HTTPException(400, "unknown scan root")
    target = os.path.join(req.root, req.subpath.lstrip("/")) if req.subpath else req.root
    target = _resolve_under_roots(target)
    if not os.path.isdir(target):
        raise HTTPException(400, "not a directory")
    job_id = db.create_job(target)
    threading.Thread(target=_run_scan, args=(job_id, target), daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/scan/{job_id}")
def api_scan_status(job_id: int):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(404)
    return job


@app.get("/api/groups/{job_id}")
def api_groups(job_id: int, min: int = 2):
    if not db.get_job(job_id):
        raise HTTPException(404)
    return {"groups": db.groups(job_id, min_count=min)}


class DeleteRequest(BaseModel):
    paths: list[str]


@app.post("/api/delete")
def api_delete(req: DeleteRequest):
    if not req.paths:
        raise HTTPException(400, "no paths given")
    try:
        res = recycle.recycle(req.paths, config.SCAN_ROOTS, config.TRASH_DIR)
    except ValueError as e:
        # path outside allowed roots, or misconfig — reject whole request
        raise HTTPException(400, str(e))
    db.log_deletions(res["batch"], res["results"])  # audit log survives Empty-recycle
    return res


# ---------- masks ----------

class MaskRequest(BaseModel):
    paths: list[str]
    code: str | None = None
    note: str | None = None


@app.get("/api/masks")
def api_masks():
    return {"masks": db.list_masks()}


@app.post("/api/masks")
def api_add_mask(req: MaskRequest):
    if len(req.paths) < 2:
        raise HTTPException(400, "a mask needs at least 2 paths")
    return {"signature": db.add_mask(req.paths, req.code, req.note)}


@app.delete("/api/masks/{mask_id}")
def api_delete_mask(mask_id: int):
    if not db.delete_mask(mask_id):
        raise HTTPException(404)
    return {"ok": True}


# ---------- rename ----------

class RenameRequest(BaseModel):
    path: str
    new_name: str


@app.post("/api/rename")
def api_rename(req: RenameRequest):
    try:
        dest = recycle.rename(req.path, req.new_name, config.SCAN_ROOTS)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except OSError as e:
        raise HTTPException(500, str(e))
    return {"path": dest, "name": os.path.basename(dest)}


# ---------- recycle folder ----------

@app.get("/api/trash")
def api_trash():
    return recycle.trash_stats(config.TRASH_DIR)


@app.get("/api/trash/files")
def api_trash_files():
    return {"files": recycle.list_trash(config.TRASH_DIR)}


class RestoreRequest(BaseModel):
    path: str


@app.post("/api/trash/restore")
def api_trash_restore(req: RestoreRequest):
    try:
        dest = recycle.restore(req.path, config.SCAN_ROOTS, config.TRASH_DIR)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except OSError as e:
        raise HTTPException(500, str(e))
    return {"path": dest, "name": os.path.basename(dest)}


@app.post("/api/trash/empty")
def api_trash_empty():
    try:
        return recycle.empty_trash(config.TRASH_DIR, config.SCAN_ROOTS)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/deletions")
def api_deletions():
    return {"deletions": db.list_deletions()}


@app.get("/api/status")
def api_status():
    return {"latest_job": db.latest_job(), "roots": config.SCAN_ROOTS}
