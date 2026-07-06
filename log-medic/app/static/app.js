/* ── Toast ── */
function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateX(1rem)";
    toast.style.transition = "all .2s";
    setTimeout(() => toast.remove(), 200);
  }, 3500);
}

/* ── Tab switching ── */
function showTab(id) {
  document.querySelectorAll(".tab-content").forEach((el) => el.classList.remove("active"));
  document.querySelectorAll(".tab-btn").forEach((btn) => btn.classList.remove("active"));
  document.getElementById(id).classList.add("active");
  // find the matching tab button
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    if (btn.textContent.trim().toLowerCase() === id) btn.classList.add("active");
  });
  if (id === "events") loadEvents();
  if (id === "containers") loadContainers();
}

/* ── Badge helper ── */
function badge(text, extraClass) {
  return `<span class="badge ${extraClass || `badge-${text}`}">${text}</span>`;
}

/* ── Containers ── */
async function loadContainers() {
  try {
    const res = await fetch("/api/containers");
    const rows = await res.json();
    const tbody = document.querySelector("#containers-table tbody");
    tbody.innerHTML = "";

    if (rows.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" class="empty-state">No containers yet. Add one above.</td></tr>`;
      return;
    }

    for (const c of rows) {
      if (!c.name) continue;
      const tr = document.createElement("tr");
      const isMonitored = c.maturity !== undefined;
      const maturityOptions = ["dev", "staging", "stable"]
        .map((m) => `<option value="${m}" ${c.maturity === m ? "selected" : ""}>${m}</option>`)
        .join("");

      tr.innerHTML = `
        <td style="font-weight:600">${c.name}</td>
        <td>
          ${isMonitored
            ? `<select class="maturity-select" onchange="changeMaturity('${c.name}', this.value)">${maturityOptions}</select>`
            : `<span class="badge badge-dev">not added</span>`
          }
        </td>
        <td>
          ${isMonitored
            ? `<label class="toggle">
                <input type="checkbox" ${c.notify_only ? "checked" : ""} onchange="patchContainer('${c.name}', {notify_only: this.checked ? 1 : 0})" />
                <span class="toggle-slider"></span>
              </label>`
            : "—"
          }
        </td>
        <td>
          ${isMonitored
            ? `<label class="toggle">
                <input type="checkbox" ${c.paused ? "checked" : ""} onchange="patchContainer('${c.name}', {paused: this.checked ? 1 : 0})" />
                <span class="toggle-slider"></span>
              </label>`
            : "—"
          }
        </td>
        <td>
          <div class="actions">
            ${!isMonitored
              ? `<button class="btn btn-sm btn-primary" onclick="quickAdd('${c.name}')">Add</button>`
              : `<button class="btn btn-sm btn-danger" onclick="removeContainer('${c.name}')">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                  Remove
                </button>`
            }
          </div>
        </td>`;
      tbody.appendChild(tr);
    }
  } catch (e) {
    showToast("Failed to load containers", "error");
  }
}

async function addContainer() {
  const name = document.getElementById("add-name").value.trim();
  if (!name) return showToast("Container name is required", "error");
  const repo = document.getElementById("add-repo").value.trim() || null;
  const subdir = document.getElementById("add-subdir").value.trim() || null;
  const maturity = document.getElementById("add-maturity").value;
  const notify_only = document.getElementById("add-notify-only").checked;

  try {
    const res = await fetch("/api/containers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, repo, subdir, maturity, notify_only }),
    });
    if (!res.ok) {
      const err = await res.json();
      return showToast(err.detail || "Failed to add container", "error");
    }
    showToast(`Added ${name}`, "success");
    document.getElementById("add-name").value = "";
    document.getElementById("add-repo").value = "";
    document.getElementById("add-subdir").value = "";
    document.getElementById("add-notify-only").checked = false;
    loadContainers();
  } catch (e) {
    showToast("Network error", "error");
  }
}

async function quickAdd(name) {
  try {
    const res = await fetch("/api/containers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, maturity: "dev" }),
    });
    if (!res.ok) {
      const err = await res.json();
      return showToast(err.detail || "Failed to add", "error");
    }
    showToast(`Added ${name}`, "success");
    loadContainers();
  } catch (e) {
    showToast("Network error", "error");
  }
}

async function changeMaturity(name, maturity) {
  try {
    const res = await fetch(`/api/containers/${name}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ maturity }),
    });
    if (!res.ok) return showToast("Failed to update maturity", "error");
    showToast(`${name} → ${maturity}`, "success");
  } catch (e) {
    showToast("Network error", "error");
  }
}

async function patchContainer(name, payload) {
  try {
    const res = await fetch(`/api/containers/${name}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) return showToast("Failed to update", "error");
    const key = Object.keys(payload)[0];
    const val = payload[key];
    showToast(`${name}: ${key} = ${val ? "on" : "off"}`, "success");
    loadContainers();
  } catch (e) {
    showToast("Network error", "error");
  }
}

async function removeContainer(name) {
  if (!confirm(`Remove ${name} from monitoring?\nEvent history will be kept.`)) return;
  try {
    await fetch(`/api/containers/${name}`, { method: "DELETE" });
    showToast(`Removed ${name}`, "info");
    loadContainers();
  } catch (e) {
    showToast("Network error", "error");
  }
}

/* ── Events ── */
async function loadEvents() {
  try {
    const res = await fetch("/api/events?limit=50");
    const rows = await res.json();
    const tbody = document.querySelector("#events-table tbody");
    tbody.innerHTML = "";

    if (rows.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" class="empty-state">No events recorded yet.</td></tr>`;
      return;
    }

    for (const e of rows) {
      const tr = document.createElement("tr");
      const time = new Date(e.last_seen).toLocaleString("en-GB", {
        day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
      });
      tr.innerHTML = `
        <td style="white-space:nowrap;color:var(--text-secondary)">${time}</td>
        <td style="font-weight:600">${e.container}</td>
        <td><code style="font-size:.75rem;color:var(--text-muted)">${e.fingerprint}</code></td>
        <td>${e.count}</td>
        <td>${badge(e.status)}</td>
        <td>${e.verdict ? badge(e.verdict, `badge-verdict-${e.verdict}`) : "—"}</td>
        <td style="color:var(--text-secondary)">${e.gate_reason || "—"}</td>`;
      tbody.appendChild(tr);
    }
  } catch (e) {
    showToast("Failed to load events", "error");
  }
}

/* ── Watcher control ── */
let watcherPaused = false;
async function toggleWatcher() {
  const endpoint = watcherPaused ? "resume" : "pause";
  try {
    await fetch(`/api/watcher/${endpoint}`, { method: "POST" });
    watcherPaused = !watcherPaused;
    updateWatcherUI();
    showToast(`Watcher ${watcherPaused ? "paused" : "resumed"}`, "info");
  } catch (e) {
    showToast("Failed to toggle watcher", "error");
  }
}

function updateWatcherUI() {
  const pill = document.getElementById("watcher-status");
  const label = document.getElementById("watcher-label");
  const btn = document.getElementById("watcher-toggle");

  if (watcherPaused) {
    pill.className = "watcher-pill paused";
    label.textContent = "paused";
    btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg> Resume`;
  } else {
    pill.className = "watcher-pill running";
    label.textContent = "running";
    btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg> Pause`;
  }
}

/* ── Test notification ── */
async function testNotification() {
  const btn = document.getElementById("btn-test-noti");
  btn.disabled = true;
  btn.style.opacity = "0.6";
  try {
    const res = await fetch("/api/notify/test", { method: "POST" });
    if (res.ok) {
      showToast("Test notification sent!", "success");
    } else {
      const err = await res.json();
      showToast(err.detail?.errors?.join(", ") || "Notification failed", "error");
    }
  } catch (e) {
    showToast("Network error", "error");
  } finally {
    btn.disabled = false;
    btn.style.opacity = "1";
  }
}

/* ── Init ── */
loadContainers();
