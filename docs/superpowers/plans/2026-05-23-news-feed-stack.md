# news-feed Stack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `news-feed/` Docker Compose stack that fetches RSS from 7 sources, summarises articles in Thai via Claude or OpenRouter (switchable at runtime), sends digest to LINE + Telegram, and exposes a single-page dashboard.

**Architecture:** Single Python 3.12-slim container running FastAPI (HTTP + static dashboard) + APScheduler BackgroundScheduler (fetch/price/digest jobs). SQLite at `/data/news.db` for all persistence. Schedule config stored at `/data/schedule.json`, read on every job run so live changes take effect immediately.

**Tech Stack:** Python 3.12, FastAPI 0.115, APScheduler 3.10, feedparser 6, httpx 0.28, BeautifulSoup4, anthropic SDK 0.40, sqlite3 (stdlib), pytest 8.

---

## File Map

| File | Responsibility |
|------|---------------|
| `news-feed/requirements.txt` | Python deps + test deps |
| `news-feed/app/config.py` | SOURCES registry, DB_PATH, `get_config()`, `update_config()` |
| `news-feed/app/models.py` | `get_conn()`, `init_db()`, all CRUD helpers |
| `news-feed/app/deps.py` | FastAPI `get_db` dependency (yield conn per request) |
| `news-feed/app/fetcher.py` | `fetch_all(db_path, config)` — RSS → dedup → body → returns new IDs |
| `news-feed/app/summarizer.py` | `summarize(title, body, config)` — routes Anthropic vs OpenRouter |
| `news-feed/app/pricer.py` | `fetch_prices(db_path)` — OpenRouter API → upsert prices |
| `news-feed/app/notifier.py` | `send_digest(articles, config)` — LINE + Telegram push |
| `news-feed/app/scheduler.py` | `setup_scheduler(db_path)` → `BackgroundScheduler` with 3 jobs |
| `news-feed/app/api/news.py` | `GET /api/news`, `GET /api/news/{id}` |
| `news-feed/app/api/prices.py` | `GET /api/prices` |
| `news-feed/app/api/schedule.py` | `GET/POST /api/schedule` |
| `news-feed/app/api/digest.py` | `GET /api/digest/history`, `POST /api/digest/trigger` |
| `news-feed/app/api/health.py` | `GET /api/health` |
| `news-feed/app/main.py` | FastAPI app, lifespan (init DB, start scheduler, mount static) |
| `news-feed/app/static/index.html` | Dashboard shell + tabs |
| `news-feed/app/static/app.js` | All 6 dashboard sections, Chart.js CDN |
| `news-feed/Dockerfile` | Python 3.12-slim, non-root user |
| `news-feed/docker-compose.yml` | Service, volume, port 5064 |
| `news-feed/.env.example` | All env vars with comments |
| `news-feed/README.md` | Setup + usage |
| `news-feed/tests/conftest.py` | Shared fixtures (tmp DB, sample data) |
| `news-feed/tests/test_models.py` | Unit tests for every CRUD helper |
| `news-feed/tests/test_fetcher.py` | Fetcher with mocked feedparser + httpx |
| `news-feed/tests/test_summarizer.py` | Summarizer with mocked Anthropic + httpx |
| `news-feed/tests/test_pricer.py` | Pricer with mocked httpx |
| `news-feed/tests/test_notifier.py` | Notifier with mocked httpx |
| `news-feed/tests/test_api.py` | API endpoints via FastAPI TestClient |
| `CLAUDE.md` | Add news-feed row to ports table |

---

## Task 1: Project Scaffold

**Files:**
- Create: `news-feed/requirements.txt`
- Create: `news-feed/app/__init__.py`
- Create: `news-feed/app/api/__init__.py`
- Create: `news-feed/tests/__init__.py`
- Create: `news-feed/tests/conftest.py`
- Create: `news-feed/.notes/.gitkeep`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p news-feed/app/api news-feed/app/static news-feed/tests news-feed/.notes
touch news-feed/app/__init__.py news-feed/app/api/__init__.py news-feed/tests/__init__.py news-feed/.notes/.gitkeep
```

- [ ] **Step 2: Write `news-feed/requirements.txt`**

```text
fastapi==0.115.5
uvicorn[standard]==0.32.1
apscheduler==3.10.4
feedparser==6.0.11
httpx==0.28.0
beautifulsoup4==4.12.3
anthropic==0.40.0
python-dotenv==1.0.1

pytest==8.3.4
pytest-mock==3.14.0
httpx==0.28.0
```

- [ ] **Step 3: Write `news-feed/tests/conftest.py`**

```python
import sqlite3
import pytest
from pathlib import Path
from app.models import get_conn, init_db


@pytest.fixture
def db(tmp_path: Path) -> sqlite3.Connection:
    conn = get_conn(str(tmp_path / "test.db"))
    init_db(conn)
    yield conn
    conn.close()


@pytest.fixture
def sample_article() -> dict:
    return {
        "id": "abc123",
        "source": "techcrunch_ai",
        "title": "AI News",
        "url": "https://example.com/article",
        "published": "2026-05-23T07:00:00",
        "fetched_at": "2026-05-23T07:01:00",
    }


@pytest.fixture
def base_config() -> dict:
    return {
        "digest_times": ["07:00", "12:00", "18:00"],
        "enabled_sources": ["techcrunch_ai", "venturebeat"],
        "summarizer_provider": "anthropic",
        "summarizer_model": "claude-sonnet-4-6",
    }
```

- [ ] **Step 4: Verify pytest can be imported (no code to run yet)**

```bash
cd news-feed && pip install -r requirements.txt
```

Expected: installs without errors.

- [ ] **Step 5: Commit scaffold**

```bash
git add news-feed/
git commit -m "feat(news-feed): scaffold project structure"
```

---

## Task 2: Config Module

**Files:**
- Create: `news-feed/app/config.py`

- [ ] **Step 1: Write `news-feed/app/config.py`**

```python
import json
import os
from pathlib import Path

SOURCES: dict[str, str] = {
    "techcrunch_ai": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "venturebeat": "https://venturebeat.com/feed/",
    "theverge": "https://www.theverge.com/rss/index.xml",
    "arstechnica": "https://feeds.arstechnica.com/arstechnica/technology-lab",
    "gsmarena": "https://www.gsmarena.com/rss-news-reviews.php3",
    "9to5mac": "https://9to5mac.com/feed/",
    "android_authority": "https://www.androidauthority.com/feed/",
}

DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
DB_PATH = str(DATA_DIR / "news.db")
_SCHEDULE_FILE = DATA_DIR / "schedule.json"


def _env_defaults() -> dict:
    return {
        "digest_times": [t.strip() for t in os.getenv("DIGEST_TIMES", "07:00,12:00,18:00").split(",")],
        "enabled_sources": [s.strip() for s in os.getenv("ENABLED_SOURCES", ",".join(SOURCES)).split(",")],
        "summarizer_provider": os.getenv("SUMMARIZER_PROVIDER", "anthropic"),
        "summarizer_model": os.getenv("SUMMARIZER_MODEL", "claude-sonnet-4-6"),
    }


def get_config() -> dict:
    if _SCHEDULE_FILE.exists():
        return json.loads(_SCHEDULE_FILE.read_text())
    return _env_defaults()


def update_config(data: dict) -> dict:
    current = get_config()
    current.update(data)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _SCHEDULE_FILE.write_text(json.dumps(current, indent=2))
    return current
```

- [ ] **Step 2: Write `news-feed/tests/test_config.py`**

```python
import json
from pathlib import Path
from unittest.mock import patch
import pytest


def test_get_config_returns_env_defaults_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGEST_TIMES", "08:00,13:00")
    monkeypatch.setenv("SUMMARIZER_PROVIDER", "openrouter")
    with patch("app.config._SCHEDULE_FILE", tmp_path / "schedule.json"):
        from app import config
        # Force re-read by calling directly
        result = config.get_config()
    assert "08:00" in result["digest_times"]
    assert result["summarizer_provider"] == "openrouter"


def test_get_config_reads_schedule_json(tmp_path):
    schedule = {"digest_times": ["09:00"], "enabled_sources": ["gsmarena"],
                 "summarizer_provider": "anthropic", "summarizer_model": "claude-sonnet-4-6"}
    f = tmp_path / "schedule.json"
    f.write_text(json.dumps(schedule))
    with patch("app.config._SCHEDULE_FILE", f):
        from app import config
        result = config.get_config()
    assert result["digest_times"] == ["09:00"]
    assert result["enabled_sources"] == ["gsmarena"]


def test_update_config_writes_file(tmp_path):
    with patch("app.config._SCHEDULE_FILE", tmp_path / "schedule.json"), \
         patch("app.config.DATA_DIR", tmp_path):
        from app import config
        config.update_config({"summarizer_provider": "openrouter", "summarizer_model": "deepseek/deepseek-chat",
                               "digest_times": ["07:00"], "enabled_sources": ["venturebeat"]})
        data = json.loads((tmp_path / "schedule.json").read_text())
    assert data["summarizer_provider"] == "openrouter"
    assert data["summarizer_model"] == "deepseek/deepseek-chat"
```

- [ ] **Step 3: Run tests**

```bash
cd news-feed && python -m pytest tests/test_config.py -v
```

Expected: 3 passed.

- [ ] **Step 4: Commit**

```bash
git add news-feed/app/config.py news-feed/tests/test_config.py
git commit -m "feat(news-feed): add config module with schedule.json persistence"
```

---

## Task 3: Data Layer

**Files:**
- Create: `news-feed/app/models.py`
- Create: `news-feed/tests/test_models.py`

- [ ] **Step 1: Write `news-feed/app/models.py`**

```python
import json
import sqlite3
from datetime import datetime, timezone


def get_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS articles (
            id          TEXT PRIMARY KEY,
            source      TEXT NOT NULL,
            title       TEXT NOT NULL,
            url         TEXT NOT NULL UNIQUE,
            published   TEXT NOT NULL,
            summary_th  TEXT,
            fetched_at  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS prices (
            model_id        TEXT PRIMARY KEY,
            provider        TEXT,
            name            TEXT,
            prompt_price    REAL,
            complete_price  REAL,
            context_length  INTEGER,
            updated_at      TEXT
        );
        CREATE TABLE IF NOT EXISTS digest_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            sent_at     TEXT NOT NULL,
            article_ids TEXT NOT NULL,
            channels    TEXT NOT NULL
        );
    """)
    conn.commit()


def article_exists(conn: sqlite3.Connection, article_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM articles WHERE id = ?", (article_id,)).fetchone()
    return row is not None


def insert_article(conn: sqlite3.Connection, article: dict) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO articles (id, source, title, url, published, fetched_at) VALUES (?,?,?,?,?,?)",
        (article["id"], article["source"], article["title"], article["url"],
         article["published"], article["fetched_at"]),
    )
    conn.commit()


def update_article_summary(conn: sqlite3.Connection, article_id: str, summary_th: str) -> None:
    conn.execute("UPDATE articles SET summary_th = ? WHERE id = ?", (summary_th, article_id))
    conn.commit()


def get_articles(conn: sqlite3.Connection, source: str | None = None,
                 date: str | None = None, limit: int = 20) -> list[dict]:
    query = "SELECT * FROM articles WHERE 1=1"
    params: list = []
    if source:
        query += " AND source = ?"
        params.append(source)
    if date:
        query += " AND published >= ?"
        params.append(date)
    query += " ORDER BY published DESC LIMIT ?"
    params.append(limit)
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def get_article(conn: sqlite3.Connection, article_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
    return dict(row) if row else None


def get_recent_articles_for_digest(conn: sqlite3.Connection, hours: int = 6, limit: int = 5) -> list[dict]:
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    # Subtract hours manually via SQL
    rows = conn.execute(
        "SELECT * FROM articles WHERE summary_th IS NOT NULL "
        "AND fetched_at >= datetime(?, ?) "
        "ORDER BY published DESC LIMIT ?",
        (cutoff, f"-{hours} hours", limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_article_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]


def get_last_fetch_time(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT MAX(fetched_at) FROM articles").fetchone()
    return row[0] if row else None


def get_source_counts(conn: sqlite3.Connection, hours: int = 24) -> list[dict]:
    rows = conn.execute(
        "SELECT source, COUNT(*) as count FROM articles "
        "WHERE fetched_at >= datetime('now', ?) GROUP BY source",
        (f"-{hours} hours",),
    ).fetchall()
    return [dict(r) for r in rows]


def upsert_price(conn: sqlite3.Connection, model: dict) -> None:
    conn.execute(
        "INSERT INTO prices (model_id, provider, name, prompt_price, complete_price, context_length, updated_at) "
        "VALUES (?,?,?,?,?,?,?) ON CONFLICT(model_id) DO UPDATE SET "
        "provider=excluded.provider, name=excluded.name, prompt_price=excluded.prompt_price, "
        "complete_price=excluded.complete_price, context_length=excluded.context_length, updated_at=excluded.updated_at",
        (model["model_id"], model["provider"], model["name"], model["prompt_price"],
         model["complete_price"], model.get("context_length"), model["updated_at"]),
    )
    conn.commit()


def get_prices(conn: sqlite3.Connection, provider: str | None = None,
               sort: str = "combined_asc") -> list[dict]:
    sort_map = {
        "prompt_asc": "prompt_price ASC",
        "prompt_desc": "prompt_price DESC",
        "complete_asc": "complete_price ASC",
        "combined_asc": "(prompt_price + complete_price) ASC",
    }
    order = sort_map.get(sort, "combined_asc")
    query = "SELECT * FROM prices WHERE 1=1"
    params: list = []
    if provider:
        query += " AND provider = ?"
        params.append(provider)
    query += f" ORDER BY {order}"
    return [dict(r) for r in conn.execute(query, params).fetchall()]


def insert_digest_log(conn: sqlite3.Connection, sent_at: str,
                      article_ids: list[str], channels: str) -> int:
    cur = conn.execute(
        "INSERT INTO digest_log (sent_at, article_ids, channels) VALUES (?,?,?)",
        (sent_at, json.dumps(article_ids), channels),
    )
    conn.commit()
    return cur.lastrowid


def get_digest_history(conn: sqlite3.Connection, limit: int = 30) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM digest_log ORDER BY sent_at DESC LIMIT ?", (limit,)
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["article_ids"] = json.loads(d["article_ids"])
        result.append(d)
    return result
```

- [ ] **Step 2: Write `news-feed/tests/test_models.py`**

```python
from app.models import (
    article_exists, insert_article, update_article_summary,
    get_articles, get_article, get_article_count, get_last_fetch_time,
    get_source_counts, upsert_price, get_prices,
    insert_digest_log, get_digest_history, get_recent_articles_for_digest,
)


def test_article_not_exists_initially(db):
    assert not article_exists(db, "abc123")


def test_insert_and_exists(db, sample_article):
    insert_article(db, sample_article)
    assert article_exists(db, "abc123")


def test_insert_idempotent(db, sample_article):
    insert_article(db, sample_article)
    insert_article(db, sample_article)  # should not raise
    assert get_article_count(db) == 1


def test_update_summary(db, sample_article):
    insert_article(db, sample_article)
    update_article_summary(db, "abc123", "สรุปภาษาไทย")
    row = get_article(db, "abc123")
    assert row["summary_th"] == "สรุปภาษาไทย"


def test_get_articles_filter_source(db, sample_article):
    insert_article(db, sample_article)
    results = get_articles(db, source="techcrunch_ai")
    assert len(results) == 1
    results_other = get_articles(db, source="gsmarena")
    assert len(results_other) == 0


def test_get_article_returns_none_for_missing(db):
    assert get_article(db, "nope") is None


def test_get_article_count(db, sample_article):
    assert get_article_count(db) == 0
    insert_article(db, sample_article)
    assert get_article_count(db) == 1


def test_get_last_fetch_time_empty(db):
    assert get_last_fetch_time(db) is None


def test_get_source_counts(db, sample_article):
    insert_article(db, sample_article)
    counts = get_source_counts(db, hours=24)
    assert any(c["source"] == "techcrunch_ai" and c["count"] == 1 for c in counts)


def test_upsert_price(db):
    upsert_price(db, {
        "model_id": "openai/gpt-4o", "provider": "openai", "name": "GPT-4o",
        "prompt_price": 5.0, "complete_price": 15.0, "context_length": 128000,
        "updated_at": "2026-05-23T00:00:00",
    })
    prices = get_prices(db)
    assert len(prices) == 1
    assert prices[0]["model_id"] == "openai/gpt-4o"


def test_upsert_price_updates_existing(db):
    base = {"model_id": "x/y", "provider": "x", "name": "Y",
            "prompt_price": 1.0, "complete_price": 2.0,
            "context_length": 4096, "updated_at": "2026-05-23T00:00:00"}
    upsert_price(db, base)
    upsert_price(db, {**base, "prompt_price": 0.5})
    prices = get_prices(db)
    assert len(prices) == 1
    assert prices[0]["prompt_price"] == 0.5


def test_get_prices_filter_provider(db):
    for p, mid in [("openai", "openai/gpt-4o"), ("anthropic", "anthropic/claude-3")]:
        upsert_price(db, {"model_id": mid, "provider": p, "name": mid,
                          "prompt_price": 1.0, "complete_price": 2.0,
                          "context_length": 4096, "updated_at": "2026-05-23T00:00:00"})
    assert len(get_prices(db, provider="openai")) == 1
    assert len(get_prices(db)) == 2


def test_insert_and_get_digest_log(db, sample_article):
    insert_article(db, sample_article)
    insert_digest_log(db, "2026-05-23T07:00:00", ["abc123"], "line,telegram")
    history = get_digest_history(db)
    assert len(history) == 1
    assert history[0]["article_ids"] == ["abc123"]
    assert history[0]["channels"] == "line,telegram"
```

- [ ] **Step 3: Run tests**

```bash
cd news-feed && python -m pytest tests/test_models.py -v
```

Expected: 14 passed.

- [ ] **Step 4: Commit**

```bash
git add news-feed/app/models.py news-feed/tests/test_models.py
git commit -m "feat(news-feed): add SQLite data layer with full CRUD"
```

---

## Task 4: RSS Fetcher

**Files:**
- Create: `news-feed/app/fetcher.py`
- Create: `news-feed/tests/test_fetcher.py`

- [ ] **Step 1: Write `news-feed/app/fetcher.py`**

```python
import hashlib
import logging
from datetime import datetime, timezone

import feedparser
import httpx
from bs4 import BeautifulSoup

from app.config import SOURCES
from app.models import article_exists, get_conn, insert_article, update_article_summary
from app.summarizer import summarize

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "news-feed-bot/1.0 (NAS RSS reader)"}


def _entry_url(entry) -> str:
    return entry.get("link") or entry.get("id") or ""


def _entry_published(entry) -> str:
    for field in ("published", "updated"):
        val = entry.get(field)
        if val:
            return val
    return datetime.now(timezone.utc).isoformat()


def _fetch_body(url: str) -> str:
    try:
        r = httpx.get(url, headers=_HEADERS, timeout=15, follow_redirects=True)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        return soup.get_text(separator=" ", strip=True)[:1500]
    except Exception as exc:
        logger.warning("body fetch failed %s: %s", url, exc)
        return ""


def fetch_all(db_path: str, config: dict) -> list[str]:
    conn = get_conn(db_path)
    new_ids: list[str] = []
    try:
        for source_key in config.get("enabled_sources", []):
            url = SOURCES.get(source_key)
            if not url:
                continue
            try:
                feed = feedparser.parse(url)
            except Exception as exc:
                logger.error("feedparser error %s: %s", source_key, exc)
                continue
            for entry in feed.entries:
                entry_url = _entry_url(entry)
                if not entry_url:
                    continue
                article_id = hashlib.sha256(entry_url.encode()).hexdigest()[:16]
                if article_exists(conn, article_id):
                    continue
                fetched_at = datetime.now(timezone.utc).isoformat()
                insert_article(conn, {
                    "id": article_id,
                    "source": source_key,
                    "title": entry.get("title", ""),
                    "url": entry_url,
                    "published": _entry_published(entry),
                    "fetched_at": fetched_at,
                })
                body = _fetch_body(entry_url)
                try:
                    summary = summarize(entry.get("title", ""), body, config)
                    update_article_summary(conn, article_id, summary)
                except Exception as exc:
                    logger.error("summarize failed %s: %s", article_id, exc)
                new_ids.append(article_id)
    finally:
        conn.close()
    return new_ids
```

- [ ] **Step 2: Write `news-feed/tests/test_fetcher.py`**

```python
from unittest.mock import MagicMock, patch
import pytest
from app.fetcher import fetch_all


def _make_feed(entries):
    feed = MagicMock()
    feed.entries = entries
    return feed


def _make_entry(url, title="Test", published="2026-05-23T07:00:00"):
    e = MagicMock()
    e.get = lambda k, d="": {"link": url, "title": title, "published": published}.get(k, d)
    return e


@patch("app.fetcher.summarize", return_value="สรุปทดสอบ")
@patch("app.fetcher.httpx.get")
@patch("app.fetcher.feedparser.parse")
def test_fetch_all_inserts_new_articles(mock_parse, mock_get, mock_summarize, db, tmp_path, base_config):
    mock_parse.return_value = _make_feed([_make_entry("https://example.com/1")])
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.text = "<html><body><p>Article body text here</p></body></html>"
    mock_get.return_value = mock_resp

    db_path = str(tmp_path / "test.db")
    from app.models import get_conn, init_db
    conn = get_conn(db_path)
    init_db(conn)
    conn.close()

    new_ids = fetch_all(db_path, base_config)
    assert len(new_ids) == 1


@patch("app.fetcher.summarize", return_value="สรุปทดสอบ")
@patch("app.fetcher.httpx.get")
@patch("app.fetcher.feedparser.parse")
def test_fetch_all_skips_duplicates(mock_parse, mock_get, mock_summarize, db, tmp_path, base_config):
    mock_parse.return_value = _make_feed([_make_entry("https://example.com/1")])
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.text = "<p>body</p>"
    mock_get.return_value = mock_resp

    db_path = str(tmp_path / "test2.db")
    from app.models import get_conn, init_db
    conn = get_conn(db_path)
    init_db(conn)
    conn.close()

    first = fetch_all(db_path, base_config)
    second = fetch_all(db_path, base_config)
    assert len(first) == 1
    assert len(second) == 0


@patch("app.fetcher.feedparser.parse", side_effect=Exception("network error"))
def test_fetch_all_tolerates_feed_error(mock_parse, tmp_path, base_config):
    db_path = str(tmp_path / "test3.db")
    from app.models import get_conn, init_db
    conn = get_conn(db_path)
    init_db(conn)
    conn.close()
    result = fetch_all(db_path, base_config)
    assert result == []
```

- [ ] **Step 3: Run tests**

```bash
cd news-feed && python -m pytest tests/test_fetcher.py -v
```

Expected: 3 passed.

- [ ] **Step 4: Commit**

```bash
git add news-feed/app/fetcher.py news-feed/tests/test_fetcher.py
git commit -m "feat(news-feed): add RSS fetcher with dedup and body extraction"
```

---

## Task 5: Summarizer

**Files:**
- Create: `news-feed/app/summarizer.py`
- Create: `news-feed/tests/test_summarizer.py`

- [ ] **Step 1: Write `news-feed/app/summarizer.py`**

```python
import os
import time
import logging
import httpx
import anthropic

logger = logging.getLogger(__name__)

_SYSTEM = "คุณคือผู้ช่วยสรุปข่าวเทคโนโลยีเป็นภาษาไทย กระชับ อ่านง่าย"


def _user_prompt(title: str, body: str) -> str:
    return f"สรุปบทความนี้ 2-3 ประโยค:\nTitle: {title}\nContent: {body[:1500]}"


def _with_retry(fn, retries: int = 3):
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt
            logger.warning("summarize retry %d/%d after %ds: %s", attempt + 1, retries, wait, exc)
            time.sleep(wait)


def _summarize_anthropic(title: str, body: str, model: str) -> str:
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))

    def call():
        resp = client.messages.create(
            model=model,
            max_tokens=300,
            system=[{"type": "text", "text": _SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": _user_prompt(title, body)}],
        )
        return resp.content[0].text

    return _with_retry(call)


def _summarize_openrouter(title: str, body: str, model: str) -> str:
    api_key = os.getenv("OPENROUTER_API_KEY", "")

    def call():
        resp = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "news-feed-nas",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 300,
                "messages": [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": _user_prompt(title, body)},
                ],
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    return _with_retry(call)


def summarize(title: str, body: str, config: dict) -> str:
    provider = config.get("summarizer_provider", "anthropic")
    model = config.get("summarizer_model", "claude-sonnet-4-6")
    if provider == "openrouter":
        return _summarize_openrouter(title, body, model)
    return _summarize_anthropic(title, body, model)
```

- [ ] **Step 2: Write `news-feed/tests/test_summarizer.py`**

```python
from unittest.mock import MagicMock, patch
from app.summarizer import summarize


@patch("app.summarizer.anthropic.Anthropic")
def test_summarize_anthropic(mock_cls, base_config):
    mock_client = MagicMock()
    mock_cls.return_value = mock_client
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="สรุปทดสอบ")]
    )
    result = summarize("Title", "Body text", base_config)
    assert result == "สรุปทดสอบ"
    mock_client.messages.create.assert_called_once()


@patch("app.summarizer.httpx.post")
def test_summarize_openrouter(mock_post, base_config):
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"choices": [{"message": {"content": "สรุป OR"}}]}
    mock_post.return_value = mock_resp

    config = {**base_config, "summarizer_provider": "openrouter", "summarizer_model": "deepseek/deepseek-chat"}
    result = summarize("Title", "Body text", config)
    assert result == "สรุป OR"
    assert mock_post.call_args[0][0] == "https://openrouter.ai/api/v1/chat/completions"


@patch("app.summarizer.anthropic.Anthropic")
def test_summarize_retries_on_failure(mock_cls, base_config):
    mock_client = MagicMock()
    mock_cls.return_value = mock_client
    mock_client.messages.create.side_effect = [
        Exception("rate limit"),
        MagicMock(content=[MagicMock(text="สรุปหลัง retry")]),
    ]
    result = summarize("Title", "Body", base_config)
    assert result == "สรุปหลัง retry"
    assert mock_client.messages.create.call_count == 2
```

- [ ] **Step 3: Run tests**

```bash
cd news-feed && python -m pytest tests/test_summarizer.py -v
```

Expected: 3 passed.

- [ ] **Step 4: Commit**

```bash
git add news-feed/app/summarizer.py news-feed/tests/test_summarizer.py
git commit -m "feat(news-feed): add summarizer with Anthropic + OpenRouter providers"
```

---

## Task 6: Price Fetcher

**Files:**
- Create: `news-feed/app/pricer.py`
- Create: `news-feed/tests/test_pricer.py`

- [ ] **Step 1: Write `news-feed/app/pricer.py`**

```python
import logging
from datetime import datetime, timezone

import httpx

from app.models import get_conn, upsert_price

logger = logging.getLogger(__name__)

_OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


def fetch_prices(db_path: str) -> int:
    try:
        resp = httpx.get(_OPENROUTER_MODELS_URL, timeout=30.0)
        resp.raise_for_status()
    except Exception as exc:
        logger.error("pricer fetch failed: %s", exc)
        return 0

    models = resp.json().get("data", [])
    updated_at = datetime.now(timezone.utc).isoformat()
    conn = get_conn(db_path)
    count = 0
    try:
        for m in models:
            model_id = m.get("id", "")
            if not model_id:
                continue
            pricing = m.get("pricing", {})
            prompt_str = pricing.get("prompt", "0") or "0"
            complete_str = pricing.get("completion", "0") or "0"
            upsert_price(conn, {
                "model_id": model_id,
                "provider": model_id.split("/")[0] if "/" in model_id else "unknown",
                "name": m.get("name", model_id),
                "prompt_price": float(prompt_str) * 1_000_000,
                "complete_price": float(complete_str) * 1_000_000,
                "context_length": m.get("context_length"),
                "updated_at": updated_at,
            })
            count += 1
    finally:
        conn.close()
    logger.info("pricer upserted %d models", count)
    return count
```

- [ ] **Step 2: Write `news-feed/tests/test_pricer.py`**

```python
from unittest.mock import MagicMock, patch
from app.pricer import fetch_prices
from app.models import get_prices


def _or_response(models):
    m = MagicMock()
    m.raise_for_status = MagicMock()
    m.json.return_value = {"data": models}
    return m


@patch("app.pricer.httpx.get")
def test_fetch_prices_upserts_models(mock_get, tmp_path):
    mock_get.return_value = _or_response([{
        "id": "deepseek/deepseek-chat",
        "name": "DeepSeek Chat",
        "context_length": 64000,
        "pricing": {"prompt": "0.00000014", "completion": "0.00000028"},
    }])
    db_path = str(tmp_path / "p.db")
    from app.models import get_conn, init_db
    conn = get_conn(db_path); init_db(conn); conn.close()

    count = fetch_prices(db_path)
    assert count == 1

    conn = get_conn(db_path)
    prices = get_prices(conn)
    conn.close()
    assert prices[0]["model_id"] == "deepseek/deepseek-chat"
    assert abs(prices[0]["prompt_price"] - 0.14) < 0.001


@patch("app.pricer.httpx.get", side_effect=Exception("timeout"))
def test_fetch_prices_tolerates_network_error(mock_get, tmp_path):
    db_path = str(tmp_path / "p2.db")
    from app.models import get_conn, init_db
    conn = get_conn(db_path); init_db(conn); conn.close()
    count = fetch_prices(db_path)
    assert count == 0
```

- [ ] **Step 3: Run tests**

```bash
cd news-feed && python -m pytest tests/test_pricer.py -v
```

Expected: 2 passed.

- [ ] **Step 4: Commit**

```bash
git add news-feed/app/pricer.py news-feed/tests/test_pricer.py
git commit -m "feat(news-feed): add OpenRouter price fetcher"
```

---

## Task 7: Notifier

**Files:**
- Create: `news-feed/app/notifier.py`
- Create: `news-feed/tests/test_notifier.py`

- [ ] **Step 1: Write `news-feed/app/notifier.py`**

```python
import logging
import os

import httpx

logger = logging.getLogger(__name__)


def _format_digest(articles: list[dict]) -> str:
    lines = ["📰 *ข่าวเทคโนโลยี/AI ล่าสุด*\n"]
    for i, a in enumerate(articles, 1):
        lines.append(f"{i}. <b>{a['title']}</b>")
        if a.get("summary_th"):
            lines.append(f"   {a['summary_th']}")
        lines.append(f"   🔗 {a['url']}\n")
    return "\n".join(lines)


def _send_line(message: str) -> bool:
    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
    user_id = os.getenv("LINE_USER_ID", "")
    if not token or not user_id:
        logger.warning("LINE credentials not set, skipping")
        return False
    try:
        resp = httpx.post(
            "https://api.line.me/v2/bot/message/push",
            headers={"Authorization": f"Bearer {token}"},
            json={"to": user_id, "messages": [{"type": "text", "text": message}]},
            timeout=15.0,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:
        logger.error("LINE send failed: %s", exc)
        return False


def _send_telegram(message: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        logger.warning("Telegram credentials not set, skipping")
        return False
    try:
        resp = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            timeout=15.0,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:
        logger.error("Telegram send failed: %s", exc)
        return False


def send_digest(articles: list[dict], config: dict) -> list[str]:
    if not articles:
        logger.info("no articles for digest, skipping")
        return []
    message = _format_digest(articles)
    sent = []
    if _send_line(message):
        sent.append("line")
    if _send_telegram(message):
        sent.append("telegram")
    return sent
```

- [ ] **Step 2: Write `news-feed/tests/test_notifier.py`**

```python
from unittest.mock import MagicMock, patch
from app.notifier import send_digest


def _ok_response():
    m = MagicMock()
    m.raise_for_status = MagicMock()
    return m


@patch("app.notifier.httpx.post", return_value=_ok_response())
def test_send_digest_sends_to_both_channels(mock_post, monkeypatch, base_config):
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("LINE_USER_ID", "Uabc")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot:token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    articles = [{"title": "AI News", "summary_th": "สรุปข่าว", "url": "https://x.com/1"}]
    sent = send_digest(articles, base_config)
    assert "line" in sent
    assert "telegram" in sent
    assert mock_post.call_count == 2


def test_send_digest_skips_when_no_credentials(monkeypatch, base_config):
    monkeypatch.delenv("LINE_CHANNEL_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    sent = send_digest([{"title": "X", "summary_th": "Y", "url": "https://x.com"}], base_config)
    assert sent == []


def test_send_digest_empty_articles(base_config):
    sent = send_digest([], base_config)
    assert sent == []
```

- [ ] **Step 3: Run tests**

```bash
cd news-feed && python -m pytest tests/test_notifier.py -v
```

Expected: 3 passed.

- [ ] **Step 4: Commit**

```bash
git add news-feed/app/notifier.py news-feed/tests/test_notifier.py
git commit -m "feat(news-feed): add LINE + Telegram notifier"
```

---

## Task 8: Scheduler

**Files:**
- Create: `news-feed/app/scheduler.py`

- [ ] **Step 1: Write `news-feed/app/scheduler.py`**

```python
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import DB_PATH, get_config
from app.fetcher import fetch_all
from app.models import get_conn, get_recent_articles_for_digest, insert_digest_log
from app.notifier import send_digest
from app.pricer import fetch_prices

logger = logging.getLogger(__name__)


def _fetch_job() -> None:
    config = get_config()
    logger.info("fetch_job starting")
    new_ids = fetch_all(DB_PATH, config)
    logger.info("fetch_job done: %d new articles", len(new_ids))


def _price_job() -> None:
    logger.info("price_job starting")
    count = fetch_prices(DB_PATH)
    logger.info("price_job done: %d models upserted", count)


def _digest_job() -> None:
    config = get_config()
    conn = get_conn(DB_PATH)
    try:
        articles = get_recent_articles_for_digest(conn, hours=6, limit=5)
        sent = send_digest(articles, config)
        if sent and articles:
            insert_digest_log(
                conn,
                datetime.now(timezone.utc).isoformat(),
                [a["id"] for a in articles],
                ",".join(sent),
            )
        logger.info("digest_job sent to: %s", sent)
    finally:
        conn.close()


def setup_scheduler(db_path: str) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Asia/Bangkok")

    scheduler.add_job(
        _fetch_job,
        trigger=IntervalTrigger(minutes=60),
        id="fetch_job",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.add_job(
        _price_job,
        trigger=IntervalTrigger(hours=6),
        id="price_job",
        replace_existing=True,
        max_instances=1,
    )

    config = get_config()
    for t in config.get("digest_times", ["07:00", "12:00", "18:00"]):
        hour, minute = t.split(":")
        scheduler.add_job(
            _digest_job,
            trigger=CronTrigger(hour=int(hour), minute=int(minute)),
            id=f"digest_{t.replace(':', '')}",
            replace_existing=True,
            max_instances=1,
        )

    return scheduler
```

- [ ] **Step 2: Verify scheduler imports cleanly**

```bash
cd news-feed && python -c "from app.scheduler import setup_scheduler; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add news-feed/app/scheduler.py
git commit -m "feat(news-feed): add APScheduler with fetch/price/digest jobs"
```

---

## Task 9: API — News & Prices Endpoints

**Files:**
- Create: `news-feed/app/deps.py`
- Create: `news-feed/app/api/news.py`
- Create: `news-feed/app/api/prices.py`

- [ ] **Step 1: Write `news-feed/app/deps.py`**

```python
import sqlite3
from typing import Generator

from fastapi import Request

from app.models import get_conn


def get_db(request: Request) -> Generator[sqlite3.Connection, None, None]:
    conn = get_conn(request.app.state.db_path)
    try:
        yield conn
    finally:
        conn.close()
```

- [ ] **Step 2: Write `news-feed/app/api/news.py`**

```python
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import get_db
from app.models import get_article, get_articles

router = APIRouter(prefix="/api/news", tags=["news"])


@router.get("")
def list_news(
    db: Annotated[sqlite3.Connection, Depends(get_db)],
    source: str | None = Query(None),
    date: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
):
    return get_articles(db, source=source, date=date, limit=limit)


@router.get("/{article_id}")
def get_news_item(
    article_id: str,
    db: Annotated[sqlite3.Connection, Depends(get_db)],
):
    article = get_article(db, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return article
```

- [ ] **Step 3: Write `news-feed/app/api/prices.py`**

```python
import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.deps import get_db
from app.models import get_prices

router = APIRouter(prefix="/api/prices", tags=["prices"])


@router.get("")
def list_prices(
    db: Annotated[sqlite3.Connection, Depends(get_db)],
    provider: str | None = Query(None),
    sort: Literal["prompt_asc", "prompt_desc", "complete_asc", "combined_asc"] = Query("combined_asc"),
):
    return get_prices(db, provider=provider, sort=sort)
```

- [ ] **Step 4: Commit**

```bash
git add news-feed/app/deps.py news-feed/app/api/news.py news-feed/app/api/prices.py
git commit -m "feat(news-feed): add news + prices API endpoints"
```

---

## Task 10: API — Schedule, Digest & Health Endpoints

**Files:**
- Create: `news-feed/app/api/schedule.py`
- Create: `news-feed/app/api/digest.py`
- Create: `news-feed/app/api/health.py`
- Create: `news-feed/tests/test_api.py`

- [ ] **Step 1: Write `news-feed/app/api/schedule.py`**

```python
from fastapi import APIRouter

from app.config import update_config, get_config

router = APIRouter(prefix="/api/schedule", tags=["schedule"])


@router.get("")
def get_schedule():
    return get_config()


@router.post("")
def post_schedule(body: dict):
    allowed_keys = {"digest_times", "enabled_sources", "summarizer_provider", "summarizer_model"}
    filtered = {k: v for k, v in body.items() if k in allowed_keys}
    return update_config(filtered)
```

- [ ] **Step 2: Write `news-feed/app/api/digest.py`**

```python
import sqlite3
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException

from app.config import get_config, DB_PATH
from app.deps import get_db
from app.models import get_conn, get_digest_history, get_recent_articles_for_digest, insert_digest_log
from app.notifier import send_digest
import os

router = APIRouter(prefix="/api/digest", tags=["digest"])


@router.get("/history")
def digest_history(db: Annotated[sqlite3.Connection, Depends(get_db)]):
    return get_digest_history(db)


@router.post("/trigger")
def trigger_digest(x_admin_token: str | None = Header(None)):
    expected = os.getenv("ADMIN_TOKEN", "")
    if not expected or x_admin_token != expected:
        raise HTTPException(status_code=403, detail="Forbidden")
    config = get_config()
    conn = get_conn(DB_PATH)
    try:
        articles = get_recent_articles_for_digest(conn, hours=6, limit=5)
        sent = send_digest(articles, config)
        if sent and articles:
            insert_digest_log(
                conn,
                datetime.now(timezone.utc).isoformat(),
                [a["id"] for a in articles],
                ",".join(sent),
            )
        return {"sent_to": sent, "article_count": len(articles)}
    finally:
        conn.close()
```

- [ ] **Step 3: Write `news-feed/app/api/health.py`**

```python
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends

from app.deps import get_db
from app.models import get_article_count, get_last_fetch_time

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health(db: Annotated[sqlite3.Connection, Depends(get_db)]):
    return {
        "status": "ok",
        "article_count": get_article_count(db),
        "last_fetch": get_last_fetch_time(db),
    }
```

- [ ] **Step 4: Write `news-feed/tests/test_api.py`**

```python
import os
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models import get_conn, init_db, insert_article, update_article_summary


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test_api.db")
    monkeypatch.setattr("app.config.DB_PATH", db_path)
    monkeypatch.setattr("app.deps.get_conn", lambda _: get_conn(db_path))
    app.state.db_path = db_path
    conn = get_conn(db_path)
    init_db(conn)
    insert_article(conn, {
        "id": "test01",
        "source": "techcrunch_ai",
        "title": "Test Article",
        "url": "https://example.com/test",
        "published": "2026-05-23T07:00:00",
        "fetched_at": "2026-05-23T07:01:00",
    })
    update_article_summary(conn, "test01", "สรุปทดสอบ")
    conn.close()
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["article_count"] == 1


def test_list_news(client):
    r = client.get("/api/news")
    assert r.status_code == 200
    articles = r.json()
    assert len(articles) == 1
    assert articles[0]["id"] == "test01"


def test_get_news_item(client):
    r = client.get("/api/news/test01")
    assert r.status_code == 200
    assert r.json()["summary_th"] == "สรุปทดสอบ"


def test_get_news_item_404(client):
    r = client.get("/api/news/nope")
    assert r.status_code == 404


def test_get_schedule(client):
    r = client.get("/api/schedule")
    assert r.status_code == 200
    assert "digest_times" in r.json()


def test_post_schedule(client):
    r = client.post("/api/schedule", json={"summarizer_provider": "openrouter",
                                           "summarizer_model": "deepseek/deepseek-chat"})
    assert r.status_code == 200
    assert r.json()["summarizer_provider"] == "openrouter"


def test_digest_trigger_forbidden(client):
    r = client.post("/api/digest/trigger")
    assert r.status_code == 403


def test_digest_trigger_with_token(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "secret")
    r = client.post("/api/digest/trigger", headers={"X-Admin-Token": "secret"})
    assert r.status_code == 200
    assert "sent_to" in r.json()


def test_digest_history(client):
    r = client.get("/api/digest/history")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
```

- [ ] **Step 5: Run all API tests (requires main.py — stub it first)**

Write a minimal stub `news-feed/app/main.py` just to make imports work:

```python
from fastapi import FastAPI
from app.api import news, prices, schedule, digest, health

app = FastAPI()
app.include_router(news.router)
app.include_router(prices.router)
app.include_router(schedule.router)
app.include_router(digest.router)
app.include_router(health.router)
```

```bash
cd news-feed && python -m pytest tests/test_api.py -v
```

Expected: 9 passed.

- [ ] **Step 6: Commit**

```bash
git add news-feed/app/api/schedule.py news-feed/app/api/digest.py news-feed/app/api/health.py news-feed/tests/test_api.py news-feed/app/main.py
git commit -m "feat(news-feed): add schedule/digest/health endpoints + API tests"
```

---

## Task 11: FastAPI App (main.py — final)

**Files:**
- Modify: `news-feed/app/main.py`

- [ ] **Step 1: Replace stub with full `news-feed/app/main.py`**

```python
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import digest, health, news, prices, schedule
from app.config import DB_PATH, DATA_DIR
from app.models import get_conn, init_db
from app.scheduler import setup_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_conn(DB_PATH)
    init_db(conn)
    conn.close()
    app.state.db_path = DB_PATH

    scheduler = setup_scheduler(DB_PATH)
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="News Feed Bot", lifespan=lifespan)

app.include_router(news.router)
app.include_router(prices.router)
app.include_router(schedule.router)
app.include_router(digest.router)
app.include_router(health.router)

_static = Path(__file__).parent / "static"
if _static.exists():
    app.mount("/", StaticFiles(directory=str(_static), html=True), name="static")
```

- [ ] **Step 2: Verify app starts cleanly**

```bash
cd news-feed && DATA_DIR=/tmp/nf-test uvicorn app.main:app --port 8099 &
sleep 2 && curl -s http://localhost:8099/api/health | python3 -m json.tool
kill %1
```

Expected: `{"status": "ok", "article_count": 0, "last_fetch": null}`

- [ ] **Step 3: Run full test suite**

```bash
cd news-feed && python -m pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add news-feed/app/main.py
git commit -m "feat(news-feed): complete FastAPI app with lifespan and static mount"
```

---

## Task 12: Dashboard

**Files:**
- Create: `news-feed/app/static/index.html`
- Create: `news-feed/app/static/app.js`

- [ ] **Step 1: Write `news-feed/app/static/index.html`**

```html
<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>News Feed Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh}
  header{background:#1e293b;padding:1rem 1.5rem;display:flex;align-items:center;gap:1rem;border-bottom:1px solid #334155}
  header h1{font-size:1.1rem;font-weight:600}
  .badge{background:#3b82f6;color:#fff;border-radius:999px;padding:.15rem .6rem;font-size:.75rem}
  nav{display:flex;gap:.25rem;padding:.75rem 1.5rem;background:#1e293b;border-bottom:1px solid #334155;flex-wrap:wrap}
  nav button{background:none;border:none;color:#94a3b8;padding:.4rem .8rem;border-radius:.375rem;cursor:pointer;font-size:.875rem}
  nav button.active{background:#3b82f6;color:#fff}
  main{padding:1.5rem;max-width:1200px;margin:0 auto}
  .section{display:none}.section.active{display:block}
  .card{background:#1e293b;border:1px solid #334155;border-radius:.5rem;padding:1.25rem;margin-bottom:1rem}
  .card h2{font-size:.95rem;font-weight:600;margin-bottom:.75rem;color:#94a3b8}
  .dot{display:inline-block;width:.5rem;height:.5rem;border-radius:50%;margin-right:.35rem}
  .dot.green{background:#22c55e}.dot.red{background:#ef4444}
  table{width:100%;border-collapse:collapse;font-size:.85rem}
  th,td{text-align:left;padding:.5rem .75rem;border-bottom:1px solid #334155}
  th{color:#64748b;font-weight:500}
  .article-card{border-bottom:1px solid #334155;padding:.75rem 0;cursor:pointer}
  .article-card:last-child{border-bottom:none}
  .article-title{font-weight:500;margin-bottom:.25rem}
  .article-meta{font-size:.75rem;color:#64748b;margin-bottom:.25rem}
  .article-summary{font-size:.85rem;color:#94a3b8;display:none;margin-top:.5rem;line-height:1.5}
  .article-card.open .article-summary{display:block}
  .source-badge{background:#1d4ed8;color:#93c5fd;border-radius:.25rem;padding:.1rem .4rem;font-size:.7rem;margin-right:.4rem}
  input[type=text],input[type=time],select{background:#0f172a;border:1px solid #334155;color:#e2e8f0;padding:.4rem .6rem;border-radius:.375rem;font-size:.85rem}
  button.btn{background:#3b82f6;color:#fff;border:none;padding:.5rem 1rem;border-radius:.375rem;cursor:pointer;font-size:.875rem}
  button.btn:hover{background:#2563eb}
  button.btn-sm{padding:.25rem .6rem;font-size:.75rem}
  .rank-row{display:flex;align-items:center;gap:.75rem;padding:.4rem 0;border-bottom:1px solid #1e293b}
  .rank-num{color:#64748b;width:1.5rem;flex-shrink:0;font-size:.85rem}
  .rank-name{flex:1;font-size:.85rem}
  .rank-price{color:#22c55e;font-size:.8rem}
  .digest-entry{padding:.5rem 0;border-bottom:1px solid #334155;cursor:pointer;font-size:.85rem}
  .digest-detail{display:none;padding:.5rem;background:#0f172a;border-radius:.375rem;margin-top:.35rem}
  .digest-entry.open .digest-detail{display:block}
  .search-row{display:flex;gap:.5rem;margin-bottom:1rem;flex-wrap:wrap}
  .search-row input{flex:1;min-width:180px}
  footer{text-align:center;padding:1rem;color:#475569;font-size:.75rem}
</style>
</head>
<body>
<header>
  <h1>📰 News Feed Bot</h1>
  <span class="badge" id="health-badge">loading…</span>
</header>
<nav>
  <button class="active" onclick="showTab('source-health')">Source Health</button>
  <button onclick="showTab('news-timeline')">News Timeline</button>
  <button onclick="showTab('price-tracker')">AI Price Tracker</button>
  <button onclick="showTab('ai-leaderboard')">Leaderboard</button>
  <button onclick="showTab('digest-history')">Digest History</button>
  <button onclick="showTab('schedule-config')">Schedule Config</button>
</nav>
<main>
  <div id="source-health" class="section active">
    <div class="card"><h2>Articles per source (last 24h)</h2><canvas id="sourceChart" height="80"></canvas></div>
    <div class="card" id="source-status-list"><h2>Source Status</h2></div>
  </div>
  <div id="news-timeline" class="section">
    <div class="search-row">
      <input type="text" id="news-search" placeholder="Search articles…" oninput="filterNews()">
      <select id="news-source-filter" onchange="filterNews()"><option value="">All sources</option></select>
    </div>
    <div class="card" id="news-list"><h2>News Timeline</h2></div>
  </div>
  <div id="price-tracker" class="section">
    <div class="search-row">
      <select id="price-provider-filter" onchange="loadPrices()"><option value="">All providers</option></select>
      <select id="price-sort" onchange="loadPrices()">
        <option value="combined_asc">Combined ↑</option>
        <option value="prompt_asc">Prompt ↑</option>
        <option value="complete_asc">Completion ↑</option>
        <option value="prompt_desc">Prompt ↓</option>
      </select>
    </div>
    <div class="card"><table id="price-table"><thead><tr><th>Model</th><th>Provider</th><th>Prompt/1M</th><th>Completion/1M</th><th>Context</th></tr></thead><tbody></tbody></table></div>
  </div>
  <div id="ai-leaderboard" class="section">
    <div class="card"><h2>Top 10 Cheapest (by combined)</h2><div id="leaderboard-cheap"></div></div>
    <div class="card"><h2>Top 5 Most Expensive</h2><div id="leaderboard-expensive"></div></div>
  </div>
  <div id="digest-history" class="section">
    <div class="card"><h2>Past Digests</h2><div id="digest-list"></div></div>
  </div>
  <div id="schedule-config" class="section">
    <div class="card">
      <h2>Digest Times (Bangkok)</h2>
      <div id="digest-times-inputs"></div>
    </div>
    <div class="card">
      <h2>Enabled Sources</h2>
      <div id="source-toggles"></div>
    </div>
    <div class="card">
      <h2>Summarizer Model</h2>
      <label>Provider: <select id="cfg-provider"><option value="anthropic">Anthropic</option><option value="openrouter">OpenRouter</option></select></label>&nbsp;
      <label>Model: <input type="text" id="cfg-model" style="width:220px"></label>
    </div>
    <br>
    <button class="btn" onclick="saveSchedule()">Save Config</button>
    <span id="save-status" style="margin-left:.75rem;font-size:.85rem;color:#22c55e"></span>
  </div>
</main>
<footer id="footer-info">–</footer>
<script src="/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write `news-feed/app/static/app.js`**

```javascript
let allNews = [];
let allPrices = [];

async function api(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(r.status);
  return r.json();
}

function showTab(id) {
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('nav button').forEach(b => b.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  const tabs = ['source-health','news-timeline','price-tracker','ai-leaderboard','digest-history','schedule-config'];
  document.querySelectorAll('nav button')[tabs.indexOf(id)].classList.add('active');
  if (id === 'source-health') loadSourceHealth();
  if (id === 'news-timeline') loadNews();
  if (id === 'price-tracker') loadPrices();
  if (id === 'ai-leaderboard') loadLeaderboard();
  if (id === 'digest-history') loadDigestHistory();
  if (id === 'schedule-config') loadScheduleConfig();
}

async function loadHealth() {
  try {
    const h = await api('/api/health');
    const badge = document.getElementById('health-badge');
    badge.textContent = `${h.article_count} articles`;
    document.getElementById('footer-info').textContent =
      `Last fetch: ${h.last_fetch ? new Date(h.last_fetch+'Z').toLocaleString('th-TH') : 'never'}`;
  } catch(e) { document.getElementById('health-badge').textContent = 'error'; }
}

let sourceChart;
async function loadSourceHealth() {
  try {
    const news = await api('/api/news?limit=500');
    const counts = {};
    news.forEach(a => { counts[a.source] = (counts[a.source]||0)+1; });
    const labels = Object.keys(counts);
    const data = labels.map(k => counts[k]);
    if (sourceChart) sourceChart.destroy();
    sourceChart = new Chart(document.getElementById('sourceChart'), {
      type: 'bar',
      data: { labels, datasets: [{ label: 'Articles', data, backgroundColor: '#3b82f6' }] },
      options: { plugins: { legend: { display: false } }, scales: { x: { ticks: { color: '#94a3b8' } }, y: { ticks: { color: '#94a3b8' } } } },
    });
    const statusEl = document.getElementById('source-status-list');
    statusEl.innerHTML = '<h2>Source Status</h2>' + labels.map(s =>
      `<div style="padding:.35rem 0"><span class="dot green"></span>${s} <small style="color:#64748b">(${counts[s]} articles)</small></div>`
    ).join('');
  } catch(e) { console.error(e); }
}

async function loadNews() {
  allNews = await api('/api/news?limit=100');
  const sel = document.getElementById('news-source-filter');
  const sources = [...new Set(allNews.map(a=>a.source))];
  sel.innerHTML = '<option value="">All sources</option>' + sources.map(s=>`<option value="${s}">${s}</option>`).join('');
  renderNews(allNews);
}

function renderNews(articles) {
  const el = document.getElementById('news-list');
  if (!articles.length) { el.innerHTML = '<h2>News Timeline</h2><p style="color:#64748b;padding:.5rem 0">No articles</p>'; return; }
  el.innerHTML = '<h2>News Timeline</h2>' + articles.map(a => `
    <div class="article-card" onclick="this.classList.toggle('open')">
      <div class="article-title">${a.title}</div>
      <div class="article-meta"><span class="source-badge">${a.source}</span>${new Date(a.published).toLocaleString('th-TH')}</div>
      <div class="article-summary">${a.summary_th || '<em>Summarizing…</em>'}</div>
      <div style="margin-top:.25rem"><a href="${a.url}" target="_blank" style="color:#3b82f6;font-size:.75rem" onclick="event.stopPropagation()">อ่านต่อ ↗</a></div>
    </div>`).join('');
}

function filterNews() {
  const q = document.getElementById('news-search').value.toLowerCase();
  const src = document.getElementById('news-source-filter').value;
  renderNews(allNews.filter(a =>
    (!src || a.source === src) &&
    (!q || a.title.toLowerCase().includes(q) || (a.summary_th||'').toLowerCase().includes(q))
  ));
}

async function loadPrices() {
  const provider = document.getElementById('price-provider-filter').value;
  const sort = document.getElementById('price-sort').value;
  const params = new URLSearchParams({ sort });
  if (provider) params.set('provider', provider);
  allPrices = await api('/api/prices?' + params);
  if (!document.getElementById('price-provider-filter').options.length > 1) {
    const providers = [...new Set(allPrices.map(p=>p.provider))];
    const sel = document.getElementById('price-provider-filter');
    sel.innerHTML = '<option value="">All providers</option>' + providers.map(p=>`<option value="${p}">${p}</option>`).join('');
  }
  const tbody = document.querySelector('#price-table tbody');
  tbody.innerHTML = allPrices.map(p => `<tr>
    <td>${p.name}</td><td>${p.provider}</td>
    <td>$${(p.prompt_price||0).toFixed(3)}</td>
    <td>$${(p.complete_price||0).toFixed(3)}</td>
    <td>${p.context_length ? p.context_length.toLocaleString() : '–'}</td>
  </tr>`).join('');
}

async function loadLeaderboard() {
  const prices = await api('/api/prices?sort=combined_asc');
  const cheapEl = document.getElementById('leaderboard-cheap');
  cheapEl.innerHTML = prices.slice(0,10).map((p,i) => `
    <div class="rank-row">
      <span class="rank-num">${i+1}</span>
      <span class="rank-name">${p.name}<br><small style="color:#64748b">${p.model_id}</small></span>
      <span class="rank-price">$${((p.prompt_price||0)+(p.complete_price||0)).toFixed(3)}/1M</span>
    </div>`).join('');
  const expensive = [...prices].reverse().slice(0,5);
  const expEl = document.getElementById('leaderboard-expensive');
  expEl.innerHTML = expensive.map((p,i) => `
    <div class="rank-row">
      <span class="rank-num">${i+1}</span>
      <span class="rank-name">${p.name}<br><small style="color:#64748b">${p.model_id}</small></span>
      <span class="rank-price" style="color:#ef4444">$${((p.prompt_price||0)+(p.complete_price||0)).toFixed(3)}/1M</span>
    </div>`).join('');
}

async function loadDigestHistory() {
  const history = await api('/api/digest/history');
  const el = document.getElementById('digest-list');
  if (!history.length) { el.innerHTML = '<p style="color:#64748b">No digests sent yet</p>'; return; }
  el.innerHTML = history.map(d => `
    <div class="digest-entry" onclick="this.classList.toggle('open')">
      <span>${new Date(d.sent_at+'Z').toLocaleString('th-TH')}</span>
      <span style="color:#64748b;font-size:.75rem;margin-left:.5rem">${d.channels} · ${d.article_ids.length} articles</span>
      <div class="digest-detail">${d.article_ids.map(id=>`<div style="font-size:.8rem;color:#94a3b8">• ${id}</div>`).join('')}</div>
    </div>`).join('');
}

async function loadScheduleConfig() {
  const cfg = await api('/api/schedule');
  const timesEl = document.getElementById('digest-times-inputs');
  timesEl.innerHTML = (cfg.digest_times||[]).map((t,i) =>
    `<label style="margin-right:.75rem">Digest ${i+1}: <input type="time" value="${t}" data-idx="${i}" class="digest-time-input"></label>`
  ).join('');
  const allSources = ['techcrunch_ai','venturebeat','theverge','arstechnica','gsmarena','9to5mac','android_authority'];
  document.getElementById('source-toggles').innerHTML = allSources.map(s =>
    `<label style="display:inline-block;margin:.25rem .5rem">
      <input type="checkbox" value="${s}" ${(cfg.enabled_sources||[]).includes(s)?'checked':''}> ${s}
    </label>`).join('');
  document.getElementById('cfg-provider').value = cfg.summarizer_provider || 'anthropic';
  document.getElementById('cfg-model').value = cfg.summarizer_model || '';
}

async function saveSchedule() {
  const times = [...document.querySelectorAll('.digest-time-input')].map(i=>i.value).filter(Boolean);
  const sources = [...document.querySelectorAll('#source-toggles input:checked')].map(i=>i.value);
  const provider = document.getElementById('cfg-provider').value;
  const model = document.getElementById('cfg-model').value;
  await fetch('/api/schedule', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ digest_times: times, enabled_sources: sources, summarizer_provider: provider, summarizer_model: model }),
  });
  document.getElementById('save-status').textContent = '✓ Saved';
  setTimeout(()=>document.getElementById('save-status').textContent='', 2000);
}

// Init
loadHealth();
loadSourceHealth();
```

- [ ] **Step 3: Start dev server and verify dashboard loads**

```bash
cd news-feed && DATA_DIR=/tmp/nf-test uvicorn app.main:app --port 8064 --reload
```

Open `http://localhost:8064` in browser. Verify:
- All 6 nav tabs render without JS errors
- Health badge shows article count
- Schedule Config loads and Save works (POST /api/schedule returns 200)

- [ ] **Step 4: Commit**

```bash
git add news-feed/app/static/
git commit -m "feat(news-feed): add static dashboard with 6 sections"
```

---

## Task 13: Dockerfile, docker-compose, .env.example, README

**Files:**
- Create: `news-feed/Dockerfile`
- Create: `news-feed/docker-compose.yml`
- Create: `news-feed/.env.example`
- Create: `news-feed/README.md`

- [ ] **Step 1: Write `news-feed/Dockerfile`**

```dockerfile
FROM python:3.12-slim

RUN groupadd -g 1000 app && useradd -u 1000 -g app -s /bin/sh app

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

USER app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Write `news-feed/docker-compose.yml`**

```yaml
services:
  news-feed:
    build: .
    container_name: news-feed
    restart: unless-stopped
    ports:
      - "5064:8000"
    env_file: .env
    environment:
      - TZ=Asia/Bangkok
    volumes:
      - news_feed_data:/data

volumes:
  news_feed_data:
```

- [ ] **Step 3: Write `news-feed/.env.example`**

```bash
# Anthropic Claude API
ANTHROPIC_API_KEY=sk-ant-...

# LINE Messaging API (push to single user)
LINE_CHANNEL_ACCESS_TOKEN=...
LINE_USER_ID=U...

# Telegram Bot
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...

# Admin token for POST /api/digest/trigger
ADMIN_TOKEN=changeme

# Summarizer: "anthropic" or "openrouter"
SUMMARIZER_PROVIDER=anthropic
SUMMARIZER_MODEL=claude-sonnet-4-6
# Only needed if SUMMARIZER_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-...

# Digest schedule (Bangkok time, comma-separated HH:MM)
DIGEST_TIMES=07:00,12:00,18:00

# Enabled sources (comma-separated keys)
ENABLED_SOURCES=techcrunch_ai,venturebeat,theverge,arstechnica,gsmarena,9to5mac,android_authority

# Data directory (inside container)
DATA_DIR=/data
```

- [ ] **Step 4: Write `news-feed/README.md`**

```markdown
# news-feed

AI & IT news feed bot with Thai summaries. Fetches RSS from 7 sources, summarises via Claude or DeepSeek (OpenRouter), sends digest to LINE + Telegram, serves a dashboard at port 5064.

## Setup

1. Copy and fill env:
   ```bash
   cp .env.example .env
   ```

2. Fill in `.env`: at minimum `ANTHROPIC_API_KEY` (or `OPENROUTER_API_KEY` + set `SUMMARIZER_PROVIDER=openrouter`), `LINE_CHANNEL_ACCESS_TOKEN`, `LINE_USER_ID`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

3. Deploy:
   ```bash
   scripts/deploy.sh -s news-feed
   ```

## Dashboard

`http://<NAS_HOST>:5064` — Source Health, News Timeline, AI Price Tracker, Leaderboard, Digest History, Schedule Config.

## Switch LLM Model

Via dashboard → Schedule Config → set Provider + Model → Save.
Or via API:
```bash
curl -X POST http://<NAS_HOST>:5064/api/schedule \
  -H 'Content-Type: application/json' \
  -d '{"summarizer_provider":"openrouter","summarizer_model":"deepseek/deepseek-chat"}'
```

## Manual Digest Trigger

```bash
curl -X POST http://<NAS_HOST>:5064/api/digest/trigger \
  -H "X-Admin-Token: <ADMIN_TOKEN>"
```
```

- [ ] **Step 5: Build and run Docker container locally**

```bash
cd news-feed
cp .env.example .env   # fill in real values
docker compose build
docker compose up -d
curl http://localhost:5064/api/health
```

Expected: `{"status":"ok","article_count":0,"last_fetch":null}`

- [ ] **Step 6: Commit**

```bash
git add news-feed/Dockerfile news-feed/docker-compose.yml news-feed/.env.example news-feed/README.md
git commit -m "feat(news-feed): add Dockerfile, compose, env.example, README"
```

---

## Task 14: CLAUDE.md Update + Deploy

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add news-feed row to CLAUDE.md ports table**

Find the table row for `torrentwatch/` in `CLAUDE.md` and add a new row after it:

```
| `news-feed/` | AI & IT News Feed Bot + Dashboard | 5064 / — | Single container: FastAPI + APScheduler + SQLite. Summariser switchable via dashboard (Anthropic default, OpenRouter/DeepSeek option). Digest sent to LINE + Telegram at 07:00/12:00/18:00. |
```

- [ ] **Step 2: Run full test suite one final time**

```bash
cd news-feed && python -m pytest tests/ -v --tb=short
```

Expected: all tests pass.

- [ ] **Step 3: Commit CLAUDE.md update**

```bash
git add CLAUDE.md
git commit -m "docs: add news-feed stack to CLAUDE.md ports table"
```

- [ ] **Step 4: Deploy to NAS**

```bash
scripts/deploy.sh -s news-feed
```

- [ ] **Step 5: Verify on NAS**

```bash
ssh <NAS_HOST> "docker logs news-feed --tail 20"
curl http://<NAS_HOST>:5064/api/health
```

Expected: logs show scheduler started, health endpoint returns `{"status":"ok",...}`.

- [ ] **Step 6: Final commit if any last fixes**

```bash
git add -p
git commit -m "fix(news-feed): <describe any fixes>"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|-----------------|------|
| RSS from 7 sources | Task 4 (fetcher.py) |
| Scrape AI pricing from openrouter.ai | Task 6 (pricer.py) |
| Summarize in Thai via Claude API | Task 5 (summarizer.py) |
| Schedule digest 07:00/12:00/18:00 | Task 8 (scheduler.py) |
| Push to LINE + Telegram | Task 7 (notifier.py) |
| Dashboard: Source Health | Task 12 (app.js loadSourceHealth) |
| Dashboard: News Timeline + search | Task 12 (app.js loadNews/filterNews) |
| Dashboard: AI Price Tracker | Task 12 (app.js loadPrices) |
| Dashboard: AI Leaderboard | Task 12 (app.js loadLeaderboard) |
| Dashboard: Digest History | Task 12 (app.js loadDigestHistory) |
| Dashboard: Schedule Config | Task 12 (app.js loadScheduleConfig/saveSchedule) |
| Switch LLM provider at runtime | Task 5 + Task 10 (POST /api/schedule) + Task 12 |
| schedule.json persist across restarts | Task 2 (config.py update_config) |
| CLAUDE.md updated | Task 14 |
| .env.example | Task 13 |
| README | Task 13 |

All spec requirements covered. No placeholders. Type consistency verified (all function signatures match across tasks).
