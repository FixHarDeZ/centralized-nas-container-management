# TorrentWatch — Sticky Notification Toggle

**Date:** 2026-05-20  
**Scope:** torrentwatch stack only  
**Status:** Approved

---

## Problem

Notifications (LINE + Telegram) currently fire only on keyword matches. Users have no way to get alerted when a new sticky/pinned/auto-sticky torrent appears — even though sticky entries are already scraped and stored.

---

## Goal

Add a single on/off toggle in Settings that sends a notification to all configured channels (LINE and/or Telegram) whenever a **brand-new** sticky torrent is first discovered.

---

## Approach Selected: A — Single toggle, independent of keyword notify

`notify_sticky_enabled = "0"` in the `settings` table.  
When `"1"`, send to LINE if LINE env vars are set, send to Telegram if Telegram env vars are set.  
Does **not** depend on `line_notify_keyword_enabled` or `telegram_notify_keyword_enabled`.

---

## Data Layer (`db.py`)

Add one entry to `_DEFAULT_SETTINGS`:

```python
"notify_sticky_enabled": "0"   # "1" = push notify when a new sticky torrent is first seen
```

No schema migration needed — the settings table's key/value design handles new keys via `get_settings()` default fallback.

---

## Scheduler Logic (`scheduler.py`)

In `_do_scrape()`:

1. Read `notify_sticky = settings.get("notify_sticky_enabled", "0") == "1"` alongside existing settings reads.
2. Collect new sticky entries in a list `new_sticky_entries`:
   ```python
   if is_new and entry.get("is_sticky"):
       new_sticky_entries.append({**entry, "id": torrent_id})
   ```
3. After the per-source upsert loop, send notifications:
   ```python
   if notify_sticky and new_sticky_entries:
       line_on = bool(config.LINE_ACCESS_TOKEN and config.LINE_USER_ID)
       tg_on   = bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)
       if line_on:
           await line_notify.notify_sticky_new(source_url, new_sticky_entries)
       if tg_on:
           await telegram_notify.notify_sticky_new(source_url, new_sticky_entries)
   ```

Trigger condition: `is_new=True` (first INSERT) **and** `entry["is_sticky"]=True`.  
No notification for existing stickies that are refreshed each cycle.

---

## Notification Functions

### `line_notify.py` — add `notify_sticky_new(source_url, entries)`

Message format (Flex or plain):
```
📌 Sticky ใหม่ — <source label>
• <title> [<seeds>↑ <leeches>↓]
• ...
```

Mirror the existing `notify_keyword_matches()` structure but swap the header emoji/label.

### `telegram_notify.py` — add `notify_sticky_new(source_url, entries)`

Same format, using `sendMessage` Markdown — mirror `notify_keyword_matches()`.

---

## Settings UI

### `index.html`

Add inside the Notification card, after the Auto-DL row:

```html
<div class="tw-field-row" style="margin-top:14px">
  <label for="cfg-sticky-notify">📌 Sticky Notify</label>
  <label class="tw-toggle-row">
    <input type="checkbox" class="tw-toggle" id="cfg-sticky-notify">
  </label>
</div>
<p class="tw-hint">แจ้งเตือนเมื่อพบ sticky/pinned ใหม่ (ผ่าน LINE + Telegram ที่ตั้งค่าไว้)</p>
```

### `app.js`

- `loadSettings()`: `document.getElementById("cfg-sticky-notify").checked = s.notify_sticky_enabled === "1"`
- `saveSettings()`: include `notify_sticky_enabled: ... ? "1" : "0"` in the PUT payload

---

## Files Changed

| File | Change |
|---|---|
| `db.py` | Add `notify_sticky_enabled: "0"` to `_DEFAULT_SETTINGS` |
| `scheduler.py` | Collect `new_sticky_entries`, call `notify_sticky_new()` |
| `line_notify.py` | Add `notify_sticky_new()` function |
| `telegram_notify.py` | Add `notify_sticky_new()` function |
| `static/index.html` | Add toggle row in Notification card |
| `static/app.js` | Wire toggle in `loadSettings()` / `saveSettings()` |

---

## Out of Scope

- No separate LINE vs Telegram sticky toggles (one toggle controls both)
- No notification for stickies that were already in DB before this feature is enabled
- No notification when a torrent *becomes* sticky after initial insert
