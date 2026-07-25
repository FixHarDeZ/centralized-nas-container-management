"""SQLite persistence for scan jobs and discovered files.

No decisions table: the frontend holds the keep/delete selection and POSTs the
delete list. A re-scan invalidates any prior selection (paths move), so
persisting *pending* decisions would be dead weight.

The `deletions` table is different — it's an audit log of *completed* recycles
(what was moved to trash, and when). It survives Empty-recycle and records
failed attempts too, so the History view can look back regardless of trash state.
"""

import hashlib
import json
import os
import sqlite3
import time
from contextlib import contextmanager

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS scan_jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    root         TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'running',   -- running|done|error
    total_files  INTEGER DEFAULT 0,
    dup_groups   INTEGER DEFAULT 0,
    error        TEXT,
    started_at   REAL NOT NULL,
    finished_at  REAL
);
CREATE TABLE IF NOT EXISTS files (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id  INTEGER NOT NULL REFERENCES scan_jobs(id) ON DELETE CASCADE,
    path    TEXT NOT NULL,
    name    TEXT NOT NULL,
    size    INTEGER NOT NULL,
    mtime   REAL NOT NULL,
    code    TEXT,
    part    TEXT,
    res     TEXT
);
CREATE INDEX IF NOT EXISTS idx_files_job_code ON files(job_id, code);

-- Masked (false-positive) groups. Identity is the EXACT set of file paths, not
-- the code: if a new file with the same code appears later, the set changes,
-- the signature changes, and the group re-surfaces for review. Ceiling: the
-- mask is path-based, so renaming/moving a masked file breaks the mask and
-- re-surfaces the group (no content hashing — acceptable for this tool).
CREATE TABLE IF NOT EXISTS masks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    signature  TEXT NOT NULL UNIQUE,
    code       TEXT,
    paths      TEXT NOT NULL,   -- json array, for display
    note       TEXT,
    created_at REAL NOT NULL
);

-- Audit log of completed recycles (one row per file). `batch` groups a single
-- Recycle click; `ok`/`error` capture failures too. ponytail: no retention —
-- fine for a LAN tool with occasional deletes; add a purge job if it ever grows.
CREATE TABLE IF NOT EXISTS deletions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    batch      TEXT NOT NULL,
    path       TEXT NOT NULL,
    name       TEXT NOT NULL,
    size       INTEGER NOT NULL DEFAULT 0,
    ok         INTEGER NOT NULL DEFAULT 1,
    error      TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_deletions_batch ON deletions(batch);
"""


def mask_signature(paths) -> str:
    """Order-independent signature over normalised paths."""
    norm = sorted(os.path.normpath(p) for p in paths)
    return hashlib.sha1("\n".join(norm).encode()).hexdigest()


@contextmanager
def _conn():
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db():
    with _conn() as con:
        con.executescript(SCHEMA)


def create_job(root: str) -> int:
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO scan_jobs(root, status, started_at) VALUES (?, 'running', ?)",
            (root, time.time()),
        )
        return cur.lastrowid


def finish_job(job_id: int, files: list, dup_groups: int):
    with _conn() as con:
        con.executemany(
            "INSERT INTO files(job_id, path, name, size, mtime, code, part, res) "
            "VALUES (?,?,?,?,?,?,?,?)",
            [(job_id, f["path"], f["name"], f["size"], f["mtime"],
              f["code"], f["part"], f["res"]) for f in files],
        )
        con.execute(
            "UPDATE scan_jobs SET status='done', total_files=?, dup_groups=?, "
            "finished_at=? WHERE id=?",
            (len(files), dup_groups, time.time(), job_id),
        )


def fail_job(job_id: int, error: str):
    with _conn() as con:
        con.execute(
            "UPDATE scan_jobs SET status='error', error=?, finished_at=? WHERE id=?",
            (error, time.time(), job_id),
        )


def get_job(job_id: int):
    with _conn() as con:
        row = con.execute("SELECT * FROM scan_jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None


def latest_job():
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM scan_jobs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def groups(job_id: int, min_count: int = 2):
    """Return duplicate groups (code with >= min_count files), largest first.
    Masked groups (exact file-set signature in `masks`) are excluded.
    """
    masked = masked_signatures()
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM files WHERE job_id=? AND code IS NOT NULL "
            "ORDER BY code, size DESC",
            (job_id,),
        ).fetchall()
    by_code: dict[str, list] = {}
    for r in rows:
        by_code.setdefault(r["code"], []).append(dict(r))
    out = []
    for code, fs in sorted(by_code.items()):
        if len(fs) < min_count:
            continue
        if mask_signature([f["path"] for f in fs]) in masked:
            continue
        parts = {f["part"] for f in fs if f["part"]}
        out.append({
            "code": code,
            "multipart": len(parts) >= 2,
            "files": fs,
        })
    return out


# ---------- masks ----------

def add_mask(paths: list[str], code: str | None = None, note: str | None = None) -> str:
    sig = mask_signature(paths)
    with _conn() as con:
        con.execute(
            "INSERT OR IGNORE INTO masks(signature, code, paths, note, created_at) "
            "VALUES (?,?,?,?,?)",
            (sig, code, json.dumps(paths), note, time.time()),
        )
    return sig


def list_masks() -> list:
    with _conn() as con:
        rows = con.execute("SELECT * FROM masks ORDER BY id DESC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["paths"] = json.loads(d["paths"])
        out.append(d)
    return out


def delete_mask(mask_id: int) -> bool:
    with _conn() as con:
        cur = con.execute("DELETE FROM masks WHERE id=?", (mask_id,))
        return cur.rowcount > 0


def masked_signatures() -> set:
    with _conn() as con:
        return {r["signature"] for r in con.execute("SELECT signature FROM masks")}


# ---------- deletion audit log ----------

def log_deletions(batch: str, results: list) -> None:
    """Persist a completed recycle batch. `results` = recycle()'s per-file dicts
    ({path, ok, size, error?}). Names derived from path — never trust client."""
    now = time.time()
    with _conn() as con:
        con.executemany(
            "INSERT INTO deletions(batch, path, name, size, ok, error, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            [(batch, r["path"], os.path.basename(r["path"]), r.get("size", 0),
              1 if r["ok"] else 0, r.get("error"), now) for r in results],
        )


def list_deletions(limit: int = 500) -> list:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM deletions ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]
