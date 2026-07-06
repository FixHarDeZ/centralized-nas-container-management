# ink-reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** New `ink-reader/` stack — scrapes doujin-th.com latest releases to CBZ files on the NAS, serves a keep/delete curation dashboard and an OPDS feed for KOReader on a Meebook M8.

**Architecture:** Single FastAPI container (flat-file layout copied from `torrentwatch/`) + nginx basic-auth sidecar (copied from `wallpaper-scout/`). SQLite catalog with `new → kept | deleted` lifecycle; `deleted` rows are tombstones that block re-download. APScheduler runs scrape/expiry/backup jobs.

**Tech Stack:** Python 3.12-slim, FastAPI, uvicorn, httpx, beautifulsoup4, APScheduler, SQLite (stdlib), nginx:alpine sidecar.

**Spec:** `docs/superpowers/specs/2026-07-06-ink-reader-design.md`

## Global Constraints

- Ports: nginx sidecar publishes **5068**; FastAPI app is `expose: 8000` only (container network); DSM reverse proxy **15068** is a manual DSM step.
- Retention default: **30 days** (`INK_RETENTION_DAYS=30`). Scrape interval default **6h**, `INK_MAX_NEW_PER_CYCLE=10`.
- Dependencies pinned exactly as `torrentwatch/requirements.txt`: `fastapi==0.115.5`, `uvicorn[standard]==0.32.1`, `httpx==0.28.1`, `beautifulsoup4==4.12.3`, `apscheduler==3.10.4`. No other runtime deps. `pytest` is dev-only (never in requirements.txt).
- Vault keys: `stacks.ink_reader.dashboard.username` / `stacks.ink_reader.dashboard.password` — edit ONLY via `make edit-vault`, never edit `vault.sops.yaml` directly.
- Never commit `.env`, `nginx/.htpasswd`, or real hostnames/credentials; use placeholders like `<NAS_HOST>` in docs.
- doujin-th.com is unreachable from the workstation sandbox (MITM block) but was verified live via NAS SSH before implementation (2026-07-06). Real findings baked into Tasks 3-4: the site is SMF-forum-based; there is **no server-side zip/download** — the page's "Download" button only generates a PDF client-side in the browser (fetches already-visible reader images, builds PDF with jsPDF). The scraper's only path is: scrape reader-page image URLs from static HTML and build a CBZ directly — there is no zip-download branch. Reader images are hotlink-protected (403 without a `Referer` header set to the title page URL) — `fetch_bytes` takes an optional `referer` param. No login/PM gate exists. Task 9's live step is a redeploy confirmation, not a selector-discovery session.
- Timezone `Asia/Bangkok` everywhere.
- Run tests from repo root: `python3 -m pytest ink-reader/tests -v` (a top-level `conftest.py` in `ink-reader/` adds the stack dir to `sys.path`). If imports fail locally, install dev deps once: `python3 -m pip install -r ink-reader/requirements.txt pytest`.
- CLAUDE.md rules apply: after finishing work write `ink-reader/.notes/daily_log.md` + `ink-reader/.notes/00_INDEX.md`.

---

### Task 1: Scaffold + config + DB layer

**Files:**
- Create: `ink-reader/config.py`
- Create: `ink-reader/db.py`
- Create: `ink-reader/requirements.txt`
- Create: `ink-reader/conftest.py`
- Create: `ink-reader/tests/conftest.py`
- Test: `ink-reader/tests/test_db.py`

**Interfaces:**
- Consumes: nothing (first task)
- Produces:
  - `config` module attrs: `SITE_BASE_URL, USER_AGENT, DATA_DIR, DB_PATH, LIBRARY_DIR, COVERS_DIR, BACKUP_DIR, SCRAPE_INTERVAL_HOURS, MAX_NEW_PER_CYCLE, RETENTION_DAYS, REQUEST_DELAY_SECONDS, TZ`
  - `db.init_db()`, `db.now_iso() -> str`
  - `db.known_slugs() -> set[str]`
  - `db.add_title(slug: str, title: str, tags: str, pages: int, file_size: int, source_url: str) -> int`
  - `db.get_title(tid: int) -> dict | None`
  - `db.list_titles(status: str | None = None) -> list[dict]`
  - `db.keep_title(tid: int) -> bool`
  - `db.purge_title(tid: int) -> bool` (removes CBZ+cover files AND sets status=deleted)
  - `db.expired_ids() -> list[int]`
  - `db.log_scrape(found: int, downloaded: int, error: str | None = None)`
  - `db.last_scrape() -> dict | None`
  - `db.stats() -> dict`
  - `db.cbz_path(tid: int) -> str`, `db.cover_path(tid: int) -> str`

- [ ] **Step 1: Create requirements + conftest files**

`ink-reader/requirements.txt`:
```
fastapi==0.115.5
uvicorn[standard]==0.32.1
httpx==0.28.1
beautifulsoup4==4.12.3
apscheduler==3.10.4
```

`ink-reader/conftest.py` (makes `import config` etc. work when pytest runs from repo root):
```python
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
```

`ink-reader/tests/conftest.py`:
```python
import os

import pytest

import config
import db


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "ink.db"))
    monkeypatch.setattr(config, "LIBRARY_DIR", str(tmp_path / "library"))
    monkeypatch.setattr(config, "COVERS_DIR", str(tmp_path / "covers"))
    monkeypatch.setattr(config, "BACKUP_DIR", str(tmp_path / "backups"))
    os.makedirs(config.LIBRARY_DIR)
    os.makedirs(config.COVERS_DIR)
    db.init_db()
    return tmp_path
```

- [ ] **Step 2: Create config.py**

```python
import os

SITE_BASE_URL = os.environ.get("INK_SITE_BASE_URL", "https://doujin-th.com")
USER_AGENT = os.environ.get(
    "INK_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
)

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "ink.db")
LIBRARY_DIR = os.path.join(DATA_DIR, "library")
COVERS_DIR = os.path.join(DATA_DIR, "covers")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")

SCRAPE_INTERVAL_HOURS = int(os.environ.get("INK_SCRAPE_INTERVAL_HOURS", "6"))
MAX_NEW_PER_CYCLE = int(os.environ.get("INK_MAX_NEW_PER_CYCLE", "10"))
RETENTION_DAYS = int(os.environ.get("INK_RETENTION_DAYS", "30"))
REQUEST_DELAY_SECONDS = float(os.environ.get("INK_REQUEST_DELAY_SECONDS", "2"))

TZ = "Asia/Bangkok"
```

- [ ] **Step 3: Write the failing tests**

`ink-reader/tests/test_db.py`:
```python
import os

import config
import db


def _add(slug="s1", **kw):
    args = dict(slug=slug, title="T", tags="tag1,tag2", pages=20,
                file_size=1000, source_url="https://x/s1/")
    args.update(kw)
    return db.add_title(**args)


def test_add_and_get(data_dir):
    tid = _add()
    row = db.get_title(tid)
    assert row["slug"] == "s1"
    assert row["status"] == "new"
    assert row["expires_at"] is not None


def test_known_slugs_includes_deleted(data_dir):
    tid = _add("s1")
    _add("s2")
    db.purge_title(tid)
    assert db.known_slugs() == {"s1", "s2"}


def test_keep_clears_expiry(data_dir):
    tid = _add()
    assert db.keep_title(tid)
    row = db.get_title(tid)
    assert row["status"] == "kept"
    assert row["expires_at"] is None


def test_purge_removes_files_and_tombstones(data_dir):
    tid = _add()
    open(db.cbz_path(tid), "wb").write(b"x")
    open(db.cover_path(tid), "wb").write(b"x")
    assert db.purge_title(tid)
    assert not os.path.exists(db.cbz_path(tid))
    assert not os.path.exists(db.cover_path(tid))
    row = db.get_title(tid)
    assert row["status"] == "deleted"
    assert row["file_size"] is None


def test_expired_ids(data_dir):
    tid = _add("old")
    with db._connect() as conn:
        conn.execute("UPDATE titles SET expires_at='2000-01-01T00:00:00+07:00' WHERE id=?", (tid,))
    _add("fresh")
    kept = _add("kept-old")
    db.keep_title(kept)
    assert db.expired_ids() == [tid]


def test_list_filter_and_stats(data_dir):
    _add("a")
    tid = _add("b")
    db.keep_title(tid)
    assert len(db.list_titles()) == 2
    assert [r["slug"] for r in db.list_titles(status="kept")] == ["b"]
    s = db.stats()
    assert s["new"]["count"] == 1
    assert s["kept"]["count"] == 1
    assert s["kept"]["size"] == 1000


def test_scrape_log(data_dir):
    assert db.last_scrape() is None
    db.log_scrape(5, 3)
    db.log_scrape(2, 0, error="boom")
    last = db.last_scrape()
    assert last["found"] == 2
    assert last["error"] == "boom"
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `python3 -m pytest ink-reader/tests/test_db.py -v`
Expected: FAIL / collection error — `db` has no attributes yet.

- [ ] **Step 5: Implement db.py**

```python
import os
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS titles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slug TEXT UNIQUE NOT NULL,
  title TEXT NOT NULL,
  tags TEXT DEFAULT '',
  pages INTEGER DEFAULT 0,
  file_size INTEGER,
  status TEXT NOT NULL DEFAULT 'new',
  source_url TEXT DEFAULT '',
  downloaded_at TEXT NOT NULL,
  expires_at TEXT
);
CREATE TABLE IF NOT EXISTS scrape_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_at TEXT NOT NULL,
  found INTEGER DEFAULT 0,
  downloaded INTEGER DEFAULT 0,
  error TEXT
);
"""


def _connect():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def now_iso() -> str:
    return datetime.now(ZoneInfo(config.TZ)).isoformat(timespec="seconds")


def init_db():
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with _connect() as conn:
        conn.executescript(SCHEMA)


def cbz_path(tid: int) -> str:
    return os.path.join(config.LIBRARY_DIR, f"{tid}.cbz")


def cover_path(tid: int) -> str:
    return os.path.join(config.COVERS_DIR, f"{tid}.jpg")


def known_slugs() -> set[str]:
    with _connect() as conn:
        return {r["slug"] for r in conn.execute("SELECT slug FROM titles")}


def add_title(slug, title, tags, pages, file_size, source_url) -> int:
    expires = (
        datetime.now(ZoneInfo(config.TZ)) + timedelta(days=config.RETENTION_DAYS)
    ).isoformat(timespec="seconds")
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO titles (slug, title, tags, pages, file_size, source_url,"
            " downloaded_at, expires_at) VALUES (?,?,?,?,?,?,?,?)",
            (slug, title, tags, pages, file_size, source_url, now_iso(), expires),
        )
        return cur.lastrowid


def get_title(tid: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM titles WHERE id=?", (tid,)).fetchone()
        return dict(row) if row else None


def list_titles(status: str | None = None) -> list[dict]:
    q = "SELECT * FROM titles"
    args: tuple = ()
    if status:
        q += " WHERE status=?"
        args = (status,)
    q += " ORDER BY downloaded_at DESC, id DESC"
    with _connect() as conn:
        return [dict(r) for r in conn.execute(q, args)]


def keep_title(tid: int) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE titles SET status='kept', expires_at=NULL WHERE id=? AND status='new'",
            (tid,),
        )
        return cur.rowcount > 0


def purge_title(tid: int) -> bool:
    """Delete files from disk and tombstone the row."""
    for p in (cbz_path(tid), cover_path(tid)):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE titles SET status='deleted', expires_at=NULL, file_size=NULL"
            " WHERE id=? AND status != 'deleted'",
            (tid,),
        )
        return cur.rowcount > 0


def expired_ids() -> list[int]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id FROM titles WHERE status='new' AND expires_at < ?",
            (now_iso(),),
        )
        return [r["id"] for r in rows]


def log_scrape(found: int, downloaded: int, error: str | None = None):
    with _connect() as conn:
        conn.execute(
            "INSERT INTO scrape_log (run_at, found, downloaded, error) VALUES (?,?,?,?)",
            (now_iso(), found, downloaded, error),
        )


def last_scrape() -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM scrape_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def stats() -> dict:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS count, COALESCE(SUM(file_size),0) AS size"
            " FROM titles GROUP BY status"
        )
        out = {s: {"count": 0, "size": 0} for s in ("new", "kept", "deleted")}
        for r in rows:
            out[r["status"]] = {"count": r["count"], "size": r["size"]}
        return out
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 -m pytest ink-reader/tests/test_db.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add ink-reader/
git commit -m "feat(ink-reader): scaffold stack with config and SQLite catalog"
```

---

### Task 2: CBZ builder

**Files:**
- Create: `ink-reader/cbz.py`
- Test: `ink-reader/tests/test_cbz.py`

**Interfaces:**
- Consumes: nothing (pure functions, paths passed in)
- Produces:
  - `cbz.build_cbz(images: list[tuple[str, bytes]], cbz_dest: str, cover_dest: str) -> tuple[int, int]` — `images` is an ordered list of `(ext, data)` like `(".jpg", b"...")`; returns `(pages, file_size)`; raises `ValueError` on empty list. Writes `cbz_dest + ".part"` then `os.replace` (no half files). Cover = first image's bytes.

**Note:** the plan originally included a `normalize_zip_to_cbz` for a site-provided zip download. Live verification against doujin-th.com (2026-07-06) found the site has no server-side zip/download endpoint at all — only client-side PDF generation from images already on the page — so that function has no caller anywhere in this plan and is dropped (YAGNI).

- [ ] **Step 1: Write the failing tests**

`ink-reader/tests/test_cbz.py`:
```python
import os
import zipfile

import pytest

import cbz


def test_build_cbz(tmp_path):
    dest = str(tmp_path / "out.cbz")
    cover = str(tmp_path / "cover.jpg")
    pages, size = cbz.build_cbz(
        [(".jpg", b"one"), (".png", b"two")], dest, cover
    )
    assert pages == 2
    assert size == os.path.getsize(dest)
    with zipfile.ZipFile(dest) as zf:
        assert zf.namelist() == ["001.jpg", "002.png"]
    assert open(cover, "rb").read() == b"one"
    assert not os.path.exists(dest + ".part")


def test_build_cbz_empty_raises(tmp_path):
    with pytest.raises(ValueError):
        cbz.build_cbz([], str(tmp_path / "o.cbz"), str(tmp_path / "c.jpg"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest ink-reader/tests/test_cbz.py -v`
Expected: FAIL — `cbz` module missing.

- [ ] **Step 3: Implement cbz.py**

```python
import os
import zipfile


def build_cbz(images: list[tuple[str, bytes]], cbz_dest: str, cover_dest: str) -> tuple[int, int]:
    if not images:
        raise ValueError("no images")
    part = cbz_dest + ".part"
    with zipfile.ZipFile(part, "w", zipfile.ZIP_STORED) as out:
        for i, (ext, data) in enumerate(images, 1):
            out.writestr(f"{i:03d}{ext}", data)
    os.replace(part, cbz_dest)
    with open(cover_dest, "wb") as f:
        f.write(images[0][1])
    return len(images), os.path.getsize(cbz_dest)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest ink-reader/tests/test_cbz.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add ink-reader/cbz.py ink-reader/tests/test_cbz.py
git commit -m "feat(ink-reader): CBZ builder"
```

---

### Task 3: Scraper parsers (real doujin-th.com selectors, verified live 2026-07-06)

**Files:**
- Create: `ink-reader/scraper.py` (parsers + fetch only; cycle comes in Task 4)
- Create: `ink-reader/tests/fixtures/listing.html`
- Create: `ink-reader/tests/fixtures/title.html`
- Test: `ink-reader/tests/test_scraper.py`

**Interfaces:**
- Consumes: `config.SITE_BASE_URL`, `config.USER_AGENT`
- Produces:
  - `scraper.fetch_bytes(url: str, referer: str | None = None) -> bytes` (httpx GET, browser UA, follow redirects, `raise_for_status`; sets `Referer` header when given — doujin-th.com's image CDN 403s without it)
  - `scraper.parse_listing(html: str, base_url: str) -> list[dict]` — `[{"slug", "title", "url"}]`, newest first, deduped
  - `scraper.parse_title_page(html: str, base_url: str) -> dict` — `{"tags": list[str], "image_urls": list[str]}` (no `download_url` — the site has no server-side download; see Task 4 note)

**Ground truth (verified live via `ssh nas "curl ..."` against the real site, 2026-07-06):** doujin-th.com is an SMF forum. Homepage `/` IS the listing — "new release" entries are `<a class="hentai-item">` / `<a class="doujin-item">` with `href="//doujin-th.com/forum/index.php?topic=NNNNN.0"` and a `title` attribute formatted `"ThaiTitle - OriginalTitle"`; slug = the numeric topic id. The same homepage also has unrelated recommendation links (`<a class="col-xs-6 ...">` with no `hentai-item`/`doujin-item` class) that must be excluded by the class selector, not just by container. Title pages have the Thai title in `h1.panel-title`, tags as `<a class="tag">tagname</a>` inside a "Tags:" line, and reader images as `<img class="img-responsive">` inside `div.col-xs-12.col-md-8` — some of those `<img>` are decorative UI assets (e.g. a grayscale-toggle icon) whose `src` contains `/image/other/` and must be filtered out. There is no download link/button in the HTML at all — the site's "Download" button is pure client-side JS that re-fetches the same on-page images and assembles a PDF in the browser (jsPDF), it is not a link the scraper can use.

- [ ] **Step 1: Create fixture HTML**

`ink-reader/tests/fixtures/listing.html`:
```html
<!DOCTYPE html>
<html><body>
<div class="row layer_grid">
<style type="text/css">
#post_doujin_0 { background-image:url('https://cdn.example/covers/aaa-001.jpg'); }
</style>
<a href="//doujin-th.example/forum/index.php?topic=111.0" target="_blank" class="hentai-item" title="เรื่องหนึ่ง - Original Title One">
  <div class="topic_new_mark"><span class="label label-danger">มาใหม่ !!</span></div>
  <div id="post_doujin_0">
    <div class="topic_new_name"><div class="well well-sm">เรื่องหนึ่ง</div></div>
  </div>
</a>
<style type="text/css">
#post_doujin_1 { background-image:url('https://cdn.example/covers/bbb-001.jpg'); }
</style>
<a href="//doujin-th.example/forum/index.php?topic=112.0" target="_blank" class="doujin-item" title="เรื่องสอง - Original Title Two">
  <div class="topic_new_name"><div class="well well-sm">เรื่องสอง</div></div>
</a>
<a href="//doujin-th.example/forum/index.php?topic=111.0" target="_blank" class="hentai-item" title="เรื่องหนึ่ง - Original Title One">
  <div class="topic_new_name"><div class="well well-sm">เรื่องหนึ่ง (duplicate link)</div></div>
</a>
<a href="//doujin-th.example/forum/index.php?topic=999.0" target="_blank" class="col-xs-6 col-sm-4 col-md-3 col-lg-2">
  <div class="topic_new_name"><div class="well well-sm">Unrelated recommendation</div></div>
</a>
</div>
</body></html>
```

`ink-reader/tests/fixtures/title.html`:
```html
<!DOCTYPE html>
<html><body>
<div class="col-xs-12 col-md-8">
  <h1 class="panel-title">เรื่องหนึ่ง</h1>
  <h2 class="panel-title">Original Title One</h2>
  <p>Tags: <span class="label label-danger">มาใหม่ !!</span>
    <span class="label label-info"><a class="tag" href="https://doujin-th.example/forum/index.php?action=tags&amp;tagid=1">tag-a</a></span>
    <span class="label label-info"><a class="tag" href="https://doujin-th.example/forum/index.php?action=tags&amp;tagid=2">tag-b</a></span>
  </p>
  <img class="img-responsive" src="https://cdn.example/pages/111-001.jpg">
  <img class="img-responsive" src="https://cdn.example/pages/111-002.jpg">
  <img class="img-responsive" src="https://cdn.example/image/other/change-to-bw.jpg">
</div>
</body></html>
```

- [ ] **Step 2: Write the failing tests**

`ink-reader/tests/test_scraper.py`:
```python
import os

import scraper

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _read(name):
    return open(os.path.join(FIXTURES, name), encoding="utf-8").read()


def test_parse_listing():
    items = scraper.parse_listing(_read("listing.html"), "https://doujin-th.example")
    assert [i["slug"] for i in items] == ["111", "112"]
    assert items[0]["title"] == "เรื่องหนึ่ง"
    assert items[0]["url"] == "https://doujin-th.example/forum/index.php?topic=111.0"
    assert items[1]["title"] == "เรื่องสอง"


def test_parse_listing_ignores_links_without_item_class():
    items = scraper.parse_listing(_read("listing.html"), "https://doujin-th.example")
    assert "999" not in {i["slug"] for i in items}


def test_parse_title_page():
    meta = scraper.parse_title_page(_read("title.html"), "https://doujin-th.example")
    assert meta["tags"] == ["tag-a", "tag-b"]
    assert meta["image_urls"] == [
        "https://cdn.example/pages/111-001.jpg",
        "https://cdn.example/pages/111-002.jpg",
    ]


def test_parse_title_page_filters_decorative_images():
    meta = scraper.parse_title_page(_read("title.html"), "https://doujin-th.example")
    assert not any("/image/other/" in u for u in meta["image_urls"])
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m pytest ink-reader/tests/test_scraper.py -v`
Expected: FAIL — `scraper` module missing.

- [ ] **Step 4: Implement scraper.py (parsers + fetch)**

```python
"""doujin-th.com scraper.

Site is SMF-forum-based (verified live via NAS, 2026-07-06). There is no
server-side zip/download endpoint — the page's "Download" button only builds
a PDF client-side in the browser from the reader images already in the page.
The scraper's only path is scraping those reader-page image URLs directly
(see scrape_cycle in this file, added in Task 4). Reader images are
hotlink-protected by the CDN: a direct GET returns 403 unless a `Referer`
header pointing at the title page is sent.
"""

import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

import config

HEADERS = {"User-Agent": config.USER_AGENT}

_TOPIC_RE = re.compile(r"topic=(\d+)")


def fetch_bytes(url: str, referer: str | None = None) -> bytes:
    headers = dict(HEADERS)
    if referer:
        headers["Referer"] = referer
    with httpx.Client(headers=headers, follow_redirects=True, timeout=60) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.content


def parse_listing(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    items, seen = [], set()
    for a in soup.select("a.hentai-item[href], a.doujin-item[href]"):
        url = urljoin(base_url, a["href"])
        m = _TOPIC_RE.search(url)
        if not m:
            continue
        slug = m.group(1)
        if slug in seen:
            continue
        title_attr = a.get("title", "")
        title = title_attr.split(" - ", 1)[0].strip() if title_attr else a.get_text(strip=True)
        if not title:
            continue
        seen.add(slug)
        items.append({"slug": slug, "title": title, "url": url})
    return items


def parse_title_page(html: str, base_url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    tags = [a.get_text(strip=True) for a in soup.select("a.tag")]
    container = soup.select_one("div.col-xs-12.col-md-8") or soup
    image_urls = [
        urljoin(base_url, img["src"])
        for img in container.select("img.img-responsive[src]")
        if "/image/other/" not in img["src"]
    ]
    return {"tags": tags, "image_urls": image_urls}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest ink-reader/tests/test_scraper.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add ink-reader/scraper.py ink-reader/tests/
git commit -m "feat(ink-reader): listing and title-page parsers with real doujin-th.com selectors"
```

---

### Task 4: Scrape cycle orchestration

**Files:**
- Modify: `ink-reader/scraper.py` (append `scrape_cycle`)
- Test: `ink-reader/tests/test_cycle.py`

**Interfaces:**
- Consumes: `db.known_slugs/add_title/log_scrape`, `cbz.build_cbz`, parsers from Task 3, `config.MAX_NEW_PER_CYCLE`, `config.REQUEST_DELAY_SECONDS`
- Produces:
  - `scraper.scrape_cycle(fetch=fetch_bytes) -> dict` — `{"found": int, "downloaded": int, "errors": list[str]}`. `fetch` injectable for tests, called as `fetch(url)` for HTML pages and `fetch(url, referer=item["url"])` for reader images (the CDN 403s without it — see Task 3). Always writes a `scrape_log` row (error text = joined errors or None). Per-title failures are skipped, never abort the cycle. Files are written to a temp path first; DB row inserted only after the CBZ exists, then files renamed to `{id}.cbz` / `{id}.jpg` — a failed title leaves no row, so it retries next cycle.

**Note:** doujin-th.com has no server-side zip/download (see Task 3) — there is a single download path here, scraping the reader-page images, not a zip-then-fallback branch.

- [ ] **Step 1: Write the failing tests**

`ink-reader/tests/test_cycle.py`:
```python
import os

import db
import scraper

LISTING = """
<a class="hentai-item" href="/forum/index.php?topic=1.0" title="Story A - A">Story A</a>
<a class="doujin-item" href="/forum/index.php?topic=2.0" title="Story B - B">Story B</a>
"""
TITLE = """
<div class="col-xs-12 col-md-8">
<h1 class="panel-title">{title}</h1>
<p>Tags: <span class="label label-info"><a class="tag" href="#">x</a></span></p>
<img class="img-responsive" src="/i/{slug}/1.jpg">
<img class="img-responsive" src="/i/{slug}/2.jpg">
</div>
"""


def _fake_fetch(pages):
    def fetch(url, referer=None):
        for key, val in pages.items():
            if key in url:
                return val() if callable(val) else val
        raise RuntimeError(f"unexpected url {url}")
    return fetch


def test_cycle_downloads_new_titles(data_dir):
    fetch = _fake_fetch({
        "topic=1.0": TITLE.format(title="Story A", slug="1").encode(),
        "topic=2.0": TITLE.format(title="Story B", slug="2").encode(),
        "/i/": b"imgdata",
        "doujin-th": LISTING.encode(),
    })
    result = scraper.scrape_cycle(fetch=fetch)
    assert result["downloaded"] == 2
    rows = db.list_titles()
    assert {r["slug"] for r in rows} == {"1", "2"}
    for r in rows:
        assert r["pages"] == 2
        assert os.path.exists(db.cbz_path(r["id"]))
        assert os.path.exists(db.cover_path(r["id"]))
    assert db.last_scrape()["downloaded"] == 2


def test_cycle_skips_known_and_tombstones(data_dir):
    tid = db.add_title("1", "A", "", 1, 1, "u")
    db.purge_title(tid)  # tombstone
    fetch = _fake_fetch({
        "topic=2.0": TITLE.format(title="Story B", slug="2").encode(),
        "/i/": b"imgdata",
        "doujin-th": LISTING.encode(),
    })
    result = scraper.scrape_cycle(fetch=fetch)
    assert result["downloaded"] == 1
    assert {r["slug"] for r in db.list_titles(status="new")} == {"2"}


def test_cycle_title_failure_skips_and_logs(data_dir):
    def fetch(url, referer=None):
        if "doujin-th" in url:
            return LISTING.encode()
        if "topic=1.0" in url:
            raise RuntimeError("boom")
        if "topic=2.0" in url:
            return TITLE.format(title="Story B", slug="2").encode()
        if "/i/" in url:
            return b"imgdata"
        raise RuntimeError(f"unexpected {url}")

    result = scraper.scrape_cycle(fetch=fetch)
    assert result["downloaded"] == 1
    assert len(result["errors"]) == 1
    assert "1" in result["errors"][0]
    assert db.last_scrape()["error"] is not None
    # story 1 left no row → retried next cycle
    assert "1" not in db.known_slugs()


def test_cycle_respects_max_per_cycle(data_dir, monkeypatch):
    import config
    monkeypatch.setattr(config, "MAX_NEW_PER_CYCLE", 1)
    fetch = _fake_fetch({
        "topic=1.0": TITLE.format(title="Story A", slug="1").encode(),
        "/i/": b"imgdata",
        "doujin-th": LISTING.encode(),
    })
    result = scraper.scrape_cycle(fetch=fetch)
    assert result["downloaded"] == 1
    assert result["found"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest ink-reader/tests/test_cycle.py -v`
Expected: FAIL — `scrape_cycle` not defined.

- [ ] **Step 3: Implement scrape_cycle (append to scraper.py)**

```python
import os
import time
import uuid

import cbz
import db


def _download_title(item: dict, meta: dict, fetch) -> None:
    """Build CBZ in temp location, then insert DB row and move files into place."""
    tmp_cbz = os.path.join(config.LIBRARY_DIR, f".tmp-{uuid.uuid4().hex}.cbz")
    tmp_cover = tmp_cbz + ".cover.jpg"
    try:
        if not meta["image_urls"]:
            raise ValueError("no reader images found")
        images = [
            (os.path.splitext(u.split("?")[0])[1].lower() or ".jpg", fetch(u, referer=item["url"]))
            for u in meta["image_urls"]
        ]
        pages, size = cbz.build_cbz(images, tmp_cbz, tmp_cover)
        tid = db.add_title(
            slug=item["slug"], title=item["title"], tags=",".join(meta["tags"]),
            pages=pages, file_size=size, source_url=item["url"],
        )
        os.replace(tmp_cbz, db.cbz_path(tid))
        os.replace(tmp_cover, db.cover_path(tid))
    finally:
        for p in (tmp_cbz, tmp_cbz + ".part", tmp_cover):
            if os.path.exists(p):
                os.remove(p)


def scrape_cycle(fetch=fetch_bytes) -> dict:
    errors: list[str] = []
    downloaded = 0
    found = 0
    try:
        listing_html = fetch(config.SITE_BASE_URL + "/").decode("utf-8", "replace")
        items = parse_listing(listing_html, config.SITE_BASE_URL)
        known = db.known_slugs()
        fresh = [i for i in items if i["slug"] not in known]
        found = len(fresh)
        for item in fresh[: config.MAX_NEW_PER_CYCLE]:
            try:
                html = fetch(item["url"]).decode("utf-8", "replace")
                meta = parse_title_page(html, config.SITE_BASE_URL)
                _download_title(item, meta, fetch)
                downloaded += 1
            except Exception as e:
                errors.append(f"{item['slug']}: {e}")
            time.sleep(config.REQUEST_DELAY_SECONDS)
    except Exception as e:
        errors.append(f"listing: {e}")
    db.log_scrape(found, downloaded, "; ".join(errors) or None)
    return {"found": found, "downloaded": downloaded, "errors": errors}
```

Also set `REQUEST_DELAY_SECONDS` to 0 in tests — add to `data_dir` fixture in `ink-reader/tests/conftest.py`:
```python
    monkeypatch.setattr(config, "REQUEST_DELAY_SECONDS", 0)
```

- [ ] **Step 4: Run all tests**

Run: `python3 -m pytest ink-reader/tests -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add ink-reader/scraper.py ink-reader/tests/
git commit -m "feat(ink-reader): scrape cycle with tombstone dedup"
```

---

### Task 5: OPDS feed

**Files:**
- Create: `ink-reader/opds.py`
- Test: `ink-reader/tests/test_opds.py`

**Interfaces:**
- Consumes: `db.list_titles`, `db.now_iso`
- Produces:
  - `opds.root_feed() -> bytes` — Atom navigation feed with two subsection links: `/opds/new` ("ใหม่ล่าสุด"), `/opds/kept` ("ที่เก็บไว้")
  - `opds.titles_feed(status: str) -> bytes` — Atom acquisition feed; per entry: title, updated, acquisition link `href=/files/{id}.cbz` `type=application/vnd.comicbook+zip`, cover link `href=/covers/{id}.jpg`
  - Content-type used by the API layer: `application/atom+xml`

- [ ] **Step 1: Write the failing tests**

`ink-reader/tests/test_opds.py`:
```python
import xml.etree.ElementTree as ET

import db
import opds

ATOM = "{http://www.w3.org/2005/Atom}"


def test_root_feed(data_dir):
    root = ET.fromstring(opds.root_feed())
    hrefs = [l.get("href") for e in root.findall(f"{ATOM}entry")
             for l in e.findall(f"{ATOM}link")]
    assert hrefs == ["/opds/new", "/opds/kept"]


def test_titles_feed(data_dir):
    tid = db.add_title("s1", "Story One", "a,b", 20, 1000, "u")
    root = ET.fromstring(opds.titles_feed("new"))
    entries = root.findall(f"{ATOM}entry")
    assert len(entries) == 1
    links = {l.get("rel"): l for l in entries[0].findall(f"{ATOM}link")}
    acq = links["http://opds-spec.org/acquisition"]
    assert acq.get("href") == f"/files/{tid}.cbz"
    assert acq.get("type") == "application/vnd.comicbook+zip"
    assert links["http://opds-spec.org/image"].get("href") == f"/covers/{tid}.jpg"


def test_titles_feed_filters_status(data_dir):
    db.add_title("s1", "One", "", 1, 1, "u")
    root = ET.fromstring(opds.titles_feed("kept"))
    assert root.findall(f"{ATOM}entry") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest ink-reader/tests/test_opds.py -v`
Expected: FAIL — `opds` missing.

- [ ] **Step 3: Implement opds.py**

```python
from xml.etree.ElementTree import Element, SubElement, tostring

import db

ATOM = "http://www.w3.org/2005/Atom"
ACQ_TYPE = "application/atom+xml;profile=opds-catalog;kind=acquisition"


def _feed(feed_id: str, title: str) -> Element:
    feed = Element("feed", xmlns=ATOM)
    SubElement(feed, "id").text = feed_id
    SubElement(feed, "title").text = title
    SubElement(feed, "updated").text = db.now_iso()
    return feed


def _entry(feed: Element, entry_id: str, title: str, updated: str) -> Element:
    entry = SubElement(feed, "entry")
    SubElement(entry, "id").text = entry_id
    SubElement(entry, "title").text = title
    SubElement(entry, "updated").text = updated
    return entry


def root_feed() -> bytes:
    feed = _feed("ink-reader:root", "ink-reader")
    for path, name in (("/opds/new", "ใหม่ล่าสุด"), ("/opds/kept", "ที่เก็บไว้")):
        entry = _entry(feed, f"ink-reader:{path}", name, db.now_iso())
        SubElement(entry, "link", rel="subsection", href=path, type=ACQ_TYPE)
    return tostring(feed, encoding="utf-8", xml_declaration=True)


def titles_feed(status: str) -> bytes:
    names = {"new": "ใหม่ล่าสุด", "kept": "ที่เก็บไว้"}
    feed = _feed(f"ink-reader:{status}", names.get(status, status))
    for row in db.list_titles(status=status):
        entry = _entry(feed, f"ink-reader:title:{row['id']}", row["title"],
                       row["downloaded_at"])
        SubElement(entry, "link", rel="http://opds-spec.org/acquisition",
                   href=f"/files/{row['id']}.cbz",
                   type="application/vnd.comicbook+zip")
        SubElement(entry, "link", rel="http://opds-spec.org/image",
                   href=f"/covers/{row['id']}.jpg", type="image/jpeg")
    return tostring(feed, encoding="utf-8", xml_declaration=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest ink-reader/tests/test_opds.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add ink-reader/opds.py ink-reader/tests/test_opds.py
git commit -m "feat(ink-reader): OPDS navigation and acquisition feeds"
```

---

### Task 6: Scheduler (scrape + expiry + backup)

**Files:**
- Create: `ink-reader/scheduler.py`
- Create: `ink-reader/sqlite_backup.py` (verbatim copy of `torrentwatch/sqlite_backup.py`)
- Test: `ink-reader/tests/test_scheduler.py`

**Interfaces:**
- Consumes: `scraper.scrape_cycle`, `db.expired_ids/purge_title/log_scrape`, `sqlite_backup.backup_db`, `config.SCRAPE_INTERVAL_HOURS/BACKUP_DIR/DB_PATH/TZ`
- Produces:
  - `scheduler.start()` — BackgroundScheduler with 3 jobs: scrape every `SCRAPE_INTERVAL_HOURS` hours, `expiry_job` daily 04:00, `backup_job` daily 03:00
  - `scheduler.shutdown()`
  - `scheduler.scrape_job()`, `scheduler.expiry_job() -> int`, `scheduler.backup_job()` (callable directly; `expiry_job` returns purge count)

- [ ] **Step 1: Copy sqlite_backup.py**

```bash
cp torrentwatch/sqlite_backup.py ink-reader/sqlite_backup.py
```

- [ ] **Step 2: Write the failing test**

`ink-reader/tests/test_scheduler.py`:
```python
import os

import db
import scheduler


def test_expiry_job_purges_expired(data_dir):
    tid = db.add_title("old", "Old", "", 1, 1, "u")
    open(db.cbz_path(tid), "wb").write(b"x")
    with db._connect() as conn:
        conn.execute(
            "UPDATE titles SET expires_at='2000-01-01T00:00:00+07:00' WHERE id=?",
            (tid,),
        )
    fresh = db.add_title("fresh", "Fresh", "", 1, 1, "u")

    assert scheduler.expiry_job() == 1
    assert db.get_title(tid)["status"] == "deleted"
    assert not os.path.exists(db.cbz_path(tid))
    assert db.get_title(fresh)["status"] == "new"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python3 -m pytest ink-reader/tests/test_scheduler.py -v`
Expected: FAIL — `scheduler` missing.

- [ ] **Step 4: Implement scheduler.py**

```python
from apscheduler.schedulers.background import BackgroundScheduler

import config
import db
import scraper
from sqlite_backup import backup_db

_sched = BackgroundScheduler(timezone=config.TZ)


def scrape_job():
    try:
        result = scraper.scrape_cycle()
        print(f"[scrape] {result}", flush=True)
    except Exception as e:  # scrape_cycle already logs; belt & braces
        print(f"[scrape] crashed: {e}", flush=True)
        db.log_scrape(0, 0, str(e))


def expiry_job() -> int:
    count = 0
    for tid in db.expired_ids():
        if db.purge_title(tid):
            count += 1
    print(f"[expiry] purged {count}", flush=True)
    return count


def backup_job():
    backup_db(config.DB_PATH, config.BACKUP_DIR, prefix="ink")


def start():
    _sched.add_job(scrape_job, "interval", hours=config.SCRAPE_INTERVAL_HOURS,
                   id="scrape")
    _sched.add_job(expiry_job, "cron", hour=4, minute=0, id="expiry")
    _sched.add_job(backup_job, "cron", hour=3, minute=0, id="backup")
    _sched.start()


def shutdown():
    if _sched.running:
        _sched.shutdown(wait=False)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest ink-reader/tests/test_scheduler.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add ink-reader/scheduler.py ink-reader/sqlite_backup.py ink-reader/tests/test_scheduler.py
git commit -m "feat(ink-reader): scheduler with scrape, expiry, and backup jobs"
```

---

### Task 7: FastAPI app (API + files + OPDS routes)

**Files:**
- Create: `ink-reader/main.py`
- Test: `ink-reader/tests/test_api.py`

**Interfaces:**
- Consumes: everything above
- Produces (HTTP, all unauthenticated in-app — nginx sidecar owns auth):
  - `GET /` → `static/index.html`
  - `GET /api/titles?status=` → `{"titles": [...]}` (each row includes `id, slug, title, tags, pages, file_size, status, downloaded_at, expires_at`)
  - `POST /api/titles/{tid}/keep` → 200 `{"ok": true}` / 404
  - `POST /api/titles/{tid}/delete` → 200 `{"ok": true}` / 404
  - `POST /api/scrape` → runs `scraper.scrape_cycle` in a background thread, returns `{"started": true}` immediately
  - `GET /api/status` → `{"stats": ..., "last_scrape": ...}`
  - `GET /files/{tid}.cbz` → FileResponse `application/vnd.comicbook+zip`, download filename `"{title}.cbz"` / 404
  - `GET /covers/{tid}.jpg` → FileResponse `image/jpeg` / 404
  - `GET /opds`, `GET /opds/new`, `GET /opds/kept` → `application/atom+xml`
  - Env guard `INK_DISABLE_SCHEDULER=1` skips scheduler start (used by tests)

- [ ] **Step 1: Write the failing tests**

`ink-reader/tests/test_api.py`:
```python
import os

import pytest
from fastapi.testclient import TestClient

import db


@pytest.fixture
def client(data_dir, monkeypatch):
    monkeypatch.setenv("INK_DISABLE_SCHEDULER", "1")
    import main
    with TestClient(main.app) as c:
        yield c


def _seed():
    tid = db.add_title("s1", "Story One", "a,b", 2, 100, "u")
    open(db.cbz_path(tid), "wb").write(b"cbzdata")
    open(db.cover_path(tid), "wb").write(b"jpgdata")
    return tid


def test_titles_list(client):
    _seed()
    r = client.get("/api/titles", params={"status": "new"})
    assert r.status_code == 200
    assert r.json()["titles"][0]["slug"] == "s1"


def test_keep_and_delete(client):
    tid = _seed()
    assert client.post(f"/api/titles/{tid}/keep").json() == {"ok": True}
    assert db.get_title(tid)["status"] == "kept"
    assert client.post(f"/api/titles/{tid}/delete").json() == {"ok": True}
    assert db.get_title(tid)["status"] == "deleted"
    assert not os.path.exists(db.cbz_path(tid))
    assert client.post("/api/titles/999/keep").status_code == 404


def test_file_and_cover(client):
    tid = _seed()
    r = client.get(f"/files/{tid}.cbz")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/vnd.comicbook+zip"
    assert r.content == b"cbzdata"
    assert client.get(f"/covers/{tid}.jpg").content == b"jpgdata"
    assert client.get("/files/999.cbz").status_code == 404


def test_opds_routes(client):
    _seed()
    for path in ("/opds", "/opds/new", "/opds/kept"):
        r = client.get(path)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/atom+xml")
    assert b"s1" not in client.get("/opds/kept").content


def test_status(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    assert "stats" in r.json()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest ink-reader/tests/test_api.py -v`
Expected: FAIL — `main` missing.

- [ ] **Step 3: Implement main.py**

```python
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
```

Note: `GET /` will 404 until Task 8 adds `static/index.html`; the API tests don't touch `/`.

- [ ] **Step 4: Run all tests**

Run: `python3 -m pytest ink-reader/tests -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add ink-reader/main.py ink-reader/tests/test_api.py
git commit -m "feat(ink-reader): FastAPI app with API, file serving, and OPDS routes"
```

---

### Task 8: Dashboard

**Files:**
- Create: `ink-reader/static/index.html`

**Interfaces:**
- Consumes: `/api/titles`, `/api/titles/{id}/keep`, `/api/titles/{id}/delete`, `/api/scrape`, `/api/status`, `/covers/{id}.jpg`
- Produces: single-file mobile-friendly dashboard (vanilla JS, no build step, Thai UI)

- [ ] **Step 1: Create static/index.html**

```html
<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ink-reader</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; background: #14151a; color: #e8e8ea;
         font-family: system-ui, sans-serif; }
  header { display: flex; gap: .5rem; align-items: center; padding: .75rem 1rem;
           position: sticky; top: 0; background: #1c1d24; flex-wrap: wrap; }
  header h1 { font-size: 1.1rem; margin: 0 auto 0 0; }
  #stats { width: 100%; font-size: .8rem; color: #9a9aa4; }
  button, .tab { border: 0; border-radius: 8px; padding: .5rem .9rem;
                 background: #2a2b34; color: #e8e8ea; font-size: .9rem; }
  .tab.active { background: #4f6ef7; }
  #grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
          gap: .75rem; padding: .75rem; }
  .card { background: #1c1d24; border-radius: 10px; overflow: hidden;
          display: flex; flex-direction: column; }
  .card img { width: 100%; aspect-ratio: 3/4; object-fit: cover; background: #000; }
  .card .body { padding: .5rem; display: flex; flex-direction: column; gap: .3rem;
                flex: 1; }
  .card .title { font-size: .85rem; line-height: 1.25; word-break: break-word; }
  .card .meta { font-size: .72rem; color: #9a9aa4; }
  .card .exp { font-size: .72rem; color: #f7b84f; }
  .card .kept-badge { font-size: .72rem; color: #6fe08a; }
  .actions { display: flex; gap: .4rem; margin-top: auto; }
  .actions button { flex: 1; padding: .45rem 0; font-size: 1rem; }
  .keep { background: #24402b; }
  .del { background: #40242a; }
</style>
</head>
<body>
<header>
  <h1>📚 ink-reader</h1>
  <button class="tab active" data-f="">ทั้งหมด</button>
  <button class="tab" data-f="new">ใหม่</button>
  <button class="tab" data-f="kept">เก็บแล้ว</button>
  <button id="scrape">🔄 Scrape</button>
  <div id="stats"></div>
</header>
<div id="grid"></div>
<script>
let filter = "";

function fmtSize(b) {
  if (!b) return "";
  return b > 1048576 ? (b / 1048576).toFixed(1) + " MB" : (b / 1024 | 0) + " KB";
}

function daysLeft(iso) {
  if (!iso) return null;
  return Math.max(0, Math.ceil((new Date(iso) - Date.now()) / 86400000));
}

async function loadStats() {
  const s = (await (await fetch("/api/status")).json());
  const st = s.stats;
  const last = s.last_scrape;
  document.getElementById("stats").textContent =
    `ใหม่ ${st.new.count} (${fmtSize(st.new.size)}) · เก็บ ${st.kept.count} ` +
    `(${fmtSize(st.kept.size)})` +
    (last ? ` · scrape ล่าสุด ${last.run_at}${last.error ? " ⚠️ " + last.error : ""}` : "");
}

async function load() {
  const q = filter ? "?status=" + filter : "";
  const data = await (await fetch("/api/titles" + q)).json();
  const grid = document.getElementById("grid");
  grid.innerHTML = "";
  for (const t of data.titles) {
    if (t.status === "deleted") continue;
    const card = document.createElement("div");
    card.className = "card";
    const dl = daysLeft(t.expires_at);
    card.innerHTML = `
      <img src="/covers/${t.id}.jpg" loading="lazy" alt="">
      <div class="body">
        <div class="title">${t.title}</div>
        <div class="meta">${t.pages} หน้า · ${fmtSize(t.file_size)}</div>
        ${t.status === "kept"
          ? `<div class="kept-badge">❤️ เก็บถาวร</div>`
          : `<div class="exp">⏳ เหลือ ${dl} วัน</div>`}
        <div class="actions">
          ${t.status === "new" ? `<button class="keep" data-a="keep" data-id="${t.id}">❤️</button>` : ""}
          <button class="del" data-a="delete" data-id="${t.id}">🗑</button>
        </div>
      </div>`;
    grid.appendChild(card);
  }
  loadStats();
}

document.getElementById("grid").addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-a]");
  if (!btn) return;
  if (btn.dataset.a === "delete" && !confirm("ลบเรื่องนี้ทิ้งถาวร?")) return;
  await fetch(`/api/titles/${btn.dataset.id}/${btn.dataset.a}`, { method: "POST" });
  load();
});

document.querySelectorAll(".tab").forEach((b) =>
  b.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    filter = b.dataset.f;
    load();
  })
);

document.getElementById("scrape").addEventListener("click", async () => {
  await fetch("/api/scrape", { method: "POST" });
  alert("เริ่ม scrape แล้ว รอสักครู่แล้วรีเฟรช");
});

load();
</script>
</body>
</html>
```

- [ ] **Step 2: Smoke-verify locally**

```bash
cd ink-reader && INK_DISABLE_SCHEDULER=1 DATA_DIR=/tmp/ink-test python3 -m uvicorn main:app --port 8001 &
sleep 2
curl -s http://localhost:8001/ | grep -q "ink-reader" && echo DASHBOARD-OK
curl -s http://localhost:8001/opds | grep -q "opds" && echo OPDS-OK
kill %1
```
Expected: `DASHBOARD-OK` and `OPDS-OK`.

- [ ] **Step 3: Commit**

```bash
git add ink-reader/static/index.html
git commit -m "feat(ink-reader): curation dashboard"
```

---

### Task 9: Docker, nginx, secrets, docs, deploy + live verify

**Files:**
- Create: `ink-reader/Dockerfile`
- Create: `ink-reader/docker-compose.yml`
- Create: `ink-reader/nginx/nginx.conf`
- Create: `ink-reader/nginx/.htpasswd` (generated, gitignored)
- Create: `ink-reader/secrets.manifest.yaml`
- Create: `ink-reader/README.md`
- Create: `ink-reader/.notes/00_INDEX.md`, `ink-reader/.notes/daily_log.md`
- Modify: `CLAUDE.md` (stacks table), root `README.md` (stack list)
- Modify: `.gitignore` only if `*/nginx/.htpasswd` is not already covered (check first: `git check-ignore ink-reader/nginx/.htpasswd` after creating it)

**Interfaces:**
- Consumes: the whole app
- Produces: deployable stack on NAS at port 5068

- [ ] **Step 1: Create Dockerfile** (same shape as torrentwatch)

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Create docker-compose.yml**

```yaml
services:
  ink-reader:
    build: .
    container_name: ink-reader
    restart: unless-stopped
    expose:
      - "8000"
    env_file: .env
    environment:
      - TZ=Asia/Bangkok
      - DATA_DIR=/data
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/status', timeout=5)"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
    volumes:
      - ink_reader_data:/data

  nginx:
    image: nginx:alpine
    container_name: ink-reader-nginx
    restart: unless-stopped
    ports:
      - "5068:80"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - ./nginx/.htpasswd:/etc/nginx/.htpasswd:ro
    environment:
      - TZ=Asia/Bangkok
    depends_on:
      - ink-reader

volumes:
  ink_reader_data:
```

- [ ] **Step 3: Create nginx/nginx.conf**

```nginx
server {
    listen 80;

    location / {
        auth_basic           "Restricted";
        auth_basic_user_file /etc/nginx/.htpasswd;

        proxy_pass          http://ink-reader:8000;
        proxy_http_version  1.1;
        proxy_set_header    Host              $http_host;
        proxy_set_header    X-Real-IP         $remote_addr;
        proxy_set_header    X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header    X-Forwarded-Proto $scheme;
        proxy_buffering     off;
        proxy_read_timeout  300s;
    }
}
```

- [ ] **Step 4: Create secrets.manifest.yaml**

The app itself needs no secrets (auth lives in nginx), but the stack still needs a `.env` for deploy.sh's pre-upload check, and the vault stores the dashboard credentials for htpasswd generation:

```yaml
env: {}

literals:
  DATA_DIR: /data
```

- [ ] **Step 5: Add vault credentials + generate .htpasswd**

Use the `adding-vault-secret` skill flow:
1. `make edit-vault` → add under `stacks:`:
   ```yaml
   ink_reader:
     dashboard:
       username: <choose>
       password: <generate strong password>
   ```
2. `make secrets` (renders `ink-reader/.env` so deploy.sh passes its check)
3. Generate htpasswd from the vault values (do not echo the password into shell history; read from the decrypted vault):
   ```bash
   mkdir -p ink-reader/nginx
   USER=$(sops -d secrets/vault.sops.yaml | python3 -c "import sys,yaml; print(yaml.safe_load(sys.stdin)['stacks']['ink_reader']['dashboard']['username'])")
   PASS=$(sops -d secrets/vault.sops.yaml | python3 -c "import sys,yaml; print(yaml.safe_load(sys.stdin)['stacks']['ink_reader']['dashboard']['password'])")
   printf "%s:%s\n" "$USER" "$(openssl passwd -apr1 "$PASS")" > ink-reader/nginx/.htpasswd
   ```
4. Verify gitignore coverage: `git check-ignore ink-reader/nginx/.htpasswd` must print the path. If not, add `ink-reader/nginx/.htpasswd` to `.gitignore`.

- [ ] **Step 6: Write docs**

- `ink-reader/README.md`: purpose, architecture diagram (from spec), ports (5068/15068), env vars (`INK_*`), API + OPDS endpoints, KOReader setup steps (install APK → Search → OPDS catalog → add `http://<NAS_HOST>:5068/opds` + basic auth credentials), curation lifecycle.
- `ink-reader/.notes/00_INDEX.md`: DB schema, endpoints, settings, gaps (selector verification status).
- `ink-reader/.notes/daily_log.md`: first entry for the build.
- Root `CLAUDE.md`: add row to the stacks table:
  `| ink-reader/ | Doujin library + OPDS สำหรับ Meebook M8 | 5068 / 15068 | Scrape doujin-th.com → CBZ ใน /data/library. Lifecycle new(30วัน auto-expire)/kept/deleted(tombstone กันโหลดซ้ำ). KOReader ต่อ OPDS /opds ผ่าน nginx basic auth (vault: stacks.ink_reader.dashboard.*). Fallback สร้าง CBZ จากรูปหน้าอ่านถ้าลิงก์ download พัง |`
- Root `README.md`: add ink-reader to the stack list following the existing format.

- [ ] **Step 7: Run full test suite + commit**

```bash
python3 -m pytest ink-reader/tests -v
git add ink-reader/ CLAUDE.md README.md .gitignore
git commit -m "feat(ink-reader): docker stack, nginx auth sidecar, and docs"
```
Confirm `git status` shows no `.env` or `.htpasswd` staged.

- [ ] **Step 8: Deploy to NAS**

```bash
./scripts/deploy.sh
```
Then restart just this stack per repo convention (deploy.sh handles upload; compose up for ink-reader). Container build happens on NAS.

- [ ] **Step 9: Live confirmation on NAS**

Parser selectors were already verified against the real site before implementation (2026-07-06, via `ssh nas "curl ..."` — see Task 3's Ground Truth note), so this step is a confirmation, not a discovery session:

1. Trigger one live cycle against the deployed container: `curl -u <user>:<pass> -X POST http://<NAS_HOST>:5068/api/scrape`, wait, then `curl -u ... http://<NAS_HOST>:5068/api/status` and confirm `downloaded > 0` and no error.
2. If it fails (site changed again since verification, or a selector edge case the fixtures didn't cover), fetch fresh HTML via `ssh nas "curl -sL -A '<UA>' https://doujin-th.com/"`, diff against `tests/fixtures/listing.html`/`title.html`, adjust the parser + fixtures, `python3 -m pytest ink-reader/tests -v`, redeploy, retry step 1.
3. Commit any fixes: `git commit -m "fix(ink-reader): align parsers with live site structure"`.

- [ ] **Step 10: End-to-end acceptance**

1. Dashboard: open `http://<NAS_HOST>:5068/` on phone (basic auth prompt) → covers grid shows downloaded titles; press ❤️ on one → moves to เก็บแล้ว tab; press 🗑 on another → gone, and `/api/titles?status=deleted` shows the tombstone.
2. KOReader on M8: install KOReader APK → Catalogs → add OPDS `http://<NAS_HOST>:5068/opds` with the dashboard credentials → browse "ใหม่ล่าสุด" → download one CBZ → opens and reads.
3. DSM manual step (user): add reverse proxy 15068 → localhost:5068 (HTTPS) if outside-LAN dashboard access wanted.
4. Update `.notes/daily_log.md` + `.notes/00_INDEX.md` with verification results.

---

## Self-Review Notes

- Spec coverage: scraper (Tasks 3-4), lifecycle/tombstone (1, 4, 6), dashboard (8), OPDS (5), scheduler+backup (6), deploy/auth/docs (9), live verification (9). Out-of-scope items from spec remain out.
- Type consistency: `db.purge_title` used by API delete + expiry job; `scrape_cycle(fetch=...)` injectable everywhere; OPDS hrefs match `main.py` routes (`/files/{tid}.cbz`, `/covers/{tid}.jpg`).
- Parser selectors reflect real site structure verified live before implementation (Global Constraints, Task 3); Task 9 Step 9 is a deploy-time confirmation, not first discovery.
