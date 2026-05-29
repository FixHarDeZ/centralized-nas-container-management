# News Feed Mobile Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ปรับ dashboard ให้ใช้งานบน smartphone ได้สะดวก — bottom nav, compact price table, และ mobile-friendly controls

**Architecture:** CSS-only สำหรับ responsive layout (`@media (max-width:640px)`) + เพิ่ม HTML elements สำหรับ bottom nav/drawer + แก้ JS `showTab()` ให้ sync bottom nav, เพิ่ม `renderPriceTable()` ให้มี expand row. Desktop ไม่เปลี่ยน

**Tech Stack:** Vanilla HTML/CSS/JS (ไม่มี framework), แก้ `app/static/index.html` และ `app/static/app.js` เท่านั้น

---

> **Note on testing:** งานนี้เป็น frontend CSS/JS ล้วน ไม่มี Python unit tests ที่เกี่ยวข้อง — verification ใช้ browser devtools resize ตามที่ระบุในแต่ละ task

---

## File Map

| File | Changes |
|------|---------|
| `news-feed/app/static/index.html` | เพิ่ม CSS block สำหรับ mobile, เพิ่ม bottom nav HTML, เพิ่ม drawer HTML |
| `news-feed/app/static/app.js` | แก้ `showTab()` sync bottom nav, เพิ่ม `openMobileDrawer()`, `closeMobileDrawer()`, `togglePriceExpand()`, แก้ `renderPriceTable()` |

---

## Task 1: Mobile CSS — New Elements + Responsive Rules

**Files:**
- Modify: `news-feed/app/static/index.html` (ในส่วน `<style>` ก่อน `</style>`)

เพิ่ม CSS 2 ส่วน: (1) styles สำหรับ element ใหม่ (bottom nav, drawer), (2) media query สำหรับ responsive behavior

- [ ] **Step 1: เพิ่ม CSS สำหรับ new elements (bottom nav + drawer) ก่อน `</style>`**

เปิด `news-feed/app/static/index.html` หา `</style>` แล้วแทรก CSS นี้ก่อน `</style>`:

```css
  /* ---------- Mobile bottom nav (hidden on desktop) ---------- */
  .mobile-bottom-nav {
    position: fixed; bottom: 0; left: 0; right: 0;
    height: 56px;
    background: var(--surface);
    border-top: 1px solid var(--border);
    z-index: 30;
    display: none;
    padding-bottom: env(safe-area-inset-bottom, 0);
  }
  .mob-nav-item {
    flex: 1; display: flex; flex-direction: column;
    align-items: center; justify-content: center; gap: 2px;
    border: none; background: transparent; cursor: pointer;
    min-height: 44px; font-family: inherit;
    transition: background .12s;
  }
  .mob-nav-item .mob-nav-icon { font-size: 1.15rem; line-height: 1; }
  .mob-nav-item .mob-nav-label { font-size: .52rem; font-weight: 600; color: var(--text-3); }
  .mob-nav-item.active { background: var(--primary-50); }
  .mob-nav-item.active .mob-nav-label { color: var(--primary); }

  /* ---------- Mobile drawer ---------- */
  .mobile-drawer-overlay {
    display: none; position: fixed; inset: 0;
    background: rgba(15,23,42,.4); z-index: 40;
  }
  .mobile-drawer-overlay.open { display: block; }
  .mobile-drawer-sheet {
    position: absolute; bottom: 0; left: 0; right: 0;
    background: var(--surface);
    border-radius: 1.25rem 1.25rem 0 0;
    padding: .75rem 1rem 2rem;
  }
  .mobile-drawer-handle {
    width: 36px; height: 4px;
    background: var(--border); border-radius: 99px;
    margin: 0 auto .75rem;
  }
  .mobile-drawer-item {
    display: flex; align-items: center; gap: .75rem;
    padding: .7rem .5rem; border-radius: .5rem;
    font-size: .9rem; color: var(--text); font-weight: 500;
    border: none; background: transparent; cursor: pointer;
    width: 100%; text-align: left; font-family: inherit;
    transition: background .12s;
  }
  .mobile-drawer-item:hover { background: var(--bg-tint); }

  /* ---------- Price table expand row (all breakpoints, shown on demand) ---------- */
  .price-expand-row { display: none; background: var(--surface-2); }
  .price-expand-row.open { display: table-row; }
  .price-expand-detail { font-size: .78rem; color: var(--text-3); padding: .1rem 0; }
  .price-expand-detail > div { margin-bottom: .2rem; display: flex; gap: .5rem; align-items: baseline; }
  .price-expand-detail .lbl { color: var(--muted); font-size: .72rem; width: 68px; flex-shrink: 0; }
  .price-expand-detail code {
    font-family: ui-monospace,"SF Mono",Menlo,Monaco,Consolas,monospace;
    font-size: .72rem; background: var(--bg-tint);
    padding: .1rem .35rem; border-radius: .3rem; color: var(--text-2);
  }

  /* Provider sub-label inside model cell (hidden on desktop) */
  .price-cell-provider { display: none; font-size: .72rem; color: var(--text-3); margin-top: 1px; }
```

- [ ] **Step 2: เพิ่ม media query block ต่อจาก Step 1 (ก่อน `</style>` เช่นกัน)**

```css
  /* ========== Mobile responsive (max-width: 640px) ========== */
  @media (max-width:640px) {
    /* Show bottom nav, hide top nav */
    .mobile-bottom-nav { display: flex; }
    nav { display: none !important; }

    /* Content doesn't hide behind bottom nav */
    main { padding-bottom: 5rem; }

    /* Header compact */
    header { padding: .75rem 1rem; }

    /* News controls: search full-width, tools row below */
    #news-search { width: 100%; flex: none; min-width: unset; }
    #news-source-filter,
    #news-sort-btn,
    #fetch-now-btn { flex: 1; min-width: 0; min-height: 40px; }
    #fetch-now-status { width: 100%; order: 99; }

    /* Price tracker: search full-width */
    #price-search { width: 100%; flex: none; min-width: unset; }
    #price-provider-filter,
    #price-sort { flex: 1; min-width: 0; }

    /* Price table: hide Model ID(2), Provider(3), Context(6), Updated(7) */
    /* Remaining visible: Model(1) | Prompt/1M(4) | Completion/1M(5) */
    #price-table th:nth-child(2), #price-table td:nth-child(2),
    #price-table th:nth-child(3), #price-table td:nth-child(3),
    #price-table th:nth-child(6), #price-table td:nth-child(6),
    #price-table th:nth-child(7), #price-table td:nth-child(7) { display: none; }

    /* Show provider under model name + make row tappable */
    .price-cell-provider { display: block; }
    #price-table tbody tr:not(.price-expand-row) { cursor: pointer; }

    /* Leaderboard jump bar: horizontal scroll, no wrap */
    .lb-jump { flex-wrap: nowrap; overflow-x: auto; -webkit-overflow-scrolling: touch; top: 52px; }
    .lb-jump::-webkit-scrollbar { display: none; }
    .lb-card { scroll-margin-top: 116px; }
  }
```

- [ ] **Step 3: ตรวจสอบใน browser**

เปิด `http://localhost:5064` (หรือ dev server ถ้ามี) → DevTools → toggle device toolbar → iPhone 14 (390px)
- ตรวจว่า top nav (`nav`) หายไป
- ตรวจว่า `main` มี padding-bottom ชัดเจน (bottom area ว่างประมาณ 80px)
- ตรวจว่าใน news-timeline: search input กว้างเต็ม row, ปุ่ม 3 อันอยู่แถวถัดไป
- Desktop 1200px: top nav ยังแสดงปกติ, ไม่มี bottom nav

- [ ] **Step 4: Commit**

```bash
git add news-feed/app/static/index.html
git commit -m "feat(news-feed): add mobile CSS — bottom nav, compact table, responsive controls"
```

---

## Task 2: Bottom Nav + Drawer HTML

**Files:**
- Modify: `news-feed/app/static/index.html` (ก่อน `<script src="app.js"></script>`)

- [ ] **Step 1: เพิ่ม bottom nav HTML ก่อน `<script src="app.js">`**

หา `<script src="app.js"></script>` ใน index.html แล้วแทรก HTML นี้ก่อน:

```html
<!-- ===== Mobile Bottom Navigation ===== -->
<div id="mobile-bottom-nav" class="mobile-bottom-nav">
  <button id="mob-news" class="mob-nav-item active" onclick="showTab('news-timeline')">
    <span class="mob-nav-icon">📰</span>
    <span class="mob-nav-label">News</span>
  </button>
  <button id="mob-board" class="mob-nav-item" onclick="showTab('ai-leaderboard')">
    <span class="mob-nav-icon">🏆</span>
    <span class="mob-nav-label">Board</span>
  </button>
  <button id="mob-prices" class="mob-nav-item" onclick="showTab('price-tracker')">
    <span class="mob-nav-icon">💰</span>
    <span class="mob-nav-label">Prices</span>
  </button>
  <button class="mob-nav-item" onclick="openMobileDrawer()">
    <span class="mob-nav-icon">⋯</span>
    <span class="mob-nav-label">More</span>
  </button>
</div>

<!-- ===== Mobile Drawer ===== -->
<div id="mobile-drawer-overlay" class="mobile-drawer-overlay" onclick="closeMobileDrawer()">
  <div class="mobile-drawer-sheet" onclick="event.stopPropagation()">
    <div class="mobile-drawer-handle"></div>
    <button class="mobile-drawer-item" onclick="showTab('digest-history'); closeMobileDrawer()">
      <span>📋</span> Digest History
    </button>
    <button class="mobile-drawer-item" onclick="showTab('source-health'); closeMobileDrawer()">
      <span>📊</span> Source Health
    </button>
    <button class="mobile-drawer-item" onclick="showTab('schedule-config'); closeMobileDrawer()">
      <span>⚙️</span> Schedule Config
    </button>
  </div>
</div>
```

- [ ] **Step 2: ตรวจสอบใน browser**

iPhone 14 (390px):
- Bottom nav แสดง 4 ปุ่ม (📰 News / 🏆 Board / 💰 Prices / ⋯ More)
- กด **⋯ More** → drawer เลื่อนขึ้นจากด้านล่าง
- กด overlay นอก drawer → drawer ปิด
- Desktop: bottom nav ไม่แสดง (display:none)

- [ ] **Step 3: Commit**

```bash
git add news-feed/app/static/index.html
git commit -m "feat(news-feed): add mobile bottom nav and drawer HTML"
```

---

## Task 3: JS — showTab sync + drawer functions

**Files:**
- Modify: `news-feed/app/static/app.js`

- [ ] **Step 1: แก้ `showTab()` ให้ sync bottom nav active state**

หา `function showTab(id) {` ใน app.js (บรรทัดประมาณ 163) แล้วแทนที่ทั้งฟังก์ชัน:

```js
function showTab(id) {
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('nav button').forEach(b => b.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  const tabs = ['source-health','news-timeline','price-tracker','ai-leaderboard','digest-history','schedule-config'];
  document.querySelectorAll('nav button')[tabs.indexOf(id)].classList.add('active');
  // sync mobile bottom nav
  const mobTabMap = { 'news-timeline': 'mob-news', 'ai-leaderboard': 'mob-board', 'price-tracker': 'mob-prices' };
  document.querySelectorAll('.mob-nav-item').forEach(b => b.classList.remove('active'));
  const mobBtn = document.getElementById(mobTabMap[id]);
  if (mobBtn) mobBtn.classList.add('active');
  if (id === 'source-health') { if (!_sourceHealthLoaded) loadSourceHealth(); }
  if (id === 'news-timeline') loadNews();
  if (id === 'price-tracker') loadPrices();
  if (id === 'ai-leaderboard') loadLeaderboard();
  if (id === 'digest-history') loadDigestHistory();
  if (id === 'schedule-config') loadScheduleConfig();
}
```

- [ ] **Step 2: เพิ่ม drawer functions ต่อจาก `showTab()`**

```js
function openMobileDrawer() {
  document.getElementById('mobile-drawer-overlay').classList.add('open');
}

function closeMobileDrawer() {
  document.getElementById('mobile-drawer-overlay').classList.remove('open');
}
```

- [ ] **Step 3: เพิ่ม mobile init ที่ท้ายไฟล์ ต่อจาก `loadSourceHealth()`**

หา block `// Init` ที่ท้ายไฟล์ (บรรทัดสุดท้ายคือ `loadSourceHealth();`) แล้วเพิ่ม:

```js
// On mobile: start on news timeline instead of source health
if (window.matchMedia('(max-width:640px)').matches) showTab('news-timeline');
```

- [ ] **Step 4: ตรวจสอบใน browser**

iPhone 14 (390px):
- หน้าโหลด → เห็น News Timeline (ไม่ใช่ Source Health)
- กด 🏆 Board → Leaderboard แสดง, ปุ่ม Board ใน bottom nav active (background เปลี่ยน)
- กด 💰 Prices → Price Tracker แสดง, ปุ่ม Prices active
- กด ⋯ More → drawer ขึ้น → กด "📋 Digest History" → drawer ปิด → Digest History แสดง
- Desktop: หน้าโหลด → Source Health แสดงปกติ (matchMedia ไม่ match)

- [ ] **Step 5: Commit**

```bash
git add news-feed/app/static/app.js
git commit -m "feat(news-feed): sync bottom nav in showTab, add drawer open/close JS"
```

---

## Task 4: Price Table — Compact + Expand Row

**Files:**
- Modify: `news-feed/app/static/app.js`

- [ ] **Step 1: เพิ่ม `togglePriceExpand()` ต่อจาก `renderPriceTable()`**

หา `function renderPriceTable(prices) {` (บรรทัดประมาณ 270) แล้วเพิ่มฟังก์ชันนี้ **ก่อน** `renderPriceTable`:

```js
function togglePriceExpand(idx) {
  const row = document.getElementById(`price-expand-${idx}`);
  if (row) row.classList.toggle('open');
}
```

- [ ] **Step 2: แก้ `renderPriceTable()` ให้มี provider cell + expand row**

แทนที่ฟังก์ชัน `renderPriceTable` ทั้งหมด:

```js
function renderPriceTable(prices) {
  _shownPrices = prices;
  const tbody = document.querySelector('#price-table tbody');
  tbody.innerHTML = prices.map((p, i) => {
    const z = getZone(p.model_id);
    const ctx = p.context_length ? p.context_length.toLocaleString() + ' tokens' : '–';
    const updated = p.updated_at ? new Date(p.updated_at).toLocaleString('th-TH') : '–';
    return `<tr onclick="togglePriceExpand(${i})">
    <td>
      ${escapeHtml(p.name)} <span class="zone-badge">${z.flag} ${z.label}</span>
      <span class="price-cell-provider">${escapeHtml(p.provider)}</span>
    </td>
    <td><span class="model-id">${escapeHtml(p.model_id)}</span> <button class="copy-btn" data-idx="${i}" title="Copy model ID">📋</button></td>
    <td>${escapeHtml(p.provider)}</td>
    <td>$${(p.prompt_price||0).toFixed(3)}</td>
    <td>$${(p.complete_price||0).toFixed(3)}</td>
    <td>${p.context_length ? p.context_length.toLocaleString() : '–'}</td>
    <td>${p.updated_at ? new Date(p.updated_at).toLocaleString('th-TH') : '–'}</td>
  </tr>
  <tr class="price-expand-row" id="price-expand-${i}">
    <td colspan="7">
      <div class="price-expand-detail">
        <div><span class="lbl">Model ID</span><code>${escapeHtml(p.model_id)}</code></div>
        <div><span class="lbl">Context</span><span>${ctx}</span></div>
        <div><span class="lbl">Updated</span><span>${updated}</span></div>
      </div>
    </td>
  </tr>`;
  }).join('');
}
```

- [ ] **Step 3: แก้ copy button handler ให้ไม่ trigger row expand**

หา `document.addEventListener('click', e => {` ส่วน copy button handler (บรรทัดประมาณ 566) แล้วเพิ่ม `e.stopPropagation()`:

```js
document.addEventListener('click', e => {
  const btn = e.target.closest('.copy-btn');
  if (!btn) return;
  if (btn.classList.contains('set-expiry-btn')) return;
  e.stopPropagation();  // prevent row expand from firing
  const idx = parseInt(btn.dataset.idx, 10);
  const modelId = _shownPrices[idx]?.model_id;
  if (!modelId) return;
  _copyText(modelId).then(() => {
    clearTimeout(_copyTimers.get(btn));
    btn.textContent = '✓';
    _copyTimers.set(btn, setTimeout(() => { btn.textContent = '📋'; }, 1500));
  }).catch(err => console.error('Copy failed:', err));
});
```

- [ ] **Step 4: ตรวจสอบใน browser**

iPhone 14 (390px) — ไปที่ Prices tab:
- ตาราง 3 columns เท่านั้น: (ชื่อโมเดล) | Prompt/1M | Completion/1M
- ใต้ชื่อโมเดล มีชื่อ provider ขนาดเล็ก
- **tap แถว** → expand row เปิดออก แสดง Model ID (monospace) + Context + Updated
- tap อีกครั้ง → expand row ปิด
- กด 📋 copy button → ไม่ expand row, copy model ID ได้
- Desktop 1200px: 7 columns ปกติ, tap แถวยัง expand ได้ (bonus feature)

- [ ] **Step 5: Regression check desktop**

Browser 1200px:
- Source Health, News, Leaderboard, Digest, Config ยังทำงานปกติ
- Price table มี 7 columns ครบ
- Copy button ยังทำงาน
- Top nav ยังแสดงปกติ

- [ ] **Step 6: Commit**

```bash
git add news-feed/app/static/app.js
git commit -m "feat(news-feed): compact price table + expand row on mobile, copy btn stopPropagation"
```

---

## Task 5: Deploy ไปยัง NAS

**Files:** ไม่มีการแก้ไขเพิ่มเติม

- [ ] **Step 1: ตรวจ git status**

```bash
git status
git log --oneline -5
```

Expected: 4 commits ใหม่ตั้งแต่ก่อนเริ่ม task นี้

- [ ] **Step 2: Deploy**

```bash
/deploy
```

หรือรัน deploy script ตรงๆ:

```bash
bash scripts/deploy.sh
```

- [ ] **Step 3: ทดสอบบน NAS จริง**

เปิด `https://<NAS_HOST>:15064` บน smartphone จริง (iOS Safari / Android Chrome):
- Bottom nav 4 items แสดง
- tap News → โหลดข่าว
- tap 🏆 Board → Leaderboard
- tap 💰 Prices → Compact table 3 columns, tap row expand
- tap ⋯ More → drawer เปิด, กด Digest History → ทำงาน
- หมุนแนวนอน (landscape): layout ยังรับได้

- [ ] **Step 4: อัป daily log**

เขียนสรุปใน `news-feed/.notes/daily_log.md`

---

## Self-Review Summary

| Spec requirement | Task |
|-----------------|------|
| Bottom nav C (News/Board/Prices + More drawer) | Task 2 + Task 3 |
| Drawer: Digest / Health / Config | Task 2 |
| Price table compact 3-col | Task 1 (CSS hide cols) + Task 4 (renderPriceTable) |
| Tap expand → Model ID + Context + Updated | Task 4 |
| Provider badge inside model cell on mobile | Task 1 (CSS show .price-cell-provider) + Task 4 (HTML in renderPriceTable) |
| News controls full-width search + chip row | Task 1 (CSS) |
| Leaderboard jump bar horizontal scroll | Task 1 (CSS) |
| Desktop unchanged | Task 1 (media query gates everything), Task 3 (matchMedia check) |
| Touch targets min 44px | Task 1 (.mob-nav-item min-height: 44px) |
| iOS safe area inset | Task 1 (env(safe-area-inset-bottom)) |
