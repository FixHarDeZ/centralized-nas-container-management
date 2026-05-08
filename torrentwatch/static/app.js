/* TorrentWatch SPA */

// ─── State ────────────────────────────────────────────────────────────────────
const state = {
  tab: "today",
  sources: [],
  activeSource: { today: null, history: null, keywords: null },
  sort: { today: "seeds", history: "seeds" },
  filter: "all",
  historyDate: "",
  settings: {},
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
      chip.textContent = shortUrl(src.url);
      chip.title = src.url;
      chip.addEventListener("click", () => {
        state.activeSource[tab] = src.id;
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
  const data = await api("GET", `/torrents?source_id=${sid}&sort=${state.sort.today}&filter=${state.filter}`).catch(() => ({ torrents: [] }));
  renderTorrentList("list-today", data.torrents || [], false);

  // Update "last updated" from status
  const status = await api("GET", "/status").catch(() => ({}));
  const el = document.getElementById("last-updated-today");
  if (el && status.last_scrape) el.textContent = `อัปเดตล่าสุด: ${status.last_scrape}`;
  if (el && !status.last_scrape) el.textContent = "";
}

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
  const dlLocal  = t.downloaded_local ? `<span class="tw-badge tw-badge-dl-local"><i class="bi bi-check-lg"></i> Local</span>` : "";
  const dlNas    = t.downloaded_nas   ? `<span class="tw-badge tw-badge-dl-nas"><i class="bi bi-check-lg"></i> NAS</span>` : "";
  const kwBadge  = t.keyword_match    ? `<span class="tw-badge tw-badge-kw"><i class="bi bi-star-fill"></i> KW</span>` : "";
  const catBadge = t.category         ? `<span class="tw-badge tw-badge-cat">${escHtml(t.category)}</span>` : "";
  const thumb = t.cover_url
    ? `<img class="tw-card-thumb" src="${escHtml(t.cover_url)}" alt="" loading="lazy" onerror="this.outerHTML='<div class=\'tw-card-thumb-placeholder\'><i class=\'bi bi-film\'></i></div>'">`
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
      <a class="tw-card-title tw-title-link" href="${escHtml(t.detail_url)}" target="_blank" rel="noopener noreferrer">${escHtml(t.title)}</a>
      <div class="tw-card-meta">
        ${catBadge}
        <span class="tw-card-time">${_fmtTime(t.posted_at)}</span>
      </div>
      <div class="tw-card-badges">
        <span class="tw-badge tw-badge-seed"><i class="bi bi-arrow-up-circle-fill"></i>${t.seeds}</span>
        <span class="tw-badge tw-badge-leech"><i class="bi bi-arrow-down-circle-fill"></i>${t.leeches}</span>
        ${t.file_size ? `<span class="tw-badge tw-badge-info"><i class="bi bi-hdd"></i>${escHtml(t.file_size)}</span>` : ""}
        ${t.file_count > 1 ? `<span class="tw-badge tw-badge-info"><i class="bi bi-files"></i>${t.file_count}</span>` : ""}
        ${kwBadge}${dlLocal}${dlNas}
      </div>
      ${actions}
    </div>
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

document.querySelectorAll(".tw-filter-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tw-filter-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    state.filter = btn.dataset.filter;
    loadToday();
  });
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
  const [settings, sources] = await Promise.all([
    api("GET", "/settings").catch(() => ({})),
    api("GET", "/sources").catch(() => []),
  ]);
  state.settings = settings;
  state.sources = sources;

  document.getElementById("cfg-seed-min").value  = settings.seed_min  ?? 5;
  document.getElementById("cfg-leech-min").value = settings.leech_min ?? 10;
  document.getElementById("cfg-nas-path").value  = settings.nas_path  ?? "/downloads";

  const mode = settings.filter_mode ?? "and";
  const modeEl = document.getElementById("cfg-mode-" + mode);
  if (modeEl) modeEl.checked = true;

  // Scrape schedule
  const interval = settings.scrape_interval ?? "30";
  const allDay   = settings.scrape_all_day  ?? "0";
  document.getElementById("cfg-interval-" + interval).checked = true;
  document.getElementById(allDay === "1" ? "cfg-time-allday" : "cfg-time-night").checked = true;

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
    <div class="tw-source-item">
      <label class="tw-toggle-row" style="flex:1;gap:8px;margin:0">
        <input type="checkbox" class="tw-toggle src-toggle" data-src-id="${s.id}" ${s.enabled ? "checked" : ""}>
      </label>
      <span class="tw-source-url" title="${escHtml(s.url)}">${escHtml(s.url)}</span>
      <button class="tw-btn-icon src-reset" data-src-id="${s.id}" title="ล้างข้อมูลทั้งหมดของ source นี้"><i class="bi bi-arrow-counterclockwise"></i></button>
      <button class="tw-btn-danger src-del" data-src-id="${s.id}"><i class="bi bi-trash3"></i></button>
    </div>`).join("");

  list.querySelectorAll(".src-toggle").forEach(cb => {
    cb.addEventListener("change", async () => {
      await api("PATCH", `/sources/${cb.dataset.srcId}`, { enabled: cb.checked }).catch(() => {});
      await loadSources();
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
    seed_min:        document.getElementById("cfg-seed-min").value,
    leech_min:       document.getElementById("cfg-leech-min").value,
    nas_path:        document.getElementById("cfg-nas-path").value.trim(),
    filter_mode:     document.querySelector('input[name="filter_mode"]:checked')?.value ?? "and",
    scrape_interval: document.querySelector('input[name="scrape_interval"]:checked')?.value ?? "30",
    scrape_all_day:  document.querySelector('input[name="scrape_time"]:checked')?.value ?? "0",
  };
  try {
    await api("PUT", "/settings", payload);
    toast("บันทึกแล้ว", "success");
  } catch (e) {
    toast("บันทึกไม่สำเร็จ: " + e.message, "error");
  }
});

// ─── Scrape now ───────────────────────────────────────────────────────────────
document.getElementById("btn-scrape-now").addEventListener("click", async () => {
  const btn = document.getElementById("btn-scrape-now");
  btn.classList.add("spinning");
  try {
    const r = await api("POST", "/scrape");
    toast(r?.status === "already_running" ? "กำลัง scrape อยู่แล้ว" : "เริ่ม scrape แล้ว", "success");
    // Reload today after a brief delay
    setTimeout(loadToday, 3000);
  } catch (e) {
    toast("Scrape error: " + e.message, "error");
  } finally {
    setTimeout(() => btn.classList.remove("spinning"), 1500);
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
      label = `⟳ ${prog.source} หน้า ${(prog.page ?? 0) + 1} (${prog.found ?? 0} รายการ)`;
    }
    el.textContent = label;
    el.style.color = "var(--accent)";
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
    el.textContent = status.last_scrape ? `อัปเดต: ${status.last_scrape}` : "";
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

// ─── Init ─────────────────────────────────────────────────────────────────────
(async function init() {
  await loadSources();
  loadToday();
  updateStatusBadge();   // kicks off adaptive polling
})();
