# TorrentWatch Sticky Notification Toggle — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a single Settings toggle that sends LINE + Telegram notifications whenever a brand-new sticky/pinned/auto-sticky torrent is first discovered during a scrape cycle.

**Architecture:** New DB setting `notify_sticky_enabled` drives the feature. Scheduler collects `new_sticky_entries` (is_new=True AND is_sticky=True) alongside existing keyword matches, then calls new `notify_sticky_new()` functions in line_notify.py and telegram_notify.py. Channels send if their env vars are configured — independent of the keyword notify toggles. UI adds one checkbox in the Notification card.

**Tech Stack:** Python 3.12 · FastAPI · SQLite · httpx async · Vanilla JS

---

## File Map

| File | Change |
|---|---|
| `torrentwatch/db.py` | Add `notify_sticky_enabled: "0"` to `_DEFAULT_SETTINGS` |
| `torrentwatch/line_notify.py` | Add `notify_sticky_new(source_url, entries)` function |
| `torrentwatch/telegram_notify.py` | Add `notify_sticky_new(source_url, entries)` function |
| `torrentwatch/scheduler.py` | Read setting, collect sticky entries, call notify functions |
| `torrentwatch/static/index.html` | Add toggle row in Notification card |
| `torrentwatch/static/app.js` | Wire `cfg-sticky-notify` in `loadSettings()` + `saveSettings()` |

---

## Task 1: Add DB setting

**Files:**
- Modify: `torrentwatch/db.py` lines 11–23

- [ ] **Step 1: Add default setting**

In `torrentwatch/db.py`, insert the new key into `_DEFAULT_SETTINGS` after `telegram_notify_keyword_enabled`:

```python
_DEFAULT_SETTINGS = {
    "seed_min":                        "10",
    "leech_min":                       "10",
    "completed_min":                   "20",
    "filter_mode":                     "or",
    "scrape_sticky":                   "1",
    "line_notify_keyword_enabled":     "0",
    "telegram_notify_keyword_enabled": "0",
    "notify_sticky_enabled":           "0",   # "1" = push notify when a new sticky torrent is first seen
    "auto_download_nas":               "0",
    "retention_days":                  "7",
    "scrape_interval_night":           "30",
    "scrape_interval_day":             "60",
}
```

- [ ] **Step 2: Verify setting is seeded**

```bash
cd torrentwatch
python3 -c "
import db
db.init_db()
s = db.get_settings()
print('notify_sticky_enabled:', repr(s.get('notify_sticky_enabled')))
"
```

Expected output:
```
notify_sticky_enabled: '0'
```

- [ ] **Step 3: Commit**

```bash
git add torrentwatch/db.py
git commit -m "feat(torrentwatch): add notify_sticky_enabled setting to DB defaults"
```

---

## Task 2: Add `notify_sticky_new()` to line_notify.py

**Files:**
- Modify: `torrentwatch/line_notify.py`

- [ ] **Step 1: Add function after `notify_keyword_matches()`**

In `torrentwatch/line_notify.py`, add the following function after the `notify_keyword_matches` function (after line 50):

```python
async def notify_sticky_new(source_url: str, entries: list[dict]):
    """Push when new sticky/pinned torrents are first discovered."""
    if not entries:
        return
    from urllib.parse import urlparse
    label = urlparse(source_url).path.split("/")[-1] or source_url

    lines = [f"📌 Sticky ใหม่! — {label}\n"]
    for t in entries[:10]:
        lines.append(f"🎬 {t['title']}\n   🌱{t['seeds']}  📥{t['leeches']}")
    if len(entries) > 10:
        lines.append(f"...และอีก {len(entries) - 10} รายการ")
    lines.append(f"\n🕒 {_now()}")
    await _push("\n".join(lines))
```

- [ ] **Step 2: Verify syntax**

```bash
cd torrentwatch
python3 -c "import line_notify; print('line_notify OK')"
```

Expected output:
```
line_notify OK
```

- [ ] **Step 3: Commit**

```bash
git add torrentwatch/line_notify.py
git commit -m "feat(torrentwatch): add notify_sticky_new() to line_notify"
```

---

## Task 3: Add `notify_sticky_new()` to telegram_notify.py

**Files:**
- Modify: `torrentwatch/telegram_notify.py`

- [ ] **Step 1: Add function after `notify_keyword_matches()`**

In `torrentwatch/telegram_notify.py`, add the following function after the `notify_keyword_matches` function (after line 45):

```python
async def notify_sticky_new(source_url: str, entries: list[dict]):
    """Push when new sticky/pinned torrents are first discovered."""
    if not entries:
        return
    from urllib.parse import urlparse
    label = urlparse(source_url).path.split("/")[-1] or source_url

    lines = [f"📌 Sticky ใหม่! — {label}\n"]
    for t in entries[:10]:
        lines.append(f"🎬 {t['title']}\n   🌱{t['seeds']}  📥{t['leeches']}")
    if len(entries) > 10:
        lines.append(f"...และอีก {len(entries) - 10} รายการ")
    lines.append(f"\n🕒 {_now()}")
    await _send("\n".join(lines))
```

- [ ] **Step 2: Verify syntax**

```bash
cd torrentwatch
python3 -c "import telegram_notify; print('telegram_notify OK')"
```

Expected output:
```
telegram_notify OK
```

- [ ] **Step 3: Commit**

```bash
git add torrentwatch/telegram_notify.py
git commit -m "feat(torrentwatch): add notify_sticky_new() to telegram_notify"
```

---

## Task 4: Wire sticky notification in scheduler.py

**Files:**
- Modify: `torrentwatch/scheduler.py` — `_do_scrape()` function

- [ ] **Step 1: Read the setting alongside existing settings**

In `_do_scrape()`, find the block that reads settings (around line 57–65). Add `notify_sticky_enabled` read after `auto_dl`:

```python
    settings      = db.get_settings()
    seed_min      = int(settings.get("seed_min", 5))
    leech_min     = int(settings.get("leech_min", 10))
    completed_min = int(settings.get("completed_min", 20))
    filter_mode   = settings.get("filter_mode", "and")
    scrape_sticky_val = settings.get("scrape_sticky", "0")
    skip_sticky  = scrape_sticky_val != "1"
    line_notify_enabled     = settings.get("line_notify_keyword_enabled", "0") == "1"
    telegram_notify_enabled = settings.get("telegram_notify_keyword_enabled", "0") == "1"
    notify_sticky_enabled   = settings.get("notify_sticky_enabled", "0") == "1"
    auto_dl      = settings.get("auto_download_nas", "0") == "1"
    nas_dir      = Path(config.NAS_DOWNLOADS_DIR)
```

- [ ] **Step 2: Collect new sticky entries in the upsert loop**

Find the per-source upsert loop (around line 99–106). Add `new_sticky_entries` list initialisation before the loop and collection inside it:

```python
            new_keyword_matches: list[dict] = []
            new_sticky_entries:  list[dict] = []
            for entry in entries:
                try:
                    is_new, torrent_id = db.upsert_torrent(source_id, entry["site_id"], entry)
                    if is_new and entry.get("keyword_match"):
                        new_keyword_matches.append({**entry, "id": torrent_id})
                    if is_new and entry.get("is_sticky"):
                        new_sticky_entries.append({**entry, "id": torrent_id})
                except Exception as e:
                    print(f"[scheduler] upsert error {source_url} site_id={entry.get('site_id')}: {e}")
```

- [ ] **Step 3: Add sticky notify call after keyword notify calls**

After the existing Telegram keyword notify block (around line 129), add:

```python
            # Push sticky notification for newly-found sticky torrents
            try:
                if notify_sticky_enabled and new_sticky_entries:
                    line_on = bool(config.LINE_ACCESS_TOKEN and config.LINE_USER_ID)
                    tg_on   = bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)
                    if line_on:
                        await line_notify.notify_sticky_new(source_url, new_sticky_entries)
                    if tg_on:
                        await telegram_notify.notify_sticky_new(source_url, new_sticky_entries)
            except Exception as e:
                print(f"[scheduler] sticky notify error {source_url}: {e}")
```

- [ ] **Step 4: Verify syntax**

```bash
cd torrentwatch
python3 -c "import scheduler; print('scheduler OK')"
```

Expected output:
```
scheduler OK
```

- [ ] **Step 5: Commit**

```bash
git add torrentwatch/scheduler.py
git commit -m "feat(torrentwatch): collect and notify new sticky entries in scheduler"
```

---

## Task 5: Add toggle to Settings UI

**Files:**
- Modify: `torrentwatch/static/index.html`
- Modify: `torrentwatch/static/app.js`

- [ ] **Step 1: Add toggle row to index.html**

In `torrentwatch/static/index.html`, find the Auto-DL row and its hint paragraph in the Notification card (around line 206–213):

```html
            <div class="tw-field-row" style="margin-top:14px">
              <label for="cfg-auto-dl">Auto-DL to NAS</label>
              <label class="tw-toggle-row">
                <input type="checkbox" class="tw-toggle" id="cfg-auto-dl">
              </label>
            </div>
            <p class="tw-hint">บันทึก keyword match ไป NAS อัตโนมัติ</p>
```

Add the sticky notify toggle **after** that block:

```html
            <div class="tw-field-row" style="margin-top:14px">
              <label for="cfg-auto-dl">Auto-DL to NAS</label>
              <label class="tw-toggle-row">
                <input type="checkbox" class="tw-toggle" id="cfg-auto-dl">
              </label>
            </div>
            <p class="tw-hint">บันทึก keyword match ไป NAS อัตโนมัติ</p>

            <div class="tw-field-row" style="margin-top:14px">
              <label for="cfg-sticky-notify">📌 Sticky Notify</label>
              <label class="tw-toggle-row">
                <input type="checkbox" class="tw-toggle" id="cfg-sticky-notify">
              </label>
            </div>
            <p class="tw-hint">แจ้งเตือนเมื่อพบ sticky/pinned ใหม่ (ผ่าน LINE + Telegram ที่ตั้งค่าไว้)</p>
```

- [ ] **Step 2: Wire toggle in loadSettings() in app.js**

In `torrentwatch/static/app.js`, find the `loadSettings()` function. After the line that sets `cfg-telegram-notify` (line 589), add:

```javascript
  document.getElementById("cfg-sticky-notify").checked = settings.notify_sticky_enabled === "1";
```

So the block reads:
```javascript
  document.getElementById("cfg-line-notify").checked = settings.line_notify_keyword_enabled === "1";
  document.getElementById("cfg-telegram-notify").checked = settings.telegram_notify_keyword_enabled === "1";
  document.getElementById("cfg-sticky-notify").checked = settings.notify_sticky_enabled === "1";
```

- [ ] **Step 3: Wire toggle in saveSettings() in app.js**

In `torrentwatch/static/app.js`, find the `btn-save-settings` click handler payload (around line 750–762). After the `auto_download_nas` line, add:

```javascript
    notify_sticky_enabled:           document.getElementById("cfg-sticky-notify").checked ? "1" : "0",
```

So the payload block reads:
```javascript
  const payload = {
    seed_min:                    document.getElementById("cfg-seed-min").value,
    leech_min:                   document.getElementById("cfg-leech-min").value,
    completed_min:               document.getElementById("cfg-completed-min").value,
    filter_mode:                 document.querySelector('input[name="filter_mode"]:checked')?.value ?? "and",
    scrape_sticky:               document.getElementById("cfg-scrape-sticky").checked ? "1" : "0",
    line_notify_keyword_enabled:     document.getElementById("cfg-line-notify").checked ? "1" : "0",
    telegram_notify_keyword_enabled: document.getElementById("cfg-telegram-notify").checked ? "1" : "0",
    auto_download_nas:               document.getElementById("cfg-auto-dl").checked ? "1" : "0",
    notify_sticky_enabled:           document.getElementById("cfg-sticky-notify").checked ? "1" : "0",
    retention_days:              document.getElementById("cfg-retention").value,
    scrape_interval_night:       document.getElementById("cfg-interval-night").value,
    scrape_interval_day:         document.getElementById("cfg-interval-day").value,
  };
```

- [ ] **Step 4: Update cache-busting version string in index.html and app.js**

In `torrentwatch/static/index.html` line 27, change the version string:
```html
  <link rel="stylesheet" href="/static/style.css?v=20260520c">
```

In `torrentwatch/static/index.html` line 353, change the app.js version:
```html
  <script src="/static/app.js?v=20260520c"></script>
```

- [ ] **Step 5: Verify in browser**

Start the app locally (or deploy) and:
1. Open Settings → Notification card
2. Confirm "📌 Sticky Notify" toggle appears below Auto-DL
3. Toggle it ON and click "บันทึกการตั้งค่า"
4. Reload the page — toggle should remain ON
5. Toggle it OFF and save again — reload and confirm OFF

- [ ] **Step 6: Commit**

```bash
git add torrentwatch/static/index.html torrentwatch/static/app.js
git commit -m "feat(torrentwatch): add sticky notify toggle to Settings UI"
```

---

## Task 6: Final integration verification + notes update

- [ ] **Step 1: Full import check**

```bash
cd torrentwatch
python3 -c "
import db, scheduler, line_notify, telegram_notify
db.init_db()
s = db.get_settings()
print('notify_sticky_enabled:', s.get('notify_sticky_enabled'))
print('All imports OK')
"
```

Expected output:
```
notify_sticky_enabled: '0'
All imports OK
```

- [ ] **Step 2: Verify notify_sticky_new exists in both modules**

```bash
cd torrentwatch
python3 -c "
import line_notify, telegram_notify
import inspect
print('line_notify.notify_sticky_new:', inspect.iscoroutinefunction(line_notify.notify_sticky_new))
print('telegram_notify.notify_sticky_new:', inspect.iscoroutinefunction(telegram_notify.notify_sticky_new))
"
```

Expected output:
```
line_notify.notify_sticky_new: True
telegram_notify.notify_sticky_new: True
```

- [ ] **Step 3: Update .notes/daily_log.md**

Add entry to `torrentwatch/.notes/daily_log.md`:
```
## 2026-05-20 — sticky notify toggle
- เพิ่ม setting `notify_sticky_enabled` ใน db.py
- เพิ่ม `notify_sticky_new()` ใน line_notify.py + telegram_notify.py
- scheduler.py: เก็บ new_sticky_entries แล้ว call notify เมื่อ is_new AND is_sticky
- UI: toggle "📌 Sticky Notify" ใน Notification card, version string → 20260520c
```

- [ ] **Step 4: Update .notes/00_INDEX.md**

In `torrentwatch/.notes/00_INDEX.md`, add to `_DEFAULT_SETTINGS` section:
```
- `notify_sticky_enabled = "0"` — push LINE+Telegram เมื่อพบ sticky/pinned torrent ใหม่ครั้งแรก
```

And add to Known Gaps:
```
| ✅ Sticky notification — **ADDED** | toggle ใน Settings → แจ้งเตือน LINE+Telegram เมื่อ is_new AND is_sticky | db.py, scheduler.py, line_notify.py, telegram_notify.py |
```

- [ ] **Step 5: Final commit**

```bash
git add torrentwatch/.notes/
git commit -m "docs(torrentwatch): update notes for sticky notify feature"
```
