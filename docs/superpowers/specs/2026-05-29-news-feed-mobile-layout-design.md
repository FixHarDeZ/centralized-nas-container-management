# News Feed Dashboard — Mobile Layout Redesign

**Date:** 2026-05-29  
**Stack:** `news-feed/`  
**Files affected:** `app/static/index.html`, `app/static/app.js`  
**Approach:** CSS `@media (max-width:640px)` + targeted JS additions (Option B)

---

## Problem

Dashboard ใช้งานบน smartphone ลำบากใน 3 จุดหลัก:

1. **Navigation** — top nav 6 tabs เล็กเกิน tap ยาก ต้อง scroll ขึ้นมาทุกครั้ง
2. **Price Tracker table** — 7 columns บนหน้าจอแคบ ต้อง scroll ซ้าย-ขวา อ่านยาก
3. **News Timeline controls** — Search + filter + sort + fetch button อยู่แถวเดียว แน่นเกินไป

Sections ที่ใช้บน mobile บ่อยสุด: **News Timeline, Leaderboard, AI Price Tracker**

---

## Design Decisions

| ประเด็น | การตัดสินใจ |
|---------|------------|
| Navigation pattern | Bottom nav bar: News / Board / Prices / ⋯ More |
| Hidden sections (Digest, Health, Config) | Bottom drawer เปิดจาก "⋯ More" |
| Price table | Compact 3-col (Model · In · Out) + tap-to-expand row |
| News controls | Search full-width + chip row (filter · sort · fetch) |
| Desktop layout | ไม่เปลี่ยน — mobile styles ใน `@media (max-width:640px)` เท่านั้น |

---

## Architecture

ไม่มีการเปลี่ยน backend หรือ API — แก้เฉพาะ frontend 2 ไฟล์

### index.html changes

**1. Bottom Nav HTML** (เพิ่มก่อน `</body>`)
```html
<!-- mobile bottom nav — hidden on desktop via CSS -->
<div id="mobile-bottom-nav" class="mobile-bottom-nav">
  <button class="mob-nav-item active" data-tab="news-timeline" onclick="mobSwitchTab('news-timeline', this)">
    <span>📰</span><span>News</span>
  </button>
  <button class="mob-nav-item" data-tab="ai-leaderboard" onclick="mobSwitchTab('ai-leaderboard', this)">
    <span>🏆</span><span>Board</span>
  </button>
  <button class="mob-nav-item" data-tab="price-tracker" onclick="mobSwitchTab('price-tracker', this)">
    <span>💰</span><span>Prices</span>
  </button>
  <button class="mob-nav-item" onclick="openMobileDrawer()">
    <span>⋯</span><span>More</span>
  </button>
</div>

<!-- mobile drawer -->
<div id="mobile-drawer-overlay" class="mobile-drawer-overlay" onclick="closeMobileDrawer()">
  <div class="mobile-drawer-sheet" onclick="event.stopPropagation()">
    <div class="mobile-drawer-handle"></div>
    <button class="mobile-drawer-item" onclick="mobSwitchTab('digest-history', null); closeMobileDrawer()">📋 Digest History</button>
    <button class="mobile-drawer-item" onclick="mobSwitchTab('source-health', null); closeMobileDrawer()">📊 Source Health</button>
    <button class="mobile-drawer-item" onclick="mobSwitchTab('schedule-config', null); closeMobileDrawer()">⚙️ Schedule Config</button>
  </div>
</div>
```

**2. Price table** — ไม่เปลี่ยน HTML ของ table header แต่เพิ่ม CSS ซ่อน columns บน mobile และ JS สำหรับ expand row

### CSS additions (`@media (max-width:640px)`)

```css
/* Hide desktop top nav, show bottom nav */
nav { display: none; }
.mobile-bottom-nav { display: flex; }

/* Main padding for bottom nav */
main { padding-bottom: 5rem; }

/* Bottom nav */
.mobile-bottom-nav {
  position: fixed; bottom: 0; left: 0; right: 0;
  height: 56px;
  background: var(--surface);
  border-top: 1px solid var(--border);
  display: none; /* shown only on mobile */
  z-index: 30;
  padding-bottom: env(safe-area-inset-bottom);
}
.mob-nav-item {
  flex: 1; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 2px;
  border: none; background: transparent; cursor: pointer;
  min-height: 44px;
}
.mob-nav-item.active { background: var(--primary-50); }

/* News controls: stack vertically */
.search-row {
  flex-direction: column;
  gap: .4rem;
}
.search-row input { min-width: unset; width: 100%; }
.search-row-chips { display: flex; gap: .4rem; flex-wrap: nowrap; overflow-x: auto; }

/* Price table: hide 4 columns, show expand */
/* Table cols: Model(1) ModelID(2) Provider(3) Prompt(4) Completion(5) Context(6) Updated(7) */
/* Mobile shows: Model(1) Prompt(4) Completion(5) — provider badge injected into col 1 by JS */
#price-table th:nth-child(2), #price-table td:nth-child(2),  /* Model ID */
#price-table th:nth-child(3), #price-table td:nth-child(3),  /* Provider */
#price-table th:nth-child(6), #price-table td:nth-child(6),  /* Context */
#price-table th:nth-child(7), #price-table td:nth-child(7)   /* Updated */
{ display: none; }

/* Provider badge moves into model cell — handled in JS renderPriceTable */
.price-expand-row { display: none; }
.price-expand-row.open { display: table-row; background: var(--surface-2); }

/* Leaderboard jump bar */
.lb-jump { overflow-x: auto; flex-wrap: nowrap; -webkit-overflow-scrolling: touch; top: 56px; }
.lb-card { scroll-margin-top: 120px; }
```

### JS additions (`app.js`)

**`mobSwitchTab(tabId, btn)`** — wrapper ที่เรียก `showTab(tabId)` เดิม แล้วอัป active state ของ bottom nav  
**`openMobileDrawer()` / `closeMobileDrawer()`** — toggle class `open` บน overlay  
**Price table row expand** — เพิ่ม `onclick` ใน `renderPriceTable()` ที่มีอยู่ เพิ่ม expand row HTML ต่อท้ายแต่ละ `<tr>` แสดง Model ID + Context + Updated  
**Provider in model cell** — ใน `renderPriceTable()` เพิ่ม provider + zone badge ใต้ model name  

---

## Component Boundaries

| Component | เปลี่ยนอะไร | ไม่เปลี่ยนอะไร |
|-----------|------------|--------------|
| `index.html` | เพิ่ม bottom nav HTML, drawer HTML, mobile CSS block | Desktop CSS ทั้งหมด, API calls, tab sections HTML |
| `app.js` | เพิ่ม `mobSwitchTab`, `openMobileDrawer`, `closeMobileDrawer`, ปรับ `renderPriceTable` | Logic การ fetch, filter, sort, leaderboard |
| Backend | — | ไม่แตะเลย |

---

## Testing Plan

- [ ] Mobile breakpoint 375px: bottom nav แสดง, top nav ซ่อน
- [ ] Tab switching ผ่าน bottom nav ทำงานถูกต้อง
- [ ] "More" drawer เปิด/ปิด, เลือก tab ใน drawer แล้วปิดได้
- [ ] Price table 3 columns บน mobile, tap row expand แสดง Model ID + Context
- [ ] News search/filter controls ไม่ overflow บน mobile
- [ ] Desktop 1200px: layout เหมือนเดิมทุกอย่าง (regression check)
- [ ] iOS Safari: `env(safe-area-inset-bottom)` ทำงาน
