# TorrentWatch Source Reorder + Size Badge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add ↑↓ reorder buttons for sources in Settings (persisted in DB) and replace inline file-size text with a color-coded badge on every torrent card.

**Architecture:** Feature 1 adds a `sort_order` INTEGER column to `sources`, a `reorder_source()` DB function, and a `POST /api/sources/{id}/reorder` endpoint; the frontend calls it from new ↑↓ buttons in `renderSourcesList()`. Feature 2 is pure frontend: a `sizeClass()` helper classifies size strings into three tiers and `cardHTML()` wraps `file_size` in a styled badge instead of plain text. No schema change for Feature 2.

**Tech Stack:** Python 3.12 · FastAPI · SQLite (WAL) · Pydantic · Vanilla JS · Bootstrap Icons · CSS custom properties

---

## File Map

| File | What changes |
|---|---|
| `torrentwatch/db.py` | Migration adds `sort_order`; backfill; `get_sources()` + `get_enabled_sources()` sort by it; `add_source()` sets `MAX+1`; new `reorder_source()` |
| `torrentwatch/main.py` | New `SourceReorder` model + `POST /api/sources/{source_id}/reorder` endpoint |
| `torrentwatch/static/app.js` | `renderSourcesList()` template gets ↑↓ buttons + handler; new `sizeClass()` helper; `cardHTML()` size badge replaces stat text |
| `torrentwatch/static/style.css` | Four new `.tw-badge-size*` rules |

---

## Task 1: DB — sort_order migration + reorder logic

**Files:**
- Modify: `torrentwatch/db.py:106-118` (migration block), `db.py:138-147` (get_sources + add_source)

- [ ] **Step 1: Add `sort_order` to the migration block in `init_db()`**

In `db.py`, find the `for col_sql in [...]` loop (lines 106-118) and add the new column entry plus a backfill statement immediately after the loop:

```python
        # Migrate: add new columns if missing (existing installs)
        for col_sql in [
            "ALTER TABLE sources ADD COLUMN label TEXT DEFAULT ''",
            "ALTER TABLE sources ADD COLUMN sort_order INTEGER DEFAULT 0",
            "ALTER TABLE torrents ADD COLUMN posted_at   TEXT DEFAULT ''",
            "ALTER TABLE torrents ADD COLUMN category    TEXT DEFAULT ''",
            "ALTER TABLE torrents ADD COLUMN file_count  INTEGER DEFAULT 0",
            "ALTER TABLE torrents ADD COLUMN file_size   TEXT DEFAULT ''",
            "ALTER TABLE torrents ADD COLUMN completed   INTEGER DEFAULT 0",
            "ALTER TABLE torrents ADD COLUMN is_sticky   INTEGER DEFAULT 0",
        ]:
            try:
                c.execute(col_sql)
            except Exception:
                pass

        # Backfill sort_order for sources added before this migration
        c.execute("UPDATE sources SET sort_order = id WHERE sort_order = 0")
```

- [ ] **Step 2: Update `get_sources()` to order by `sort_order`**

Replace the current `ORDER BY id` query (line 140):

```python
def get_sources() -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM sources ORDER BY sort_order ASC, id ASC"
        ).fetchall()]
```

- [ ] **Step 3: Update `get_enabled_sources()` to order by `sort_order`**

Replace the current `ORDER BY id` query (line 214):

```python
def get_enabled_sources() -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM sources WHERE enabled = 1 ORDER BY sort_order ASC, id ASC"
        ).fetchall()]
```

- [ ] **Step 4: Update `add_source()` to assign `MAX(sort_order) + 1`**

Replace the current `add_source()` (lines 143-147):

```python
def add_source(url: str) -> dict:
    with _conn() as c:
        max_order = c.execute(
            "SELECT COALESCE(MAX(sort_order), 0) FROM sources"
        ).fetchone()[0]
        c.execute(
            "INSERT INTO sources(url, enabled, sort_order, created_at) VALUES (?, 1, ?, ?)",
            (url, max_order + 1, _now())
        )
        row = c.execute("SELECT * FROM sources WHERE url = ?", (url,)).fetchone()
        return dict(row)
```

- [ ] **Step 5: Add `reorder_source()` after `rename_source()`**

Insert this new function after the `rename_source()` function (after line 162):

```python
def reorder_source(source_id: int, direction: str):
    """Swap sort_order with the nearest neighbor in the given direction."""
    with _conn() as c:
        current = c.execute(
            "SELECT id, sort_order FROM sources WHERE id = ?", (source_id,)
        ).fetchone()
        if not current:
            return
        cur_order = current["sort_order"]
        if direction == "up":
            neighbor = c.execute(
                "SELECT id, sort_order FROM sources WHERE sort_order < ? ORDER BY sort_order DESC LIMIT 1",
                (cur_order,)
            ).fetchone()
        else:
            neighbor = c.execute(
                "SELECT id, sort_order FROM sources WHERE sort_order > ? ORDER BY sort_order ASC LIMIT 1",
                (cur_order,)
            ).fetchone()
        if not neighbor:
            return
        c.execute("UPDATE sources SET sort_order = ? WHERE id = ?", (neighbor["sort_order"], source_id))
        c.execute("UPDATE sources SET sort_order = ? WHERE id = ?", (cur_order, neighbor["id"]))
```

- [ ] **Step 6: Verify DB logic with a quick script**

Run from the `torrentwatch/` directory (no Docker needed — uses a temp DB):

```bash
cd /Users/peerawat.ujaiyen/MyCode/centralized-nas-container-management/torrentwatch
python3 - <<'EOF'
import os, sys
os.environ.setdefault("DATA_DIR", "/tmp/tw_test")
os.environ.setdefault("TZ", "Asia/Bangkok")
os.environ.setdefault("SITE_BASE_URL", "http://example.com")
os.environ.setdefault("SITE_USERNAME", "x")
os.environ.setdefault("SITE_PASSWORD", "x")
os.environ.setdefault("DEFAULT_URLS", "")
os.environ.setdefault("NAS_DOWNLOADS_DIR", "/tmp")
os.environ.setdefault("BASIC_AUTH_USER", "")
os.environ.setdefault("BASIC_AUTH_PASS", "")
os.makedirs("/tmp/tw_test", exist_ok=True)
import config
config.DB_PATH = "/tmp/tw_test/test.db"
import db
db.init_db()
db.add_source("http://example.com/a")
db.add_source("http://example.com/b")
db.add_source("http://example.com/c")
sources = db.get_sources()
print("initial order:", [(s["url"][-1], s["sort_order"]) for s in sources])
# a=1,b=2,c=3  (or similar ascending)
db.reorder_source(sources[0]["id"], "down")  # move 'a' down → b,a,c
sources = db.get_sources()
print("after moving first down:", [s["url"][-1] for s in sources])
assert sources[0]["url"][-1] == "b", f"expected b first, got {sources[0]['url'][-1]}"
db.reorder_source(sources[2]["id"], "up")    # move 'c' up → b,c,a
sources = db.get_sources()
print("after moving last up:", [s["url"][-1] for s in sources])
assert sources[1]["url"][-1] == "c", f"expected c second, got {sources[1]['url'][-1]}"
print("ALL ASSERTIONS PASSED")
import os; os.unlink("/tmp/tw_test/test.db")
EOF
```

Expected output:
```
initial order: [('a', 1), ('b', 2), ('c', 3)]
after moving first down: ['b', 'a', 'c']
after moving last up: ['b', 'c', 'a']
ALL ASSERTIONS PASSED
```

- [ ] **Step 7: Commit**

```bash
git add torrentwatch/db.py
git commit -m "feat(torrentwatch): add sort_order to sources — migration, backfill, reorder_source()"
```

---

## Task 2: API — POST /api/sources/{id}/reorder

**Files:**
- Modify: `torrentwatch/main.py:67-103` (Sources section)

- [ ] **Step 1: Add `SourceReorder` model and endpoint to `main.py`**

After the existing `SourceRename` model and `api_rename_source` endpoint (after line 102), add:

```python
class SourceReorder(BaseModel):
    direction: str  # "up" or "down"

@app.post("/api/sources/{source_id}/reorder")
def api_reorder_source(source_id: int, body: SourceReorder):
    if body.direction not in ("up", "down"):
        raise HTTPException(400, "direction must be 'up' or 'down'")
    db.reorder_source(source_id, body.direction)
    return db.get_sources()
```

- [ ] **Step 2: Verify endpoint with curl (against running container or local uvicorn)**

If running locally without Docker:
```bash
cd /Users/peerawat.ujaiyen/MyCode/centralized-nas-container-management/torrentwatch
# Start server in background (skip if already running)
uvicorn main:app --port 5059 &
sleep 2

# Get current sources to find an ID
curl -s http://localhost:5059/api/sources | python3 -m json.tool

# Move source ID 1 down (replace 1 with a real ID from above)
curl -s -X POST http://localhost:5059/api/sources/1/reorder \
  -H "Content-Type: application/json" \
  -d '{"direction":"down"}' | python3 -m json.tool

# Verify order changed — first source in list should now be the previous second
curl -s http://localhost:5059/api/sources | python3 -c "import sys,json; srcs=json.load(sys.stdin); [print(s['id'], s.get('sort_order'), s['url'][-30:]) for s in srcs]"

# Test invalid direction
curl -s -X POST http://localhost:5059/api/sources/1/reorder \
  -H "Content-Type: application/json" \
  -d '{"direction":"sideways"}' -o /dev/null -w "%{http_code}\n"
# Expected: 400
```

- [ ] **Step 3: Commit**

```bash
git add torrentwatch/main.py
git commit -m "feat(torrentwatch): add POST /api/sources/{id}/reorder endpoint"
```

---

## Task 3: Frontend — ↑↓ reorder buttons in Settings

**Files:**
- Modify: `torrentwatch/static/app.js:488-563` (`renderSourcesList` function)

- [ ] **Step 1: Add ↑↓ buttons to the source row template in `renderSourcesList()`**

Replace the `list.innerHTML = sources.map(s => \`...\`).join("")` block (lines 494-506) with:

```js
  list.innerHTML = sources.map((s, i) => `
    <div class="tw-source-item" data-src-id="${s.id}">
      <div style="display:flex;flex-direction:column;gap:2px">
        <button class="tw-btn-icon src-reorder" data-src-id="${s.id}" data-direction="up" title="ขึ้น" ${i === 0 ? "disabled" : ""}><i class="bi bi-chevron-up"></i></button>
        <button class="tw-btn-icon src-reorder" data-src-id="${s.id}" data-direction="down" title="ลง" ${i === sources.length - 1 ? "disabled" : ""}><i class="bi bi-chevron-down"></i></button>
      </div>
      <label class="tw-toggle-row" style="flex:1;gap:8px;margin:0">
        <input type="checkbox" class="tw-toggle src-toggle" data-src-id="${s.id}" ${s.enabled ? "checked" : ""}>
      </label>
      <div class="tw-source-label-wrap">
        <span class="tw-source-display-label">${escHtml(sourceLabel(s))}</span>
        <span class="tw-source-url-hint" title="${escHtml(s.url)}">${escHtml(s.url)}</span>
      </div>
      <button class="tw-btn-icon src-rename" data-src-id="${s.id}" data-label="${escHtml(s.label || "")}" title="เปลี่ยนชื่อ"><i class="bi bi-pencil"></i></button>
      <button class="tw-btn-icon src-reset" data-src-id="${s.id}" title="ล้างข้อมูลทั้งหมดของ source นี้"><i class="bi bi-arrow-counterclockwise"></i></button>
      <button class="tw-btn-danger src-del" data-src-id="${s.id}"><i class="bi bi-trash3"></i></button>
    </div>`).join("");
```

- [ ] **Step 2: Add event handler for `.src-reorder` buttons**

After the `list.querySelectorAll(".src-toggle")` block (after the closing `});` on line ~513), add:

```js
  list.querySelectorAll(".src-reorder").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (btn.disabled) return;
      try {
        await api("POST", `/sources/${btn.dataset.srcId}/reorder`, { direction: btn.dataset.direction });
        await loadSources();
        loadSettings();
      } catch (e) {
        toast("เรียงลำดับไม่สำเร็จ: " + e.message, "error");
      }
    });
  });
```

- [ ] **Step 3: Verify in browser**

Open Settings tab. Confirm:
- Each source row has ↑ and ↓ chevron buttons at the left
- First source: ↑ is disabled (visually dimmed)
- Last source: ↓ is disabled
- Clicking ↓ on first source swaps it with second; source chips in Today/History/Keywords tabs reorder immediately
- Refreshing the page preserves the new order

- [ ] **Step 4: Commit**

```bash
git add torrentwatch/static/app.js
git commit -m "feat(torrentwatch): source reorder ↑↓ buttons in Settings"
```

---

## Task 4: Size badge — colored, bold, large

**Files:**
- Modify: `torrentwatch/static/style.css` (after `.tw-badge-info` rule, line 420)
- Modify: `torrentwatch/static/app.js` (before `cardHTML()`, line 241; inside `cardHTML()`, line 257)

- [ ] **Step 1: Add size badge CSS to `style.css`**

After the `.tw-badge-info` rule (line 420 — `background: #1e293b; color: #94a3b8; }`), add:

```css
.tw-badge-size    { font-size: 12px; font-weight: 700; padding: 2px 7px; }
.tw-badge-size-sm { background: rgba(107,114,128,0.15); color: #9ca3af; }
.tw-badge-size-md { background: rgba(245,158,11,0.15);  color: #f59e0b; }
.tw-badge-size-lg { background: rgba(239,68,68,0.15);   color: #ef4444; }
```

- [ ] **Step 2: Add `sizeClass()` helper to `app.js`**

Add this function immediately before the `// ─── Torrent card renderer` comment (before line 230):

```js
// ─── Size badge helper ────────────────────────────────────────────────────────
function sizeClass(s) {
  if (!s) return "tw-badge-size-sm";
  const m = s.match(/([\d.]+)\s*(GB|MB|KB)/i);
  if (!m) return "tw-badge-size-sm";
  if (/MB|KB/i.test(m[2])) return "tw-badge-size-sm";
  const gb = parseFloat(m[1]);
  if (gb >= 5) return "tw-badge-size-lg";
  if (gb >= 1) return "tw-badge-size-md";
  return "tw-badge-size-sm";
}
```

- [ ] **Step 3: Replace inline file_size stat with badge in `cardHTML()`**

In `cardHTML()`, find the `file_size` line inside the `statsHTML` array (line 257):

```js
    t.file_size ? `<span class="tw-stat-sep">·</span><span class="tw-stat-lbl">${escHtml(t.file_size)}</span>` : "",
```

Replace it with:

```js
    t.file_size ? `<span class="tw-badge tw-badge-size ${sizeClass(t.file_size)}">${escHtml(t.file_size)}</span>` : "",
```

- [ ] **Step 4: Verify in browser**

Open Today tab. Confirm:
- Torrents with MB size (e.g. "380.60 MB") show a gray badge
- Torrents with 1–4.9 GB show an amber/yellow badge
- Torrents with ≥5 GB show a red badge
- Badge text is bold and clearly larger than the surrounding seed/leech labels
- Badge appears on History tab too (same `cardHTML()` function)
- Cards with no `file_size` show nothing (no empty badge)

- [ ] **Step 5: Commit**

```bash
git add torrentwatch/static/style.css torrentwatch/static/app.js
git commit -m "feat(torrentwatch): file size colored badge — gray/amber/red by tier"
```

---

## Self-Review Checklist

- [x] **spec coverage** — Task 1-2 cover Feature 1 (DB + API); Task 3 covers Feature 1 frontend; Task 4 covers Feature 2 entirely
- [x] **no placeholders** — every step has exact code
- [x] **type consistency** — `reorder_source(source_id, direction)` matches across Task 1 step 5, Task 2 step 1, and Task 3 step 2; `sizeClass()` defined in Task 4 step 2 and used in Task 4 step 3
- [x] **backfill handles existing data** — `WHERE sort_order = 0` backfill in Task 1 step 1 runs after `ALTER TABLE ADD COLUMN DEFAULT 0`, so all pre-existing rows get `sort_order = id`
- [x] **add_source uses MAX+1** — new sources go to bottom of the list, not sort_order=0
- [x] **disabled state on first/last** — template in Task 3 step 1 uses `i === 0` and `i === sources.length - 1`
