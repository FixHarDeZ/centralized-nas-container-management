// ---------- theme ----------
const root = document.documentElement;
const savedTheme = localStorage.getItem("theme")
  || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
setTheme(savedTheme);
document.getElementById("theme-toggle").onclick = () =>
  setTheme(root.dataset.theme === "dark" ? "light" : "dark");
function setTheme(t) {
  root.dataset.theme = t;
  localStorage.setItem("theme", t);
  document.getElementById("theme-toggle").textContent = t === "dark" ? "☀️" : "🌙";
}

// ---------- helpers ----------
const $ = (id) => document.getElementById(id);
function human(n) {
  let f = n;
  for (const u of ["B", "KB", "MB", "GB", "TB"]) {
    if (f < 1024 || u === "TB") return `${f.toFixed(1)}${u}`;
    f /= 1024;
  }
}
function fmtDate(mtime) {
  return new Date(mtime * 1000).toISOString().slice(0, 10);
}
async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}
function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(t._h);
  t._h = setTimeout(() => (t.hidden = true), 3200);
}
const esc = (s) => String(s).replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// generic confirm modal
function confirmModal({ title, sub, items = [], confirmLabel = "Confirm", onConfirm }) {
  $("modal-title").textContent = title;
  $("modal-sub").innerHTML = sub || "";
  $("modal-list").innerHTML = items.map((i) => `<li>${i}</li>`).join("");
  $("modal-confirm").textContent = confirmLabel;
  $("modal").hidden = false;
  $("modal-cancel").onclick = () => ($("modal").hidden = true);
  $("modal-confirm").onclick = async () => {
    $("modal").hidden = true;
    await onConfirm();
  };
}

// ---------- tabs ----------
document.querySelectorAll(".tab").forEach((btn) => {
  btn.onclick = () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b === btn));
    const tab = btn.dataset.tab;
    $("tab-dupes").hidden = tab !== "dupes";
    $("tab-masked").hidden = tab !== "masked";
    $("tab-recycle").hidden = tab !== "recycle";
    $("tab-history").hidden = tab !== "history";
    if (tab === "masked") loadMasks();
    if (tab === "recycle") loadRecycle();
    if (tab === "history") loadHistory();
  };
});

// ---------- jump to top ----------
const toTop = $("to-top");
addEventListener("scroll", () => { toTop.hidden = scrollY < 400; });
toTop.onclick = () => scrollTo({ top: 0, behavior: "smooth" });

// ---------- init ----------
(async function () {
  try {
    const { roots } = await api("/api/roots");
    const sel = $("root");
    sel.innerHTML = roots.map((r) => `<option>${esc(r)}</option>`).join("");
    if (!roots.length) {
      sel.innerHTML = "<option>(no roots configured)</option>";
      $("scan-btn").disabled = true;
    }
  } catch (e) {
    toast("Failed to load roots: " + e.message);
  }
  loadTrash();
})();

// ---------- scan ----------
$("scan-btn").onclick = async () => {
  const rootv = $("root").value;
  const subpath = $("subpath").value.trim();
  const status = $("status");
  $("results").innerHTML = "";
  $("empty").hidden = true;
  status.hidden = false;
  status.innerHTML = `<div class="spinner"></div> Scanning ${esc(rootv)}${subpath ? "/" + esc(subpath) : ""} …`;
  $("scan-btn").disabled = true;
  try {
    const { job_id } = await api("/api/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ root: rootv, subpath: subpath || null }),
    });
    await poll(job_id);
  } catch (e) {
    status.innerHTML = "⚠️ " + e.message;
  } finally {
    $("scan-btn").disabled = false;
  }
};

async function poll(jobId) {
  const status = $("status");
  for (;;) {
    const job = await api(`/api/scan/${jobId}`);
    if (job.status === "error") {
      status.innerHTML = "⚠️ Scan failed: " + (job.error || "unknown");
      return;
    }
    if (job.status === "done") {
      status.innerHTML =
        `Scanned <b>${job.total_files}</b> videos · <b>${job.dup_groups}</b> duplicate groups`;
      const { groups } = await api(`/api/groups/${jobId}`);
      render(groups);
      return;
    }
    await new Promise((r) => setTimeout(r, 800));
  }
}

// ---------- render duplicates ----------
function render(groups) {
  const box = $("results");
  box.innerHTML = "";
  $("empty").hidden = groups.length > 0;
  for (const g of groups) box.appendChild(groupEl(g));
}

function groupEl(g) {
  const el = document.createElement("section");
  el.className = "group";
  const badge = g.multipart
    ? `<span class="badge" title="cd1/cd2/A·B — likely one title in parts, keep all">multi-part</span>`
    : "";
  el.innerHTML = `
    <div class="group-head">
      <span class="code">${esc(g.code)}</span>
      <span class="count">${g.files.length} files</span>
      ${badge}
      <button class="btn sm mask-btn" title="These are actually different — keep all, hide this group">Not a duplicate</button>
      <button class="btn danger sm recycle-btn">Recycle un-kept</button>
    </div>`;
  g.files.forEach((f, i) => el.appendChild(fileEl(f, i === 0)));
  el.querySelector(".recycle-btn").onclick = () => recycleGroup(el, g);
  el.querySelector(".mask-btn").onclick = () => maskGroup(el, g);
  return el;
}

function fileEl(f, kept) {
  const el = document.createElement("div");
  el.className = "file" + (kept ? " kept" : " marked-delete");
  el.dataset.path = f.path;
  const res = f.res && f.res !== "-" ? `<span class="pill">${esc(f.res)}</span>` : "";
  const part = f.part ? `<span class="pill">${esc(f.part)}</span>` : "";
  el.innerHTML = `
    <label class="keep-toggle">
      <input type="checkbox" ${kept ? "checked" : ""}> keep
    </label>
    <div class="file-meta">
      <div class="file-name" title="${esc(f.name)}">${esc(f.name)}</div>
      <div class="file-sub">${res}${part}${fmtDate(f.mtime)} · ${esc(f.path)}</div>
    </div>
    <button class="icon-btn sm rename-btn" title="Rename">✎</button>
    <span class="file-size">${human(f.size)}</span>`;
  const cb = el.querySelector("input");
  cb.onchange = () => {
    el.classList.toggle("kept", cb.checked);
    el.classList.toggle("marked-delete", !cb.checked);
  };
  el.querySelector(".rename-btn").onclick = () => startRename(el);
  return el;
}

// ---------- rename (same-folder only) ----------
function startRename(fileRow) {
  if (fileRow.querySelector(".rename-input")) return; // already editing
  const nameDiv = fileRow.querySelector(".file-name");
  const curName = fileRow.dataset.path.split("/").pop();
  const input = document.createElement("input");
  input.type = "text";
  input.className = "rename-input";
  input.value = curName;
  nameDiv.replaceWith(input);
  input.focus();
  input.select();

  const restore = (name) => {
    const d = document.createElement("div");
    d.className = "file-name";
    d.title = name;
    d.textContent = name;
    if (input.isConnected) input.replaceWith(d);
    return d;
  };

  let done = false;
  input.onkeydown = async (e) => {
    if (e.key === "Escape") { done = true; restore(curName); return; }
    if (e.key !== "Enter") return;
    done = true;
    const newName = input.value.trim();
    if (!newName || newName === curName) { restore(curName); return; }
    try {
      const res = await api("/api/rename", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: fileRow.dataset.path, new_name: newName }),
      });
      const oldPath = fileRow.dataset.path;
      fileRow.dataset.path = res.path;
      restore(res.name);
      const sub = fileRow.querySelector(".file-sub");
      sub.textContent = sub.textContent.replace(oldPath, res.path);
      toast("Renamed to " + res.name);
    } catch (err) {
      toast("Rename failed: " + err.message);
      restore(curName);
    }
  };
  input.onblur = () => { if (!done) restore(curName); };
}

// ---------- mask ----------
function maskGroup(groupRow, g) {
  confirmModal({
    title: "Mark as not a duplicate?",
    sub: `<b>${esc(g.code)}</b> — these ${g.files.length} files stay put and this group is hidden from future scans. Undo it any time under the <b>Masked</b> tab.`,
    items: g.files.map((f) => esc(f.name)),
    confirmLabel: "Not a duplicate",
    onConfirm: async () => {
      try {
        await api("/api/masks", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ paths: g.files.map((f) => f.path), code: g.code }),
        });
        groupRow.remove();
        toast("Masked " + g.code);
      } catch (e) {
        toast("Mask failed: " + e.message);
      }
    },
  });
}

async function loadMasks() {
  try {
    const { masks } = await api("/api/masks");
    const box = $("masked-list");
    box.innerHTML = "";
    $("masked-empty").hidden = masks.length > 0;
    for (const m of masks) box.appendChild(maskEl(m));
  } catch (e) {
    toast("Failed to load masks: " + e.message);
  }
}

function maskEl(m) {
  const el = document.createElement("section");
  el.className = "group";
  el.innerHTML = `
    <div class="group-head">
      <span class="code">${esc(m.code || "(no code)")}</span>
      <span class="count">${m.paths.length} files · masked ${fmtDate(m.created_at)}</span>
      <button class="btn sm unmask-btn">Unmask</button>
    </div>
    ${m.paths.map((p) => `<div class="file"><div class="file-meta"><div class="file-name" title="${esc(p)}">${esc(p.split("/").pop())}</div><div class="file-sub">${esc(p)}</div></div></div>`).join("")}`;
  el.querySelector(".unmask-btn").onclick = async () => {
    try {
      await api(`/api/masks/${m.id}`, { method: "DELETE" });
      el.remove();
      $("masked-empty").hidden = $("masked-list").children.length > 0;
      toast("Unmasked — reappears on next scan");
    } catch (e) {
      toast("Unmask failed: " + e.message);
    }
  };
  return el;
}

// ---------- recycle ----------
function recycleGroup(groupRow, g) {
  const doomed = [...groupRow.querySelectorAll(".file")]
    .filter((el) => !el.querySelector("input").checked)
    .map((el) => el.dataset.path);
  if (!doomed.length) return toast("Nothing marked for delete in this group.");
  confirmModal({
    title: "Move to recycle?",
    sub: "These files move to <code>.dupe-sweeper-trash</code> (reversible). Kept files stay.",
    items: doomed.map(esc),
    confirmLabel: "Move to recycle",
    onConfirm: async () => {
      try {
        const res = await api("/api/delete", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ paths: doomed }),
        });
        const okPaths = new Set(res.results.filter((r) => r.ok).map((r) => r.path));
        const failed = res.results.filter((r) => !r.ok);
        [...groupRow.querySelectorAll(".file")].forEach((el) => {
          if (okPaths.has(el.dataset.path)) el.remove();
        });
        let msg = `Recycled ${okPaths.size} file(s), freed ${human(res.freed)}`;
        if (failed.length) msg += ` · ${failed.length} failed`;
        toast(msg);
        loadTrash();
        loadRecycle();
      } catch (e) {
        toast("Delete failed: " + e.message);
      }
    },
  });
}

async function loadTrash() {
  try {
    const t = await api("/api/trash");
    $("recycle-info").textContent = `Recycle: ${human(t.size)} · ${t.count} files`;
    $("empty-btn").disabled = t.count === 0;
  } catch (e) {
    $("recycle-info").textContent = "Recycle: —";
  }
}

// ---------- recycle folder contents ----------
async function loadRecycle() {
  try {
    const { files } = await api("/api/trash/files");
    const box = $("recycle-list");
    box.innerHTML = "";
    $("recycle-empty").hidden = files.length > 0;
    // group by batch folder (one section per Recycle click), batch = "" last
    const batches = [];
    const byBatch = new Map();
    for (const f of files) {
      if (!byBatch.has(f.batch)) { byBatch.set(f.batch, []); batches.push(f.batch); }
      byBatch.get(f.batch).push(f);
    }
    for (const batch of batches) box.appendChild(recycleBatchEl(batch, byBatch.get(batch)));
  } catch (e) {
    toast("Failed to load recycle: " + e.message);
  }
}

function recycleBatchEl(batch, files) {
  const el = document.createElement("section");
  el.className = "group";
  const total = files.reduce((s, f) => s + f.size, 0);
  el.innerHTML = `
    <div class="group-head">
      <span class="code">${batch ? esc(batch.replace("_", " ")) : "(loose files)"}</span>
      <span class="count">${files.length} file(s) · ${human(total)}</span>
    </div>
    ${files.map((f) => `
      <div class="file" data-path="${esc(f.path)}">
        <div class="file-meta">
          <div class="file-name" title="${esc(f.path)}">${esc(f.name)}</div>
          <div class="file-sub">${esc(f.path)}</div>
        </div>
        <button class="btn sm restore-btn" title="Move back to its original location">Restore</button>
        <span class="file-size">${human(f.size)}</span>
      </div>`).join("")}`;
  el.querySelectorAll(".restore-btn").forEach((btn) => {
    btn.onclick = async () => {
      const row = btn.closest(".file");
      btn.disabled = true;
      try {
        const res = await api("/api/trash/restore", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: row.dataset.path }),
        });
        row.remove();
        if (!el.querySelector(".file")) el.remove();  // batch emptied
        $("recycle-empty").hidden = $("recycle-list").children.length > 0;
        toast("Restored to " + res.path);
        loadTrash();
      } catch (e) {
        btn.disabled = false;
        toast("Restore failed: " + e.message);
      }
    };
  });
  return el;
}

// ---------- history (deletion audit log) ----------
function fmtDateTime(ts) {
  return new Date(ts * 1000).toLocaleString();
}

async function loadHistory() {
  try {
    const { deletions } = await api("/api/deletions");
    const box = $("history-list");
    box.innerHTML = "";
    $("history-empty").hidden = deletions.length > 0;
    // flat rows grouped by batch (one section per Recycle click)
    const batches = [];
    const byBatch = new Map();
    for (const d of deletions) {
      if (!byBatch.has(d.batch)) { byBatch.set(d.batch, []); batches.push(d.batch); }
      byBatch.get(d.batch).push(d);
    }
    for (const batch of batches) box.appendChild(batchEl(batch, byBatch.get(batch)));
  } catch (e) {
    toast("Failed to load history: " + e.message);
  }
}

function batchEl(batch, rows) {
  const el = document.createElement("section");
  el.className = "group";
  const total = rows.reduce((s, r) => s + (r.ok ? r.size : 0), 0);
  const failed = rows.filter((r) => !r.ok).length;
  el.innerHTML = `
    <div class="group-head">
      <span class="code">${fmtDateTime(rows[0].created_at)}</span>
      <span class="count">${rows.length} file(s) · ${human(total)}${failed ? ` · ${failed} failed` : ""}</span>
    </div>
    ${rows.map((r) => `
      <div class="file${r.ok ? "" : " marked-delete"}">
        <div class="file-meta">
          <div class="file-name" title="${esc(r.path)}">${esc(r.name)}</div>
          <div class="file-sub">${r.ok ? "recycled" : "failed: " + esc(r.error || "?")} · ${esc(r.path)}</div>
        </div>
        <span class="file-size">${human(r.size)}</span>
      </div>`).join("")}`;
  return el;
}

$("empty-btn").onclick = () => {
  confirmModal({
    title: "Empty recycle — permanent!",
    sub: "This <b>permanently deletes</b> everything in <code>.dupe-sweeper-trash</code>. Cannot be undone.",
    items: [],
    confirmLabel: "Delete permanently",
    onConfirm: async () => {
      try {
        const res = await api("/api/trash/empty", { method: "POST" });
        toast(`Emptied recycle — freed ${human(res.size)} (${res.count} files)`);
        loadTrash();
        loadRecycle();
      } catch (e) {
        toast("Empty failed: " + e.message);
      }
    },
  });
};
