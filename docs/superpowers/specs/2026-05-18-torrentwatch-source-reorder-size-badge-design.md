# TorrentWatch — Source Reorder + Size Badge Design

Date: 2026-05-18  
Status: Approved

---

## Overview

Two independent UI improvements for TorrentWatch:

1. **Source Reorder** — ↑↓ buttons in Settings let users persist source display order
2. **Size Badge** — `file_size` shown as a colored badge (tier-based) with bold larger text

---

## Feature 1: Source Reorder

### Goal

Users can reorder sources via ↑↓ buttons in the Settings tab. The order persists in the DB and is reflected in source chip bars across Today, History, and Keywords tabs.

### DB Changes (`db.py`)

- **Migration:** `ALTER TABLE sources ADD COLUMN sort_order INTEGER DEFAULT 0`
  - Guard with `PRAGMA table_info(sources)` — only run if column absent
- **Backfill:** `UPDATE sources SET sort_order = id WHERE sort_order = 0` — preserves insert order as default
- **New source insert:** `add_source()` sets `sort_order = MAX(sort_order) + 1` so new sources go to bottom by default
- **`get_sources()`** — add `ORDER BY sort_order ASC` to query
- **`reorder_source(source_id, direction)`** — `direction: "up" | "down"`
  - `"up"`: find the source with the largest `sort_order < current.sort_order`, swap values
  - `"down"`: find the source with the smallest `sort_order > current.sort_order`, swap values
  - No-op if already first/last

### API Changes (`main.py`)

- `POST /api/sources/{id}/reorder`
  - Body: `{ "direction": "up" | "down" }`
  - Calls `db.reorder_source(id, direction)`
  - Returns updated sources list (same shape as `GET /api/sources`)
  - 404 if source not found

### Frontend Changes (`app.js`, `index.html`, `style.css`)

**`renderSourcesList(sources)`** in `app.js`:
- Each source row gets `↑` and `↓` icon buttons (Bootstrap Icons `bi-chevron-up` / `bi-chevron-down`)
- First source: `↑` button disabled; last source: `↓` button disabled
- On click: `POST /api/sources/{id}/reorder` → on success, reload settings tab (`loadSettings()`) which calls `renderSourceChips()` for all tabs

**CSS**: `.src-reorder-btn` — small icon button, same style as existing `.tw-btn-icon`

### Data Flow

```
User clicks ↑ on source row
  → POST /api/sources/{id}/reorder { direction: "up" }
  → db.reorder_source() swaps sort_order with neighbor
  → Returns sorted sources list
  → loadSettings() re-renders Settings list + source chips on all tabs
```

---

## Feature 2: File Size Badge

### Goal

`file_size` shown as a prominent colored badge on torrent cards so users can instantly assess download size. Color encodes tier: gray (small/MB), amber (medium GB), red (large ≥5 GB). Text is bold and slightly larger than current inline text.

### Size Tiers

| Tier | Condition | Color |
|---|---|---|
| `sm` | MB range OR parsed GB < 1 | Gray `#6b7280` |
| `md` | 1 GB ≤ size < 5 GB | Amber `#f59e0b` |
| `lg` | ≥ 5 GB | Red `#ef4444` |

Parsing: extract float from `file_size` string (e.g. `"2.63 GB"`, `"380.60 MB"`); check unit suffix.

### Frontend Changes (`app.js`)

Add helper function `sizeClass(file_size)`:
```js
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

In `cardHTML()`: replace the current `file_size` inline stats text:
```js
// Before:
t.file_size ? `<span class="tw-stat-sep">·</span><span class="tw-stat-lbl">${escHtml(t.file_size)}</span>` : ""

// After:
t.file_size ? `<span class="tw-badge tw-badge-size ${sizeClass(t.file_size)}">${escHtml(t.file_size)}</span>` : ""
```

### CSS Changes (`style.css`)

```css
.tw-badge-size {
  font-weight: 600;
  font-size: 13px;
  padding: 2px 7px;
  border-radius: 4px;
  letter-spacing: 0.02em;
}
.tw-badge-size-sm { background: rgba(107,114,128,0.18); color: #9ca3af; }
.tw-badge-size-md { background: rgba(245,158,11,0.18);  color: #f59e0b; }
.tw-badge-size-lg { background: rgba(239,68,68,0.18);   color: #ef4444; }
```

No backend changes.

---

## Files Changed

| File | Change |
|---|---|
| `torrentwatch/db.py` | Migration + backfill + `reorder_source()` + `ORDER BY sort_order` in `get_sources()` |
| `torrentwatch/main.py` | `POST /api/sources/{id}/reorder` endpoint |
| `torrentwatch/static/app.js` | `sizeClass()` helper + `cardHTML()` size badge + `renderSourcesList()` ↑↓ buttons |
| `torrentwatch/static/style.css` | `.tw-badge-size` + tier color classes |
| `torrentwatch/static/index.html` | No change expected (buttons injected via JS) |

---

## Out of Scope

- Drag-and-drop reordering
- Auto-sort by torrent count / label
- Backend size tier calculation
- History tab size badge (same `cardHTML()` renders both — will apply automatically)
