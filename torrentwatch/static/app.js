/* TorrentWatch SPA */

// ─── State ────────────────────────────────────────────────────────────────────
const state = {
  tab: "today",
  sources: [],
  activeSource: { today: null, history: null, keywords: null },
  sort: { today: "seeds", history: "seeds" },
  filter: "all",
  showSticky: true,
  historyDate: "",
  settings: {},
  search: "",
  activeCategory: "",
  catNames: {},   // cat_id → display name from /api/categories
};

// ─── API helpers ──────────────────────────────────────────────────────────────
async function api(method, path, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const r = await fetch("/api" + path, opts);
  if (!r.ok) {
    const msg = await r.text().catch(() => r.statusText);
    throw new Error(msg || r.statusText);
  }
  if (r.status === 204) return null;
  return r.json().catch(() => null);
}

// ─── Toast ────────────────────────────────────────────────────────────────────
let _toastTimer;
function toast(msg, type = "") {
  let el = document.getElementById("toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "toast";
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.className = "show " + type;
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => { el.className = ""; }, 2800);
}

// ─── Tabs ─────────────────────────────────────────────────────────────────────
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

function onTabActivate(tab) {
  if (tab === "today") loadToday();
  if (tab === "history") loadHistoryDates();
  if (tab === "keywords") loadKeywords();
  if (tab === "settings") loadSettings();
}

// ─── Sources ──────────────────────────────────────────────────────────────────
function shortUrl(url) {
  try {
    const u = new URL(url);
    return u.pathname.split("/").filter(Boolean).pop() || u.hostname;
  } catch { return url.slice(-20); }
}

function sourceLabel(src) {
  return (src.label && src.label.trim()) ? src.label.trim() : shortUrl(src.url);
}

async function loadSources() {
  state.sources = await api("GET", "/sources").catch(() => []);
  renderSourceChips();
}

function renderSourceChips() {
  ["today", "history", "keywords"].forEach(tab => {
    const bar = document.getElementById("source-chips-" + tab);
    if (!bar) return;
    bar.innerHTML = "";
    state.sources.forEach((src, i) => {
      if (!src.enabled && tab !== "settings") return;
      const chip = document.createElement("button");
      chip.className = "tw-source-chip" + (state.activeSource[tab] === src.id ? " active" : "");
      chip.textContent = sourceLabel(src);
      chip.title = src.url;
      chip.addEventListener("click", () => {
        state.activeSource[tab] = src.id;
        if (tab === "today") {
          state.activeCategory = "";
          state.search = "";
          const searchEl = document.getElementById("search-input");
          if (searchEl) searchEl.value = "";
        }
        renderSourceChips();
        if (tab === "today") loadToday();
        if (tab === "history") loadHistoryDates();
        if (tab === "keywords") loadKeywords();
      });
      bar.appendChild(chip);
    });
    // Auto-select first if none selected
    if (!state.activeSource[tab] && state.sources.length > 0) {
      const first = state.sources.find(s => tab !== "settings" ? s.enabled : true);
      if (first) {
        state.activeSource[tab] = first.id;
        renderSourceChips();
      }
    }
  });
}

// ─── Today ────────────────────────────────────────────────────────────────────
async function loadToday() {
  const sid = state.activeSource.today;
  if (!sid) return;
  // Always fetch all so we can compute counts for every bucket
  const data = await api("GET", `/torrents?source_id=${sid}&sort=${state.sort.today}&filter=all`).catch(() => ({ torrents: [] }));
  const all = data.torrents || [];

  // Compute counts
  const countAll    = all.length;
  const countKw     = all.filter(t => t.keyword_match).length;
  const countSticky = all.filter(t => t.is_sticky).length;
  _updateFilterCounts(countAll, countKw, countSticky);

  // Apply active filters client-side (category filter applied last so chip counts reflect pre-category state)
  let torrents = all;
  if (state.filter === "keyword") torrents = torrents.filter(t => t.keyword_match);
  if (!state.showSticky) torrents = torrents.filter(t => !t.is_sticky);
  if (state.search) {
    const q = state.search.toLowerCase();
    torrents = torrents.filter(t => t.title.toLowerCase().includes(q));
  }

  renderCategoryChips(torrents);
  if (state.activeCategory) torrents = torrents.filter(t => t.category === state.activeCategory);
  renderTorrentList("list-today", torrents, false);

  // Update "last updated" from status
  const status = await api("GET", "/status").catch(() => ({}));
  const el = document.getElementById("last-updated-today");
  if (el && status.last_scrape) el.textContent = `อัปเดตล่าสุด: ${status.last_scrape}`;
  if (el && !status.last_scrape) el.textContent = "";
}

function _updateFilterCounts(total, kw, sticky) {
  const btnAll    = document.querySelector('.tw-filter-btn[data-filter="all"]');
  const btnKw     = document.querySelector('.tw-filter-btn[data-filter="keyword"]');
  const btnSticky = document.getElementById("btn-toggle-sticky");
  const badge = n => n > 0 ? ` <span class="tw-count">${n}</span>` : "";
  if (btnAll)    btnAll.innerHTML    = `ทั้งหมด${badge(total)}`;
  if (btnKw)     btnKw.innerHTML     = `<i class="bi bi-star-fill"></i> Keyword${badge(kw)}`;
  if (btnSticky) btnSticky.innerHTML = `<i class="bi bi-pin-fill"></i> Sticky${badge(sticky)}`;
}

// ─── Category filter ──────────────────────────────────────────────────────────
function catLabel(cat) {
  return state.catNames[cat] || cat;
}

function renderCategoryChips(torrents) {
  const bar = document.getElementById("cat-bar-today");
  if (!bar) return;
  const catCounts = {};
  torrents.forEach(t => { if (t.category) catCounts[t.category] = (catCounts[t.category] || 0) + 1; });
  const catKeys = Object.keys(catCounts);
  if (!catKeys.length) { bar.style.display = "none"; return; }
  const labelOf = Object.fromEntries(catKeys.map(c => [c, catLabel(c)]));
  const cats = catKeys.sort((a, b) => labelOf[a].localeCompare(labelOf[b], "th"));
  bar.style.display = "flex";
  bar.innerHTML = [
    `<button class="tw-source-chip${!state.activeCategory ? " active" : ""}" data-cat="">ทั้งหมด <span class="tw-count">${torrents.length}</span></button>`,
    ...cats.map(c => `<button class="tw-source-chip${state.activeCategory === c ? " active" : ""}" data-cat="${escHtml(c)}">${escHtml(labelOf[c])} <span class="tw-count">${catCounts[c]}</span></button>`),
  ].join("");
  bar.querySelectorAll("[data-cat]").forEach(btn => {
    btn.addEventListener("click", () => {
      state.activeCategory = btn.dataset.cat;
      loadToday();
    });
  });
}

// ─── Search filter ────────────────────────────────────────────────────────────
document.getElementById("search-input").addEventListener("input", e => {
  state.search = e.target.value.trim();
  loadToday();
});

// ─── History ──────────────────────────────────────────────────────────────────
async function loadHistoryDates() {
  const sid = state.activeSource.history;
  if (!sid) return;
  const dates = await api("GET", `/history/dates?source_id=${sid}`).catch(() => []);
  const sel = document.getElementById("history-date-select");
  const prev = state.historyDate;
  sel.innerHTML = '<option value="">เลือกวันที่...</option>';
  dates.forEach(d => {
    const opt = document.createElement("option");
    opt.value = d; opt.textContent = d;
    sel.appendChild(opt);
  });
  if (prev && dates.includes(prev)) {
    sel.value = prev;
    loadHistory(prev);
  } else {
    document.getElementById("list-history").innerHTML = "";
  }
}

async function loadHistory(date) {
  const sid = state.activeSource.history;
  if (!sid || !date) return;
  const data = await api("GET", `/history?source_id=${sid}&date=${date}&sort=${state.sort.history}`).catch(() => ({ torrents: [] }));
  renderTorrentList("list-history", data.torrents || [], true);
}

document.getElementById("history-date-select").addEventListener("change", e => {
  state.historyDate = e.target.value;
  if (state.historyDate) loadHistory(state.historyDate);
  else document.getElementById("list-history").innerHTML = "";
});

// ─── Torrent card renderer ────────────────────────────────────────────────────
function renderTorrentList(listId, torrents, readOnly) {
  const list = document.getElementById(listId);
  if (!torrents.length) {
    list.innerHTML = `<div class="tw-empty"><i class="bi bi-inbox"></i>ไม่พบ torrent ในช่วงนี้</div>`;
    return;
  }
  list.innerHTML = torrents.map(t => cardHTML(t, readOnly)).join("");
  if (!readOnly) attachCardActions(list);
}

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

function attachCardActions(list) {
  list.querySelectorAll(".btn-dl-local").forEach(btn => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.id;
      const title = btn.dataset.title || "torrent";
      btn.classList.add("loading");
      try {
        const resp = await fetch(`/api/download/local/${id}`);
        if (!resp.ok) throw new Error(await resp.text());
        const blob = await resp.blob();
        const url  = URL.createObjectURL(blob);
        const a    = document.createElement("a");
        a.href = url; a.download = title.slice(0, 100) + ".torrent";
        a.click(); URL.revokeObjectURL(url);
        btn.classList.add("done-local");
        btn.closest(".tw-card").classList.add("downloaded");
        toast("ดาวน์โหลดแล้ว", "success");
      } catch (e) {
        toast("ดาวน์โหลดไม่สำเร็จ: " + e.message, "error");
      } finally {
        btn.classList.remove("loading");
      }
    });
  });

  list.querySelectorAll(".btn-dl-nas").forEach(btn => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.id;
      btn.classList.add("loading");
      try {
        const data = await api("POST", `/download/nas/${id}`);
        btn.classList.add("done-nas");
        btn.closest(".tw-card").classList.add("downloaded");
        toast(`ส่งไป NAS แล้ว: ${data.filename}`, "success");
      } catch (e) {
        toast("ส่ง NAS ไม่สำเร็จ: " + e.message, "error");
      } finally {
        btn.classList.remove("loading");
      }
    });
  });
}

// ─── Sort & filter controls ───────────────────────────────────────────────────
document.querySelectorAll("#panel-today .tw-sort-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("#panel-today .tw-sort-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    state.sort.today = btn.dataset.sort;
    loadToday();
  });
});

document.querySelectorAll("#panel-history .tw-sort-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("#panel-history .tw-sort-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    state.sort.history = btn.dataset.sort;
    if (state.historyDate) loadHistory(state.historyDate);
  });
});

document.querySelectorAll(".tw-filter-btn[data-filter]").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tw-filter-btn[data-filter]").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    state.filter = btn.dataset.filter;
    loadToday();
  });
});

document.getElementById("btn-toggle-sticky").addEventListener("click", () => {
  state.showSticky = !state.showSticky;
  document.getElementById("btn-toggle-sticky").classList.toggle("active", state.showSticky);
  loadToday();
});

// ─── Keywords ─────────────────────────────────────────────────────────────────
async function loadKeywords() {
  const sid = state.activeSource.keywords;
  if (!sid) return;
  const kws = await api("GET", `/keywords?source_id=${sid}`).catch(() => []);
  const list = document.getElementById("kw-list");
  if (!kws.length) {
    list.innerHTML = `<div class="tw-empty" style="padding:30px 0"><i class="bi bi-tags"></i>ยังไม่มี keyword</div>`;
    return;
  }
  list.innerHTML = kws.map(k => `
    <div class="tw-kw-item">
      <span class="tw-kw-text">${escHtml(k.keyword)}</span>
      <button class="tw-kw-del" data-kw-id="${k.id}"><i class="bi bi-x-lg"></i></button>
    </div>`).join("");
  list.querySelectorAll(".tw-kw-del").forEach(btn => {
    btn.addEventListener("click", async () => {
      await api("DELETE", `/keywords/${btn.dataset.kwId}`).catch(() => {});
      loadKeywords();
    });
  });
}

document.getElementById("btn-add-kw").addEventListener("click", async () => {
  const sid = state.activeSource.keywords;
  if (!sid) { toast("เลือก source ก่อน", "error"); return; }
  const input = document.getElementById("kw-input");
  const kw = input.value.trim();
  if (!kw) return;
  try {
    await api("POST", "/keywords", { source_id: sid, keyword: kw });
    input.value = "";
    loadKeywords();
    toast("เพิ่ม keyword แล้ว", "success");
  } catch (e) {
    toast("ไม่สำเร็จ: " + e.message, "error");
  }
});

document.getElementById("kw-input").addEventListener("keydown", e => {
  if (e.key === "Enter") document.getElementById("btn-add-kw").click();
});

// ─── Settings ─────────────────────────────────────────────────────────────────
async function loadSettings() {
  const [settings, sources, status] = await Promise.all([
    api("GET", "/settings").catch(() => ({})),
    api("GET", "/sources").catch(() => []),
    api("GET", "/status").catch(() => ({})),
  ]);
  state.settings = settings;
  state.sources = sources;

  document.getElementById("cfg-seed-min").value       = settings.seed_min      ?? 5;
  document.getElementById("cfg-leech-min").value      = settings.leech_min     ?? 10;
  document.getElementById("cfg-completed-min").value  = settings.completed_min ?? 20;

  const mode = settings.filter_mode ?? "and";
  const modeEl = document.getElementById("cfg-mode-" + mode);
  if (modeEl) modeEl.checked = true;

  document.getElementById("cfg-scrape-sticky").checked = settings.scrape_sticky === "1";
  document.getElementById("cfg-auto-dl").checked = settings.auto_download_nas === "1";
  document.getElementById("cfg-retention").value = settings.retention_days ?? 7;
  document.getElementById("cfg-line-notify").checked = settings.line_notify_keyword_enabled === "1";
  document.getElementById("cfg-telegram-notify").checked = settings.telegram_notify_keyword_enabled === "1";

  const hint = document.getElementById("line-status-hint");
  if (hint) {
    if (status.line_configured) {
      hint.textContent = "✓ LINE token ตั้งค่าแล้ว — พร้อมส่งแจ้งเตือน";
      hint.style.color = "var(--seed)";
    } else {
      hint.textContent = "⚠ ยังไม่ได้ตั้งค่า TORRENTWATCH_LINE_ACCESS_TOKEN / TORRENTWATCH_LINE_USER_ID ใน .env";
      hint.style.color = "#f59e0b";
    }
  }

  const tgHint = document.getElementById("telegram-status-hint");
  if (tgHint) {
    if (status.telegram_configured) {
      tgHint.textContent = "✓ Telegram Bot token + Chat ID ตั้งค่าแล้ว — พร้อมส่งแจ้งเตือน";
      tgHint.style.color = "var(--seed)";
    } else {
      tgHint.textContent = "⚠ ยังไม่ได้ตั้งค่า TORRENTWATCH_TELEGRAM_BOT_TOKEN / TORRENTWATCH_TELEGRAM_CHAT_ID ใน .env";
      tgHint.style.color = "#f59e0b";
    }
  }

  // Clear buttons per source
  const clearDiv = document.getElementById("clear-source-btns");
  clearDiv.innerHTML = sources.map(s => `
    <div class="tw-source-item">
      <span class="tw-source-url">${escHtml(s.url)}</span>
      <button class="tw-btn-danger clear-scrape-btn" data-src-id="${s.id}">
        <i class="bi bi-arrow-counterclockwise"></i> ล้าง & Scrape
      </button>
    </div>`).join("");
  clearDiv.querySelectorAll(".clear-scrape-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!confirm("ล้างข้อมูลทั้งหมดของ source นี้แล้ว scrape ใหม่?")) return;
      btn.disabled = true;
      btn.textContent = "กำลังล้าง...";
      await api("DELETE", `/debug/clear-all/${btn.dataset.srcId}`).catch(() => {});
      await api("POST", "/scrape").catch(() => {});
      toast("ล้างแล้ว กำลัง scrape ใหม่...", "success");
      btn.disabled = false;
      btn.innerHTML = '<i class="bi bi-arrow-counterclockwise"></i> ล้าง & Scrape';
      setTimeout(loadToday, 4000);
    });
  });

  renderSourcesList(sources);
}

function renderSourcesList(sources) {
  const list = document.getElementById("sources-list");
  if (!sources.length) {
    list.innerHTML = `<p style="color:var(--text-muted);font-size:13px">ยังไม่มี source</p>`;
    return;
  }
  list.innerHTML = sources.map(s => `
    <div class="tw-source-item" data-src-id="${s.id}">
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

  list.querySelectorAll(".src-toggle").forEach(cb => {
    cb.addEventListener("change", async () => {
      await api("PATCH", `/sources/${cb.dataset.srcId}`, { enabled: cb.checked }).catch(() => {});
      await loadSources();
    });
  });
  list.querySelectorAll(".src-rename").forEach(btn => {
    btn.addEventListener("click", () => {
      const row = btn.closest(".tw-source-item");
      const sid = btn.dataset.srcId;
      const currentLabel = btn.dataset.label;
      const displayEl = row.querySelector(".tw-source-display-label");

      // Build inline editor
      const wrap = row.querySelector(".tw-source-label-wrap");
      wrap.innerHTML = `
        <input class="tw-input-sm src-rename-input" type="text" value="${escHtml(currentLabel)}" placeholder="ชื่อที่แสดง (ว่าง = ใช้ชื่อ URL)" style="flex:1;min-width:0">
        <button class="tw-btn-icon src-rename-ok" title="บันทึก"><i class="bi bi-check-lg"></i></button>
        <button class="tw-btn-icon src-rename-cancel" title="ยกเลิก"><i class="bi bi-x-lg"></i></button>`;
      const input = wrap.querySelector(".src-rename-input");
      input.focus();
      input.select();

      const save = async () => {
        const label = input.value.trim();
        await api("PATCH", `/sources/${sid}/label`, { label }).catch(() => {});
        await loadSources();
        loadSettings();
        toast("เปลี่ยนชื่อแล้ว", "success");
      };
      wrap.querySelector(".src-rename-ok").addEventListener("click", save);
      wrap.querySelector(".src-rename-cancel").addEventListener("click", () => { loadSettings(); });
      input.addEventListener("keydown", e => {
        if (e.key === "Enter") save();
        if (e.key === "Escape") loadSettings();
      });
    });
  });

  list.querySelectorAll(".src-reset").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!confirm("ล้างข้อมูล torrent ทั้งหมดของ source นี้?\n(ข้อมูลจะถูก scrape ใหม่ครั้งต่อไป)")) return;
      await api("DELETE", `/debug/clear-all/${btn.dataset.srcId}`).catch(() => {});
      toast("ล้างข้อมูลแล้ว", "success");
    });
  });

  list.querySelectorAll(".src-del").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!confirm("ลบ source นี้ออก?")) return;
      await api("DELETE", `/sources/${btn.dataset.srcId}`).catch(() => {});
      await loadSources();
      loadSettings();
    });
  });
}

document.getElementById("btn-add-source").addEventListener("click", async () => {
  const input = document.getElementById("source-url-input");
  const url = input.value.trim();
  if (!url) return;
  try {
    await api("POST", "/sources", { url });
    input.value = "";
    await loadSources();
    loadSettings();
    toast("เพิ่ม source แล้ว", "success");
  } catch (e) {
    toast("ไม่สำเร็จ: " + e.message, "error");
  }
});

document.getElementById("btn-save-settings").addEventListener("click", async () => {
  const payload = {
    seed_min:                    document.getElementById("cfg-seed-min").value,
    leech_min:                   document.getElementById("cfg-leech-min").value,
    completed_min:               document.getElementById("cfg-completed-min").value,
    filter_mode:                 document.querySelector('input[name="filter_mode"]:checked')?.value ?? "and",
    scrape_sticky:               document.getElementById("cfg-scrape-sticky").checked ? "1" : "0",
    line_notify_keyword_enabled:     document.getElementById("cfg-line-notify").checked ? "1" : "0",
    telegram_notify_keyword_enabled: document.getElementById("cfg-telegram-notify").checked ? "1" : "0",
    auto_download_nas:               document.getElementById("cfg-auto-dl").checked ? "1" : "0",
    retention_days:              document.getElementById("cfg-retention").value,
  };
  try {
    await api("PUT", "/settings", payload);
    toast("บันทึกแล้ว", "success");
  } catch (e) {
    toast("บันทึกไม่สำเร็จ: " + e.message, "error");
  }
});

// ─── LINE test ────────────────────────────────────────────────────────────────
document.getElementById("btn-line-test").addEventListener("click", async () => {
  const btn = document.getElementById("btn-line-test");
  btn.disabled = true;
  btn.innerHTML = '<i class="bi bi-hourglass-split"></i> กำลังส่ง...';
  try {
    const r = await api("POST", "/line/test");
    toast(r?.message || "ส่งทดสอบแล้ว — ตรวจสอบ LINE", "success");
  } catch (e) {
    toast("ส่งไม่สำเร็จ: " + e.message, "error");
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-send"></i> ทดสอบส่ง LINE';
  }
});

// ─── Telegram test + get-chat-id ─────────────────────────────────────────────
document.getElementById("btn-telegram-test").addEventListener("click", async () => {
  const btn = document.getElementById("btn-telegram-test");
  btn.disabled = true;
  btn.innerHTML = '<i class="bi bi-hourglass-split"></i> กำลังส่ง...';
  try {
    const r = await api("POST", "/telegram/test");
    toast(r?.message || "ส่งทดสอบแล้ว — ตรวจสอบ Telegram", "success");
  } catch (e) {
    toast("ส่งไม่สำเร็จ: " + e.message, "error");
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-send"></i> ทดสอบส่ง Telegram';
  }
});

document.getElementById("btn-telegram-get-chat-id").addEventListener("click", async () => {
  const btn = document.getElementById("btn-telegram-get-chat-id");
  const resultDiv = document.getElementById("telegram-chat-id-result");
  btn.disabled = true;
  btn.innerHTML = '<i class="bi bi-hourglass-split"></i> กำลังดึงข้อมูล...';
  resultDiv.style.display = "none";
  try {
    const r = await api("GET", "/telegram/get-chat-id");
    if (!r.ok) {
      resultDiv.innerHTML = `<span style="color:#f59e0b">⚠ ${escHtml(r.error)}</span>`;
    } else if (!r.chats || r.chats.length === 0) {
      resultDiv.innerHTML = `<span style="color:#f59e0b">⚠ ไม่พบ chat — ลองส่งข้อความหา bot ก่อนแล้วลองใหม่</span>`;
    } else {
      resultDiv.innerHTML = r.chats.map(c =>
        `<div>💬 <b>${escHtml(c.name || "(no name)")}</b> [${escHtml(c.type)}]<br>Chat ID: <code style="user-select:all;background:var(--surface1);padding:1px 5px;border-radius:4px">${c.chat_id}</code></div>`
      ).join("<hr style='border-color:var(--surface1);margin:6px 0'>");
    }
    resultDiv.style.display = "block";
  } catch (e) {
    resultDiv.innerHTML = `<span style="color:#f87171">ข้อผิดพลาด: ${escHtml(e.message)}</span>`;
    resultDiv.style.display = "block";
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-search"></i> ค้นหา Chat ID';
  }
});

// ─── Scrape now ───────────────────────────────────────────────────────────────
document.getElementById("btn-scrape-now").addEventListener("click", async () => {
  const btn = document.getElementById("btn-scrape-now");
  btn.classList.add("spinning");
  try {
    const r = await api("POST", "/scrape");
    toast(r?.status === "already_running" ? "กำลัง scrape อยู่แล้ว" : "เริ่ม scrape แล้ว", "success");
    // Immediately switch to fast polling so the status badge updates right away
    updateStatusBadge();
  } catch (e) {
    toast("Scrape error: " + e.message, "error");
    btn.classList.remove("spinning");
  }
});

// ─── Status badge + scrape progress ──────────────────────────────────────────
let _wasRunning = false;
let _statusPollTimer = null;

async function updateStatusBadge() {
  const status = await api("GET", "/status").catch(() => ({}));
  const el = document.getElementById("status-badge");
  if (!el) return;

  const running = status.scrape_status === "running";
  const prog    = status.scrape_progress || {};
  const btn     = document.getElementById("btn-scrape-now");

  if (running) {
    // Show live progress
    let label = "กำลัง scrape...";
    if (prog.source) {
      const srcPart = prog.source_total > 1 ? `${prog.source} (${prog.source_idx}/${prog.source_total})` : prog.source;
      label = `⟳ ${srcPart} — หน้า ${(prog.page ?? 0) + 1} พบ ${prog.found ?? 0} รายการ`;
    }
    el.textContent = "● " + label;
    el.classList.add("running");
    el.style.color = "";
    if (btn) btn.classList.add("spinning");
    // Poll fast while running
    schedulePoll(1500);
    _wasRunning = true;
  } else {
    if (_wasRunning) {
      // Just finished — refresh the list
      _wasRunning = false;
      loadToday();
    }
    el.textContent = status.last_scrape ? "◉ " + status.last_scrape : "◉ idle";
    el.classList.remove("running");
    el.style.color = "";
    if (btn) btn.classList.remove("spinning");
    // Back to slow polling
    schedulePoll(60000);
  }
}

function schedulePoll(ms) {
  if (_statusPollTimer) clearTimeout(_statusPollTimer);
  _statusPollTimer = setTimeout(() => {
    updateStatusBadge();
  }, ms);
}

// ─── Utility ──────────────────────────────────────────────────────────────────
function escHtml(s) {
  return String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

function _fmtTime(posted_at) {
  if (!posted_at) return "";
  // "2026-05-08 16:01:47" → "08/05 16:01"
  const m = posted_at.match(/(\d{4})-(\d{2})-(\d{2})\s+(\d{2}:\d{2})/);
  if (!m) return "";
  return `${m[3]}/${m[2]} ${m[4]}`;
}

// ─── Go-to-top button ────────────────────────────────────────────────────────
(function () {
  const btn   = document.getElementById("btn-go-top");
  const getY  = () => Math.max(
    window.scrollY || 0,
    document.documentElement.scrollTop || 0,
    document.body.scrollTop || 0
  );
  const check = () => btn.classList.toggle("visible", getY() > 200);

  // Scroll events don't bubble — listen on every possible container
  window.addEventListener("scroll",               check, { passive: true });
  document.addEventListener("scroll",             check, { passive: true });
  document.documentElement.addEventListener("scroll", check, { passive: true });
  document.body.addEventListener("scroll",        check, { passive: true });

  btn.addEventListener("click", () => {
    window.scrollTo({ top: 0, behavior: "smooth" });
    document.documentElement.scrollTop = 0;
    document.body.scrollTop = 0;
  });
})();

// ─── Lightbox ─────────────────────────────────────────────────────────────────
(function () {
  const lb    = document.getElementById("lightbox");
  const lbImg = document.getElementById("lightbox-img");
  const lbClose = document.getElementById("lightbox-close");

  function openLightbox(src) {
    lbImg.src = src;
    lb.classList.add("open");
    document.body.style.overflow = "hidden";
  }
  function closeLightbox() {
    lb.classList.remove("open");
    document.body.style.overflow = "";
    lbImg.src = "";
  }

  // Delegate click on any [data-lightbox] image in the list
  document.addEventListener("click", e => {
    const img = e.target.closest("[data-lightbox]");
    if (img) { e.stopPropagation(); openLightbox(img.dataset.lightbox); return; }
    if (e.target === lb || e.target === lbImg) closeLightbox();
  });
  lbClose.addEventListener("click", closeLightbox);
  document.addEventListener("keydown", e => { if (e.key === "Escape") closeLightbox(); });
})();

// ─── Init ─────────────────────────────────────────────────────────────────────
(async function init() {
  document.getElementById("btn-toggle-sticky").classList.toggle("active", state.showSticky);
  state.catNames = await api("GET", "/categories").catch(() => ({}));
  await loadSources();
  loadToday();
  updateStatusBadge();   // kicks off adaptive polling
})();
