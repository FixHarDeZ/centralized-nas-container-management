# TorrentWatch Frontend Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign torrentwatch frontend to Modern Minimal dark with iOS-style bottom navigation and image-dominant torrent cards.

**Architecture:** Full rewrite of `index.html` and `style.css`; targeted edits to `app.js` (nav selector + `cardHTML()` + status badge dot). Backend (Python/API/DB) untouched.

**Tech Stack:** Vanilla JS, CSS custom properties, Bootstrap Icons CDN

---

### Task 1: Rewrite style.css

**Files:**
- Modify: `torrentwatch/static/style.css`

- [ ] **Step 1: Overwrite style.css**

```css
/* ─── Reset & base ─────────────────────────────────────────────────────── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg:          #111118;
  --bg-card:     #18181f;
  --bg-elevated: #1c1c2e;
  --border:      #252532;
  --border-dim:  #1c1c2e;
  --accent:      #6366f1;
  --accent-dim:  rgba(99,102,241,0.12);
  --text:        #f1f0ff;
  --text-muted:  #9b9bbf;
  --text-dim:    #4b4b6a;
  --seed:        #4ade80;
  --leech:       #f87171;
  --completed:   #38bdf8;
  --kw-badge:    #c084fc;
  --dl-local:    #60a5fa;
  --dl-nas:      #fbbf24;
  --radius:      13px;
  --header-h:    54px;
  --nav-h:       60px;
}

html, body {
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 14px;
  line-height: 1.5;
  height: 100%;
  overflow-x: hidden;
}

/* ─── Layout ─────────────────────────────────────────────────────────── */
#app {
  max-width: 540px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  min-height: 100dvh;
}

/* ─── Header ─────────────────────────────────────────────────────────── */
.tw-header {
  position: sticky;
  top: 0;
  z-index: 100;
  background: var(--bg);
  border-bottom: 1px solid var(--border-dim);
  height: var(--header-h);
  flex-shrink: 0;
}
.tw-header-inner {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
}
.tw-logo {
  font-size: 17px;
  font-weight: 800;
  color: var(--text);
  letter-spacing: -0.03em;
}
.tw-logo .tw-logo-dot { color: var(--accent); }
.tw-header-actions { display: flex; align-items: center; gap: 10px; }
.tw-status-badge {
  font-size: 11px;
  color: var(--text-dim);
  white-space: nowrap;
}
.tw-status-badge.running { color: var(--seed); }

.tw-icon-btn {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  color: var(--text-dim);
  font-size: 15px;
  cursor: pointer;
  border-radius: 8px;
  transition: color .15s, border-color .15s;
  line-height: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
}
.tw-icon-btn:hover { color: var(--text); border-color: var(--accent); }
.tw-icon-btn.spinning .bi { animation: spin .7s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* ─── Bottom Navigation ───────────────────────────────────────────────── */
.tw-bottom-nav {
  position: sticky;
  bottom: 0;
  z-index: 100;
  background: rgba(17,17,24,0.97);
  border-top: 1px solid var(--border-dim);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  display: flex;
  height: var(--nav-h);
  flex-shrink: 0;
}
.tw-nav-item {
  flex: 1;
  background: none;
  border: none;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 3px;
  cursor: pointer;
  position: relative;
  padding: 6px 4px 4px;
  -webkit-tap-highlight-color: transparent;
  transition: opacity .15s;
}
.tw-nav-item:active { opacity: .7; }
.tw-nav-icon {
  font-size: 19px;
  line-height: 1;
  color: var(--text-dim);
  transition: color .2s;
}
.tw-nav-label {
  font-size: 9.5px;
  font-weight: 500;
  color: var(--text-dim);
  transition: color .2s;
}
.tw-nav-item.active .tw-nav-icon,
.tw-nav-item.active .tw-nav-label { color: var(--accent); }
.tw-nav-indicator {
  position: absolute;
  top: 0;
  left: 50%;
  transform: translateX(-50%);
  width: 20px;
  height: 3px;
  border-radius: 0 0 3px 3px;
  background: var(--accent);
  opacity: 0;
  transition: opacity .2s;
}
.tw-nav-item.active .tw-nav-indicator { opacity: 1; }

/* ─── Panels ─────────────────────────────────────────────────────────── */
.tw-panel { display: none; flex-direction: column; }
.tw-panel.active { display: flex; }

/* ─── Source chip bar ────────────────────────────────────────────────── */
.tw-source-bar {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  padding: 10px 14px 8px;
  scrollbar-width: none;
  flex-shrink: 0;
}
.tw-source-bar::-webkit-scrollbar { display: none; }
.tw-source-chip {
  flex-shrink: 0;
  border: 1px solid var(--border);
  border-radius: 20px;
  padding: 4px 12px;
  font-size: 11.5px;
  color: var(--text-dim);
  background: none;
  cursor: pointer;
  white-space: nowrap;
  transition: all .15s;
}
.tw-source-chip.active {
  border-color: var(--accent);
  color: var(--accent);
  background: var(--accent-dim);
}

/* ─── Toolbar ────────────────────────────────────────────────────────── */
.tw-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 14px 8px;
  flex-wrap: wrap;
  gap: 6px;
  flex-shrink: 0;
}
.tw-sort-group, .tw-filter-group { display: flex; gap: 4px; }
.tw-sort-btn, .tw-filter-btn {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  color: var(--text-dim);
  border-radius: 6px;
  padding: 4px 10px;
  font-size: 11.5px;
  cursor: pointer;
  transition: all .15s;
  white-space: nowrap;
}
.tw-sort-btn.active, .tw-filter-btn.active {
  border-color: var(--accent);
  color: var(--accent);
  background: var(--accent-dim);
}
.tw-seed-icon { color: var(--seed); }
.tw-leech-icon { color: var(--leech); }
.tw-completed-icon { color: var(--completed); }
#btn-toggle-sticky.active { border-color: #fb923c; color: #fb923c; background: #1c1007; }

.tw-count {
  display: inline-block;
  background: rgba(255,255,255,0.1);
  border-radius: 8px;
  padding: 0 5px;
  font-size: 10px;
  font-weight: 700;
  min-width: 18px;
  text-align: center;
  line-height: 16px;
  vertical-align: middle;
}

/* ─── Date select ─────────────────────────────────────────────────────── */
.tw-date-select {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text);
  padding: 4px 8px;
  font-size: 13px;
  cursor: pointer;
  flex: 1;
  min-width: 0;
}

/* ─── Search row ──────────────────────────────────────────────────────── */
.tw-search-row {
  padding: 0 14px 8px;
  display: flex;
  flex-shrink: 0;
}
.tw-search-wrap {
  flex: 1;
  position: relative;
  display: flex;
  align-items: center;
}
.tw-search-icon {
  position: absolute;
  left: 10px;
  color: var(--text-dim);
  font-size: 13px;
  pointer-events: none;
}
.tw-search-input {
  flex: 1;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 10px;
  color: var(--text);
  padding: 7px 12px 7px 32px;
  font-size: 13px;
  outline: none;
  width: 100%;
  transition: border-color .15s;
}
.tw-search-input:focus { border-color: var(--accent); }
.tw-search-input::placeholder { color: var(--text-dim); }

/* ─── Last updated ────────────────────────────────────────────────────── */
.tw-last-updated {
  font-size: 10.5px;
  color: var(--text-dim);
  padding: 0 14px 6px;
  flex-shrink: 0;
}

/* ─── Torrent list ────────────────────────────────────────────────────── */
.tw-list { padding: 0 10px 12px; display: flex; flex-direction: column; gap: 8px; }

/* ─── Torrent card ────────────────────────────────────────────────────── */
.tw-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 11px;
  display: flex;
  gap: 12px;
  transition: border-color .15s;
  position: relative;
}
.tw-card:hover { border-color: #3a3a5a; }
.tw-card.keyword-match {
  border-color: #3b2060;
  background: linear-gradient(135deg, var(--bg-card) 70%, #1a1030 100%);
}
.tw-card.downloaded { border-color: #1e3a28; }

.tw-card-thumb {
  flex-shrink: 0;
  width: 88px;
  height: 124px;
  border-radius: 9px;
  object-fit: cover;
  background: #000;
  cursor: zoom-in;
  box-shadow: 0 4px 14px rgba(0,0,0,0.5);
}
.tw-card-thumb-placeholder {
  flex-shrink: 0;
  width: 88px;
  height: 124px;
  border-radius: 9px;
  background: linear-gradient(160deg, #1e1b4b 0%, #312e81 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-dim);
  font-size: 26px;
}
.tw-card-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.tw-card-meta {
  display: flex;
  align-items: center;
  gap: 5px;
  flex-wrap: wrap;
}
.tw-card-time {
  font-size: 9.5px;
  color: var(--text-dim);
  white-space: nowrap;
}
.tw-badge-cat {
  font-size: 9.5px;
  background: #1e1b4b;
  color: #818cf8;
  padding: 1px 7px;
  border-radius: 5px;
  white-space: nowrap;
  font-weight: 500;
}
.tw-kw-star {
  position: absolute;
  top: 9px;
  right: 10px;
  font-size: 10px;
  font-weight: 700;
  color: var(--kw-badge);
  background: rgba(192,132,252,0.12);
  border: 1px solid rgba(192,132,252,0.2);
  border-radius: 4px;
  padding: 1px 5px;
  white-space: nowrap;
  line-height: 1.4;
}
.tw-card-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  line-height: 1.45;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
}
.tw-title-link { color: inherit; text-decoration: none; }
.tw-title-link:hover { color: #a5b4fc; }

/* ─── Stats row ─────────────────────────────────────────────────────── */
.tw-card-stats {
  display: flex;
  align-items: baseline;
  gap: 3px;
  flex-wrap: wrap;
  margin-top: 1px;
}
.tw-stat-val {
  font-size: 13px;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
  line-height: 1;
}
.tw-stat-seed     { color: var(--seed); }
.tw-stat-leech    { color: var(--leech); }
.tw-stat-completed { color: var(--completed); }
.tw-stat-lbl { font-size: 9px; color: var(--text-dim); margin-left: 1px; }
.tw-stat-sep { font-size: 10px; color: var(--border); margin: 0 2px; font-weight: 700; }

/* ─── DL badges ─────────────────────────────────────────────────────── */
.tw-card-dl-badges { display: flex; flex-wrap: wrap; gap: 4px; }
.tw-badge {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 4px;
  display: inline-flex;
  align-items: center;
  gap: 3px;
  white-space: nowrap;
}
.tw-badge-sticky   { background: #292524; color: #fb923c; border: 1px solid #78350f; }
.tw-badge-dl-local { background: #1e3a5f; color: var(--dl-local); }
.tw-badge-dl-nas   { background: #431407; color: var(--dl-nas); }
.tw-badge-info     { background: #1e293b; color: #94a3b8; }

/* ─── Card actions ───────────────────────────────────────────────────── */
.tw-card-actions { display: flex; gap: 5px; margin-top: 2px; }
.tw-action-btn {
  flex: 1;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 7px;
  color: var(--text-dim);
  font-size: 11px;
  padding: 5px 4px;
  cursor: pointer;
  transition: all .15s;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 3px;
  text-decoration: none;
  white-space: nowrap;
}
.tw-action-btn:hover { border-color: var(--accent); color: var(--text); }
.tw-action-btn.loading { opacity: .6; pointer-events: none; }
.tw-action-btn.done-local { border-color: var(--dl-local); color: var(--dl-local); }
.tw-action-btn.done-nas   { border-color: var(--dl-nas);   color: var(--dl-nas); }

/* ─── Empty state ────────────────────────────────────────────────────── */
.tw-empty { text-align: center; padding: 60px 20px; color: var(--text-dim); }
.tw-empty .bi { font-size: 40px; display: block; margin-bottom: 12px; }

/* ─── Keywords panel ─────────────────────────────────────────────────── */
.tw-keyword-form {
  display: flex;
  gap: 8px;
  padding: 10px 14px 6px;
  flex-shrink: 0;
}
.tw-kw-list { padding: 0 14px 12px; display: flex; flex-direction: column; gap: 6px; }
.tw-kw-item {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 9px;
  padding: 10px 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.tw-kw-text { font-size: 13.5px; }
.tw-kw-del {
  background: none;
  border: none;
  color: var(--leech);
  font-size: 15px;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;
  transition: background .15s;
}
.tw-kw-del:hover { background: #3b0000; }

/* ─── Settings panel ─────────────────────────────────────────────────── */
.tw-settings-scroll {
  padding: 10px 12px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.tw-settings-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}
.tw-section-title {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  padding: 11px 14px 10px;
  border-bottom: 1px solid var(--border-dim);
  display: flex;
  align-items: center;
  gap: 6px;
}
.tw-settings-body { padding: 12px 14px; }
.tw-sources-list { display: flex; flex-direction: column; gap: 6px; }
.tw-source-item {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--bg-elevated);
  border-radius: 8px;
  padding: 8px 10px;
}
.tw-source-url {
  flex: 1;
  font-size: 12px;
  color: var(--text-dim);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tw-source-label-wrap {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
  align-items: flex-start;
}
.tw-source-display-label {
  font-size: 13px;
  color: var(--text);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}
.tw-source-url-hint {
  font-size: 10px;
  color: var(--text-dim);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}
.tw-source-add-row { display: flex; gap: 8px; margin-top: 10px; }
.tw-field-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.tw-field-row:last-child { margin-bottom: 0; }
.tw-field-row label { font-size: 13px; color: var(--text-muted); }
.tw-radio-group { display: flex; gap: 12px; }
.tw-radio-label {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 13px;
  color: var(--text);
  cursor: pointer;
}
.tw-radio-label input[type="radio"] { cursor: pointer; accent-color: var(--accent); }
.tw-toggle-row {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}
.tw-toggle {
  width: 36px;
  height: 20px;
  appearance: none;
  background: var(--border);
  border-radius: 10px;
  cursor: pointer;
  position: relative;
  transition: background .2s;
  flex-shrink: 0;
}
.tw-toggle::after {
  content: "";
  position: absolute;
  top: 2px; left: 2px;
  width: 16px; height: 16px;
  border-radius: 50%;
  background: #fff;
  transition: transform .2s;
}
.tw-toggle:checked { background: var(--accent); }
.tw-toggle:checked::after { transform: translateX(16px); }
.tw-hint { font-size: 11px; color: var(--text-dim); margin: -6px 0 8px; }
.tw-save-btn { margin-top: 4px; width: 100%; }
.tw-schedule-info {
  background: var(--bg-elevated);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 10px;
}
.tw-schedule-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12.5px;
  padding: 3px 0;
}
.tw-schedule-time { color: var(--text); font-family: monospace; font-size: 12px; }
.tw-schedule-freq { color: var(--accent); font-weight: 500; }
.tw-schedule-pause .tw-schedule-freq { color: var(--text-dim); }

/* ─── Inputs & buttons ───────────────────────────────────────────────── */
.tw-input {
  flex: 1;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 9px;
  color: var(--text);
  padding: 8px 12px;
  font-size: 14px;
  outline: none;
  min-width: 0;
  transition: border-color .15s;
}
.tw-input:focus { border-color: var(--accent); }
.tw-input::placeholder { color: var(--text-dim); }
.tw-input-sm {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text);
  padding: 4px 8px;
  font-size: 13px;
  width: 70px;
  text-align: center;
  outline: none;
}
.tw-input-sm:focus { border-color: var(--accent); }
.tw-btn-primary {
  background: var(--accent);
  border: none;
  border-radius: 9px;
  color: #fff;
  padding: 9px 16px;
  font-size: 13.5px;
  font-weight: 700;
  cursor: pointer;
  transition: opacity .15s;
  display: flex;
  align-items: center;
  gap: 6px;
  justify-content: center;
  white-space: nowrap;
}
.tw-btn-primary:hover { opacity: .87; }
.tw-btn-primary:active { opacity: .7; }
.tw-btn-secondary {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 9px;
  color: var(--text);
  padding: 9px 16px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: border-color .15s;
  display: flex;
  align-items: center;
  gap: 6px;
  justify-content: center;
  white-space: nowrap;
}
.tw-btn-secondary:hover { border-color: var(--accent); }
.tw-btn-secondary:active { opacity: .8; }
.tw-btn-secondary:disabled { opacity: .45; cursor: not-allowed; }
.tw-btn-danger {
  background: #7f1d1d;
  border: none;
  border-radius: 6px;
  color: #fca5a5;
  padding: 4px 8px;
  font-size: 12px;
  cursor: pointer;
  transition: opacity .15s;
}
.tw-btn-danger:hover { opacity: .85; }
.tw-btn-icon {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-dim);
  padding: 4px 8px;
  font-size: 12px;
  cursor: pointer;
  transition: all .15s;
}
.tw-btn-icon:hover { color: var(--text); border-color: var(--accent); }

/* ─── Toast ──────────────────────────────────────────────────────────── */
#toast {
  position: fixed;
  bottom: calc(var(--nav-h) + 12px);
  left: 50%;
  transform: translateX(-50%) translateY(80px);
  background: #1e1e2e;
  border: 1px solid var(--border);
  border-radius: 10px;
  color: var(--text);
  padding: 10px 18px;
  font-size: 13px;
  z-index: 9999;
  transition: transform .3s ease;
  white-space: nowrap;
  box-shadow: 0 4px 20px rgba(0,0,0,.6);
  pointer-events: none;
}
#toast.show { transform: translateX(-50%) translateY(0); }
#toast.success { border-color: var(--seed); }
#toast.error   { border-color: var(--leech); }

/* ─── Scrollbar ──────────────────────────────────────────────────────── */
::-webkit-scrollbar { width: 4px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }

/* ─── Go-to-top ──────────────────────────────────────────────────────── */
#btn-go-top {
  position: fixed;
  bottom: calc(var(--nav-h) + 12px);
  right: 16px;
  width: 38px;
  height: 38px;
  border-radius: 50%;
  background: var(--accent);
  color: #fff;
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  box-shadow: 0 4px 14px rgba(0,0,0,.5);
  opacity: 0;
  transform: translateY(12px);
  pointer-events: none;
  transition: opacity .2s, transform .2s;
  z-index: 200;
}
#btn-go-top.visible { opacity: 1; transform: translateY(0); pointer-events: auto; }

/* ─── Lightbox ────────────────────────────────────────────────────────── */
.tw-lightbox {
  position: fixed;
  inset: 0;
  z-index: 9000;
  background: rgba(0,0,0,0.94);
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  pointer-events: none;
  transition: opacity .2s;
}
.tw-lightbox.open { opacity: 1; pointer-events: auto; }
.tw-lightbox-img {
  max-width: 92vw;
  max-height: 88vh;
  object-fit: contain;
  border-radius: 8px;
  box-shadow: 0 8px 40px rgba(0,0,0,.8);
  display: block;
}
.tw-lightbox-close {
  position: absolute;
  top: 16px;
  right: 16px;
  background: rgba(255,255,255,.1);
  border: none;
  border-radius: 50%;
  width: 40px;
  height: 40px;
  color: #fff;
  font-size: 18px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background .15s;
}
.tw-lightbox-close:hover { background: rgba(255,255,255,.2); }
```

- [ ] **Step 2: Commit**

```bash
git add torrentwatch/static/style.css
git commit -m "style(torrentwatch): redesign CSS — Modern Minimal, bottom nav, image-dominant cards"
```

---

### Task 2: Rewrite index.html

**Files:**
- Modify: `torrentwatch/static/index.html`

- [ ] **Step 1: Overwrite index.html**

```html
<!DOCTYPE html>
<html lang="th">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
  <meta name="theme-color" content="#111118">
  <title>TorrentWatch</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css">
  <link rel="stylesheet" href="/static/style.css?v=20260518b">
</head>
<body>
  <div id="app">

    <!-- Header -->
    <header class="tw-header">
      <div class="tw-header-inner">
        <span class="tw-logo">Torrent<span class="tw-logo-dot">.</span>Watch</span>
        <div class="tw-header-actions">
          <span id="status-badge" class="tw-status-badge"></span>
          <button class="tw-icon-btn" id="btn-scrape-now" title="Scrape now">
            <i class="bi bi-arrow-clockwise"></i>
          </button>
        </div>
      </div>
    </header>

    <!-- ── Today ── -->
    <section class="tw-panel active" id="panel-today">
      <div class="tw-source-bar" id="source-chips-today"></div>
      <div class="tw-toolbar">
        <div class="tw-sort-group">
          <button class="tw-sort-btn active" data-sort="seeds"><i class="bi bi-arrow-up-circle-fill tw-seed-icon"></i> Seed</button>
          <button class="tw-sort-btn" data-sort="leeches"><i class="bi bi-arrow-down-circle-fill tw-leech-icon"></i> Leech</button>
          <button class="tw-sort-btn" data-sort="completed"><i class="bi bi-check2-circle tw-completed-icon"></i> DL</button>
          <button class="tw-sort-btn" data-sort="date"><i class="bi bi-clock"></i></button>
        </div>
        <div class="tw-filter-group">
          <button class="tw-filter-btn active" data-filter="all">ทั้งหมด</button>
          <button class="tw-filter-btn" data-filter="keyword"><i class="bi bi-star-fill"></i> KW</button>
          <button class="tw-filter-btn" id="btn-toggle-sticky" title="แสดง/ซ่อน Sticky"><i class="bi bi-pin-fill"></i></button>
        </div>
      </div>
      <div class="tw-search-row">
        <div class="tw-search-wrap">
          <i class="bi bi-search tw-search-icon"></i>
          <input class="tw-search-input" id="search-input" type="search" placeholder="ค้นหาชื่อ..." autocomplete="off">
        </div>
      </div>
      <div class="tw-source-bar tw-cat-bar" id="cat-bar-today" style="display:none;padding-top:0;padding-bottom:6px"></div>
      <div class="tw-last-updated" id="last-updated-today"></div>
      <div class="tw-list" id="list-today"></div>
    </section>

    <!-- ── History ── -->
    <section class="tw-panel" id="panel-history">
      <div class="tw-source-bar" id="source-chips-history"></div>
      <div class="tw-toolbar">
        <select class="tw-date-select" id="history-date-select">
          <option value="">เลือกวันที่...</option>
        </select>
        <div class="tw-sort-group">
          <button class="tw-sort-btn active" data-sort="seeds"><i class="bi bi-arrow-up-circle-fill tw-seed-icon"></i> Seed</button>
          <button class="tw-sort-btn" data-sort="leeches"><i class="bi bi-arrow-down-circle-fill tw-leech-icon"></i> Leech</button>
          <button class="tw-sort-btn" data-sort="completed"><i class="bi bi-check2-circle tw-completed-icon"></i> DL</button>
          <button class="tw-sort-btn" data-sort="date"><i class="bi bi-clock"></i></button>
        </div>
      </div>
      <div class="tw-list" id="list-history"></div>
    </section>

    <!-- ── Keywords ── -->
    <section class="tw-panel" id="panel-keywords">
      <div class="tw-source-bar" id="source-chips-keywords"></div>
      <div class="tw-keyword-form">
        <input class="tw-input" id="kw-input" type="text" placeholder="เพิ่ม keyword..." autocomplete="off">
        <button class="tw-btn-primary" id="btn-add-kw"><i class="bi bi-plus-lg"></i></button>
      </div>
      <div id="kw-list" class="tw-kw-list"></div>
    </section>

    <!-- ── Settings ── -->
    <section class="tw-panel" id="panel-settings">
      <div class="tw-settings-scroll">

        <!-- Sources -->
        <div class="tw-settings-card">
          <div class="tw-section-title"><i class="bi bi-link-45deg"></i> Sources</div>
          <div class="tw-settings-body">
            <div id="sources-list" class="tw-sources-list"></div>
            <div class="tw-source-add-row">
              <input class="tw-input" id="source-url-input" type="url" placeholder="https://bearbit.org/view...php">
              <button class="tw-btn-primary" id="btn-add-source"><i class="bi bi-plus-lg"></i></button>
            </div>
          </div>
        </div>

        <!-- Threshold -->
        <div class="tw-settings-card">
          <div class="tw-section-title"><i class="bi bi-sliders"></i> Threshold</div>
          <div class="tw-settings-body">
            <div class="tw-field-row">
              <label>Seed min</label>
              <input class="tw-input-sm" id="cfg-seed-min" type="number" min="0">
            </div>
            <div class="tw-field-row">
              <label>Leech min</label>
              <input class="tw-input-sm" id="cfg-leech-min" type="number" min="0">
            </div>
            <div class="tw-field-row">
              <label>Completed min</label>
              <input class="tw-input-sm" id="cfg-completed-min" type="number" min="0">
            </div>
            <div class="tw-field-row">
              <label>เงื่อนไข</label>
              <div class="tw-radio-group">
                <label class="tw-radio-label"><input type="radio" name="filter_mode" id="cfg-mode-and" value="and"> AND</label>
                <label class="tw-radio-label"><input type="radio" name="filter_mode" id="cfg-mode-or" value="or"> OR</label>
              </div>
            </div>
          </div>
        </div>

        <!-- Notification (LINE + Telegram + Auto-DL combined) -->
        <div class="tw-settings-card">
          <div class="tw-section-title"><i class="bi bi-bell"></i> Notification</div>
          <div class="tw-settings-body">
            <div class="tw-field-row">
              <label for="cfg-line-notify">LINE Notify</label>
              <label class="tw-toggle-row">
                <input type="checkbox" class="tw-toggle" id="cfg-line-notify">
              </label>
            </div>
            <p id="line-status-hint" class="tw-hint"></p>
            <div class="tw-field-row">
              <button class="tw-btn-secondary" id="btn-line-test" style="width:100%">
                <i class="bi bi-send"></i> ทดสอบส่ง LINE
              </button>
            </div>

            <div class="tw-field-row" style="margin-top:14px">
              <label for="cfg-telegram-notify">Telegram</label>
              <label class="tw-toggle-row">
                <input type="checkbox" class="tw-toggle" id="cfg-telegram-notify">
              </label>
            </div>
            <p id="telegram-status-hint" class="tw-hint"></p>
            <div class="tw-field-row">
              <button class="tw-btn-secondary" id="btn-telegram-test" style="width:100%">
                <i class="bi bi-send"></i> ทดสอบส่ง Telegram
              </button>
            </div>
            <div class="tw-field-row" style="margin-top:4px">
              <button class="tw-btn-secondary" id="btn-telegram-get-chat-id" style="width:100%;background:var(--bg-elevated)">
                <i class="bi bi-search"></i> ค้นหา Chat ID
              </button>
            </div>
            <div id="telegram-chat-id-result" style="display:none;margin-top:8px;font-size:12px;background:var(--bg-elevated);padding:8px 10px;border-radius:6px;word-break:break-all"></div>

            <div class="tw-field-row" style="margin-top:14px">
              <label for="cfg-auto-dl">Auto-DL to NAS</label>
              <label class="tw-toggle-row">
                <input type="checkbox" class="tw-toggle" id="cfg-auto-dl">
              </label>
            </div>
            <p class="tw-hint">บันทึก keyword match ไป NAS อัตโนมัติ</p>
          </div>
        </div>

        <!-- Schedule -->
        <div class="tw-settings-card">
          <div class="tw-section-title"><i class="bi bi-clock-history"></i> Schedule</div>
          <div class="tw-settings-body">
            <div class="tw-schedule-info">
              <div class="tw-schedule-row"><span class="tw-schedule-time">19:00 – 01:00</span><span class="tw-schedule-freq">ทุก 30 นาที</span></div>
              <div class="tw-schedule-row tw-schedule-pause"><span class="tw-schedule-time">01:00 – 06:00</span><span class="tw-schedule-freq">หยุด</span></div>
              <div class="tw-schedule-row"><span class="tw-schedule-time">06:00 – 19:00</span><span class="tw-schedule-freq">ทุก 1 ชั่วโมง</span></div>
              <div class="tw-schedule-row"><span class="tw-schedule-time">23:58</span><span class="tw-schedule-freq">สิ้นวัน</span></div>
            </div>
            <div class="tw-field-row">
              <label>รวม sticky/pinned</label>
              <label class="tw-toggle-row">
                <input type="checkbox" class="tw-toggle" id="cfg-scrape-sticky">
              </label>
            </div>
            <div class="tw-field-row">
              <label>เก็บประวัติ (วัน)</label>
              <input class="tw-input-sm" id="cfg-retention" type="number" min="1" max="90">
            </div>
          </div>
        </div>

        <!-- Danger Zone -->
        <div class="tw-settings-card">
          <div class="tw-section-title"><i class="bi bi-trash3"></i> Danger Zone</div>
          <div class="tw-settings-body">
            <p class="tw-hint" style="margin-bottom:10px">ลบ torrent ทั้งหมดของ source แล้ว scrape ใหม่</p>
            <div id="clear-source-btns" class="tw-sources-list"></div>
          </div>
        </div>

        <button class="tw-btn-primary tw-save-btn" id="btn-save-settings">
          <i class="bi bi-check-lg"></i> บันทึกการตั้งค่า
        </button>

      </div>
    </section>

    <!-- Bottom Navigation -->
    <nav class="tw-bottom-nav">
      <button class="tw-nav-item active" data-tab="today">
        <div class="tw-nav-indicator"></div>
        <i class="bi bi-collection-play tw-nav-icon"></i>
        <span class="tw-nav-label">วันนี้</span>
      </button>
      <button class="tw-nav-item" data-tab="history">
        <div class="tw-nav-indicator"></div>
        <i class="bi bi-clock-history tw-nav-icon"></i>
        <span class="tw-nav-label">ประวัติ</span>
      </button>
      <button class="tw-nav-item" data-tab="keywords">
        <div class="tw-nav-indicator"></div>
        <i class="bi bi-tags tw-nav-icon"></i>
        <span class="tw-nav-label">Keyword</span>
      </button>
      <button class="tw-nav-item" data-tab="settings">
        <div class="tw-nav-indicator"></div>
        <i class="bi bi-gear tw-nav-icon"></i>
        <span class="tw-nav-label">ตั้งค่า</span>
      </button>
    </nav>

  </div>

  <button id="btn-go-top" title="กลับขึ้นบน" aria-label="Go to top">
    <i class="bi bi-arrow-up"></i>
  </button>

  <div id="lightbox" class="tw-lightbox" role="dialog" aria-modal="true">
    <button class="tw-lightbox-close" id="lightbox-close" aria-label="ปิด"><i class="bi bi-x-lg"></i></button>
    <img class="tw-lightbox-img" id="lightbox-img" src="" alt="">
  </div>

  <script src="/static/app.js?v=20260518b"></script>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add torrentwatch/static/index.html
git commit -m "feat(torrentwatch): new HTML structure — bottom nav, search icon, consolidated settings"
```

---

### Task 3: Update app.js

**Files:**
- Modify: `torrentwatch/static/app.js`

Three targeted edits. Apply them in order.

- [ ] **Step 1: Replace nav selector (lines 47–55)**

Find this exact block:
```js
document.querySelectorAll(".tw-tab").forEach(btn => {
  btn.addEventListener("click", () => {
    state.tab = btn.dataset.tab;
    document.querySelectorAll(".tw-tab").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    document.querySelectorAll(".tw-panel").forEach(p => p.classList.remove("active"));
    document.getElementById("panel-" + state.tab).classList.add("active");
    onTabActivate(state.tab);
  });
});
```

Replace with:
```js
document.querySelectorAll(".tw-nav-item").forEach(btn => {
  btn.addEventListener("click", () => {
    state.tab = btn.dataset.tab;
    document.querySelectorAll(".tw-nav-item").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    document.querySelectorAll(".tw-panel").forEach(p => p.classList.remove("active"));
    document.getElementById("panel-" + state.tab).classList.add("active");
    onTabActivate(state.tab);
  });
});
```

- [ ] **Step 2: Replace cardHTML() function (lines 241–281)**

Find this exact block:
```js
function cardHTML(t, readOnly) {
  const dlLocal    = t.downloaded_local ? `<span class="tw-badge tw-badge-dl-local"><i class="bi bi-check-lg"></i> Local</span>` : "";
  const dlNas      = t.downloaded_nas   ? `<span class="tw-badge tw-badge-dl-nas"><i class="bi bi-check-lg"></i> NAS</span>` : "";
  const kwBadge    = t.keyword_match    ? `<span class="tw-badge tw-badge-kw"><i class="bi bi-star-fill"></i> KW</span>` : "";
  const catBadge   = t.category         ? `<span class="tw-badge tw-badge-cat">${escHtml(catLabel(t.category))}</span>` : "";
  const stickyBadge = t.is_sticky       ? `<span class="tw-badge tw-badge-sticky"><i class="bi bi-pin-fill"></i> Sticky</span>` : "";
  const completedBadge = t.completed > 0 ? `<span class="tw-badge tw-badge-completed"><i class="bi bi-check2-circle"></i>${t.completed}</span>` : "";
  const thumb = t.cover_url
    ? `<img class="tw-card-thumb" src="${escHtml(t.cover_url)}" alt="" loading="lazy" data-lightbox="${escHtml(t.cover_url)}" onerror="this.outerHTML='<div class=\'tw-card-thumb-placeholder\'><i class=\'bi bi-film\'></i></div>'">`
    : `<div class="tw-card-thumb-placeholder"><i class="bi bi-film"></i></div>`;
  const actions = readOnly ? "" : `
    <div class="tw-card-actions">
      <button class="tw-action-btn btn-dl-local${t.downloaded_local ? " done-local" : ""}" data-id="${t.id}" data-title="${escHtml(t.title)}">
        <i class="bi bi-download"></i> Browser
      </button>
      <button class="tw-action-btn btn-dl-nas${t.downloaded_nas ? " done-nas" : ""}" data-id="${t.id}">
        <i class="bi bi-folder-symlink"></i> NAS
      </button>
    </div>`;

  return `
  <div class="tw-card${t.downloaded_local || t.downloaded_nas ? " downloaded" : ""}${t.keyword_match ? " keyword-match" : ""}" data-id="${t.id}">
    ${thumb}
    <div class="tw-card-body">
      <a class="tw-card-title tw-title-link" href="/api/detail/${t.id}" target="_blank" rel="noopener">${escHtml(t.title)}</a>
      <div class="tw-card-meta">
        ${catBadge}
        <span class="tw-card-time">${_fmtTime(t.posted_at)}</span>
      </div>
      <div class="tw-card-badges">
        <span class="tw-badge tw-badge-seed"><i class="bi bi-arrow-up-circle-fill"></i>${t.seeds}</span>
        <span class="tw-badge tw-badge-leech"><i class="bi bi-arrow-down-circle-fill"></i>${t.leeches}</span>
        ${completedBadge}
        ${t.file_size ? `<span class="tw-badge tw-badge-info"><i class="bi bi-hdd"></i>${escHtml(t.file_size)}</span>` : ""}
        ${t.file_count > 1 ? `<span class="tw-badge tw-badge-info"><i class="bi bi-files"></i>${t.file_count}</span>` : ""}
        ${stickyBadge}${kwBadge}${dlLocal}${dlNas}
      </div>
      ${actions}
    </div>
  </div>`;
}
```

Replace with:
```js
function cardHTML(t, readOnly) {
  const fmt = n => n >= 1000 ? (n / 1000).toFixed(1).replace(/\.0$/, "") + "k" : String(n);

  const kwStar    = t.keyword_match ? `<span class="tw-kw-star">★ kw</span>` : "";
  const catBadge  = t.category ? `<span class="tw-badge-cat">${escHtml(catLabel(t.category))}</span>` : "";
  const stickyBadge = t.is_sticky ? `<span class="tw-badge tw-badge-sticky"><i class="bi bi-pin-fill"></i> Sticky</span>` : "";

  const thumb = t.cover_url
    ? `<img class="tw-card-thumb" src="${escHtml(t.cover_url)}" alt="" loading="lazy" data-lightbox="${escHtml(t.cover_url)}" onerror="this.outerHTML='<div class=\\'tw-card-thumb-placeholder\\'><i class=\\'bi bi-film\\'></i></div>'">`
    : `<div class="tw-card-thumb-placeholder"><i class="bi bi-film"></i></div>`;

  const statsHTML = [
    `<span class="tw-stat-val tw-stat-seed">${fmt(t.seeds)}</span><span class="tw-stat-lbl">seed</span>`,
    `<span class="tw-stat-sep">·</span>`,
    `<span class="tw-stat-val tw-stat-leech">${fmt(t.leeches)}</span><span class="tw-stat-lbl">leech</span>`,
    t.completed > 0 ? `<span class="tw-stat-sep">·</span><span class="tw-stat-val tw-stat-completed">${fmt(t.completed)}</span><span class="tw-stat-lbl">dl</span>` : "",
    t.file_size ? `<span class="tw-stat-sep">·</span><span class="tw-stat-lbl">${escHtml(t.file_size)}</span>` : "",
  ].join("");

  const dlBadges = [
    t.downloaded_local ? `<span class="tw-badge tw-badge-dl-local"><i class="bi bi-check-lg"></i> Local</span>` : "",
    t.downloaded_nas   ? `<span class="tw-badge tw-badge-dl-nas"><i class="bi bi-check-lg"></i> NAS</span>` : "",
  ].filter(Boolean).join("");

  const actions = readOnly ? "" : `
    <div class="tw-card-actions">
      <button class="tw-action-btn btn-dl-local${t.downloaded_local ? " done-local" : ""}" data-id="${t.id}" data-title="${escHtml(t.title)}">
        <i class="bi bi-download"></i> Local
      </button>
      <button class="tw-action-btn btn-dl-nas${t.downloaded_nas ? " done-nas" : ""}" data-id="${t.id}">
        <i class="bi bi-folder-symlink"></i> NAS
      </button>
      <a class="tw-action-btn" href="/api/detail/${t.id}" target="_blank" rel="noopener">
        <i class="bi bi-box-arrow-up-right"></i>
      </a>
    </div>`;

  return `
  <div class="tw-card${t.downloaded_local || t.downloaded_nas ? " downloaded" : ""}${t.keyword_match ? " keyword-match" : ""}" data-id="${t.id}">
    ${thumb}
    <div class="tw-card-body">
      <div class="tw-card-meta">
        <span class="tw-card-time">${_fmtTime(t.posted_at)}</span>
        ${catBadge}
        ${stickyBadge}
      </div>
      <a class="tw-card-title tw-title-link" href="/api/detail/${t.id}" target="_blank" rel="noopener">${escHtml(t.title)}</a>
      <div class="tw-card-stats">${statsHTML}</div>
      ${dlBadges ? `<div class="tw-card-dl-badges">${dlBadges}</div>` : ""}
      ${actions}
    </div>
    ${kwStar}
  </div>`;
}
```

- [ ] **Step 3: Update status badge in updateStatusBadge() — running branch**

Find (inside the `if (running)` block, around line 680):
```js
    el.textContent = label;
    el.style.color = "var(--accent)";
```

Replace with:
```js
    el.textContent = "● " + label;
    el.classList.add("running");
    el.style.color = "";
```

- [ ] **Step 4: Update status badge — idle branch**

Find (inside the `else` block, around line 692):
```js
    el.textContent = status.last_scrape ? `อัปเดต: ${status.last_scrape}` : "";
    el.style.color = "";
```

Replace with:
```js
    el.textContent = status.last_scrape ? "◉ " + status.last_scrape : "◉ idle";
    el.classList.remove("running");
    el.style.color = "";
```

- [ ] **Step 5: Commit**

```bash
git add torrentwatch/static/app.js
git commit -m "feat(torrentwatch): update app.js — bottom nav selector, image-dominant cardHTML, status dot"
```

---

### Task 4: Smoke test

**Files:** none (read-only verification)

- [ ] **Step 1: Start local dev server**

```bash
cd torrentwatch && pip install -r requirements.txt -q && uvicorn main:app --port 5055 --reload
```

Open `http://localhost:5055` in browser. Check:
1. Bottom nav visible and tabs switch correctly
2. Cards show thumbnail + stats row (seed · leech · dl)
3. Keyword match shows `★ kw` badge top-right
4. Status badge shows `◉ idle` or `● scraping...`
5. Settings panel shows 5 cards (Sources, Threshold, Notification, Schedule, Danger Zone)
6. Toast appears above bottom nav (not hidden behind it)
7. Go-to-top button appears above bottom nav

- [ ] **Step 2: If server not available (NAS-only setup), skip to deploy**

Use the deploy skill: `/deploy` targeting `torrentwatch` stack. Verify on NAS URL.

- [ ] **Step 3: Add `.superpowers/` to .gitignore if not already there**

```bash
grep -q ".superpowers" .gitignore || echo ".superpowers/" >> .gitignore
git add .gitignore
git commit -m "chore: ignore .superpowers brainstorm artifacts"
```
