# TorrentWatch Frontend Redesign

**Date:** 2026-05-18  
**Status:** Approved  
**Scope:** `torrentwatch/static/` — `index.html`, `style.css`, `app.js` (nav event listener เท่านั้น)  
**Backend:** ไม่แตะ — API, routes, Python ทั้งหมดเหมือนเดิม

---

## Design Decisions

| Decision | Choice | Reason |
|---|---|---|
| Visual direction | Modern Minimal dark | Clean, premium, readable บนมือถือ |
| Navigation | Bottom nav (iOS-style) | ใช้บนมือถือบ่อย นิ้วถึงง่ายกว่า |
| Card layout | Image dominant (thumbnail ใหญ่) | เน้น thumbnail + stats อ่านง่ายในบรรทัดเดียว |
| Approach | Full HTML+CSS+JS rebuild | Static files rollback ง่าย, backend ไม่เสี่ยง |

---

## Visual Spec

### Color System
```css
--bg:          #111118   /* main background */
--bg-card:     #18181f   /* card surface */
--bg-elevated: #1c1c2e   /* elevated elements */
--border:      #252532   /* borders */
--border-dim:  #1c1c2e   /* subtle borders */
--accent:      #6366f1   /* primary indigo (เปลี่ยนจาก #818cf8) */
--accent-dim:  rgba(99,102,241,0.12)
--text:        #f1f0ff
--text-muted:  #9b9bbf
--text-dim:    #4b4b6a
--seed:        #4ade80
--leech:       #f87171
--completed:   #38bdf8
--kw-badge:    #c084fc
--dl-local:    #60a5fa
--dl-nas:      #fbbf24
```

### Typography
- Font: system font stack (`-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`)
- Logo: `font-weight: 800`, `letter-spacing: -0.03em` — "Torrent**.**Watch" (dot สี accent)
- Card title: `13px`, `font-weight: 600`
- Stats numbers: `13px`, `font-weight: 800`, `font-variant-numeric: tabular-nums`
- Nav label: `9.5px`, `font-weight: 500`

---

## Layout Structure

### HTML Skeleton (เปลี่ยนจากเดิม)
```
<body>
  <div id="app">
    <header class="tw-header">          ← sticky top
    <section#panel-today.tw-panel>      ← content panels (no tabs here)
    <section#panel-history.tw-panel>
    <section#panel-keywords.tw-panel>
    <section#panel-settings.tw-panel>
    <nav class="tw-bottom-nav">         ← ย้ายมาล่างสุด (ใหม่)
  </div>
  <button#btn-go-top>
  <div#lightbox>
</body>
```

เดิม `<nav class="tw-tabs">` อยู่หลัง header → ย้ายมาเป็น `<nav class="tw-bottom-nav">` ท้าย `#app`

### Header
```
[Logo "Torrent.Watch"]    [● status · time]  [↻ refresh]
```
- Height: 54px, sticky top
- Status dot: สีเขียว glow เมื่อ scraping, สีหรี่เมื่อ idle
- Refresh button: icon-only, rounded 8px

### Bottom Nav
```
[📋 วันนี้]  [🕐 ประวัติ]  [🏷️ Keyword]  [⚙️ ตั้งค่า]
```
- Height: ~60px (icon 19px + label 9.5px + padding)
- Active state: label สี accent + indicator bar 20×3px ด้านบน nav item
- `position: sticky; bottom: 0` — ติดล่างเสมอ
- `padding-bottom` ใน `.tw-list` ปรับเป็น 12px (ไม่ต้อง 80px แล้ว เพราะ nav ติดอยู่)

---

## Card Design (Image Dominant)

```
┌─────────────────────────────────────────────┐
│ ┌──────────┐  [time] [category badge]    ★kw│
│ │          │  Title title title title…      │
│ │ thumb    │  title (3 lines max)           │
│ │ 88×124px │                                │
│ │          │  284 seed · 47 leech · 1.2k dl │
│ └──────────┘  [⬇ Local] [💾 NAS] [🔗 Detail]│
└─────────────────────────────────────────────┘
```

- Thumbnail: `88×124px`, `border-radius: 9px`, `box-shadow: 0 4px 14px rgba(0,0,0,0.5)`
- Keyword match: `border-color: #3b2060` + subtle gradient bg + `★ kw` badge มุมขวาบน
- Downloaded (local): act-btn มี `border-color: var(--dl-local); color: var(--dl-local)`
- Stats row: number ขนาด 13px bold + label 9px dim, คั่นด้วย `·`
- Card border-radius: `13px`
- Gap between cards: `8px`

---

## Per-Panel Details

### Today Panel
1. Source chip bar (horizontal scroll)
2. Toolbar: sort group (Seed/Leech/DL/Latest) + filter group (ทั้งหมด/★KW/📌Sticky)
3. Search input (full width, icon ซ้าย)
4. Category chip bar (แสดงเมื่อมีหลาย category)
5. Last-updated timestamp
6. Card list

### History Panel
1. Source chip bar
2. Date select + sort group
3. Card list

### Keywords Panel
1. Source chip bar
2. Add keyword input + button
3. Keyword item list (label + delete)

### Settings Panel
Cards จัดกลุ่มใหม่:
- **Sources** — list + add URL
- **Threshold** — seed/leech/completed min + AND/OR
- **Notification** — LINE toggle + Telegram toggle + Auto-DL toggle (รวมเป็น card เดียว)
- **Schedule** — read-only table + scrape sticky toggle + retention days
- **Danger Zone** — clear source buttons

Save button: full-width, sticky ด้านล่างของ scroll area

---

## JS Changes (app.js)

เปลี่ยนเฉพาะ CSS class selector — **ทุก occurrence** ใน `app.js`:
```js
// เดิม: ".tw-tab"   → ใหม่: ".tw-nav-item"
// เดิม: ".tw-panel" → คงเดิม (panels ยังใช้ชื่อเดิม)
```

`data-tab` attribute บน nav button เหมือนเดิมทุกค่า (`today`, `history`, `keywords`, `settings`)  
Logic ทั้งหมด (loadToday, loadHistory ฯลฯ) ไม่เปลี่ยน

---

## Files to Change

| File | Action |
|---|---|
| `static/index.html` | Rewrite — structure ใหม่ (bottom nav, class rename) |
| `static/style.css` | Rewrite — color system ใหม่, card ใหม่, bottom nav |
| `static/app.js` | Edit — เปลี่ยน selector จาก `.tw-tab` → `.tw-nav-item` เท่านั้น |

---

## Out of Scope

- Backend (Python, API, DB) — ไม่แตะ
- New features (pagination, infinite scroll, dark/light toggle)
- Font loading (ใช้ system font)
- PWA/service worker
- `app.js` logic ทั้งหมดนอกจาก nav selector
