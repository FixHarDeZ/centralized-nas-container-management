function showTab(id) {
  document.querySelectorAll(".tab-content").forEach((el) => el.classList.remove("active"));
  document.getElementById(id).classList.add("active");
  if (id === "events") loadEvents();
  if (id === "containers") loadContainers();
}

async function loadContainers() {
  const res = await fetch("/api/containers");
  const rows = await res.json();
  const tbody = document.querySelector("#containers-table tbody");
  tbody.innerHTML = "";
  for (const c of rows) {
    if (!c.name) continue;
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${c.name}</td>
      <td>${c.maturity ?? "-"}</td>
      <td>${c.notify_only ? "yes" : "no"}</td>
      <td>${c.paused ? "yes" : "no"}</td>
      <td>
        <button onclick="patchContainer('${c.name}', {paused: ${c.paused ? 0 : 1}})">${c.paused ? "resume" : "pause"}</button>
        <button onclick="removeContainer('${c.name}')">remove</button>
      </td>`;
    tbody.appendChild(tr);
  }
}

async function addContainer() {
  const name = document.getElementById("add-name").value.trim();
  if (!name) return;
  const repo = document.getElementById("add-repo").value.trim() || null;
  const subdir = document.getElementById("add-subdir").value.trim() || null;
  const maturity = document.getElementById("add-maturity").value;
  const notify_only = document.getElementById("add-notify-only").checked;
  await fetch("/api/containers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, repo, subdir, maturity, notify_only }),
  });
  loadContainers();
}

async function patchContainer(name, payload) {
  await fetch(`/api/containers/${name}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  loadContainers();
}

async function removeContainer(name) {
  if (!confirm(`Remove ${name} from monitoring? (event history is kept) Confirm again to proceed.`)) return;
  await fetch(`/api/containers/${name}`, { method: "DELETE" });
  loadContainers();
}

async function loadEvents() {
  const res = await fetch("/api/events?limit=50");
  const rows = await res.json();
  const tbody = document.querySelector("#events-table tbody");
  tbody.innerHTML = "";
  for (const e of rows) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${e.last_seen}</td><td>${e.container}</td><td>${e.fingerprint}</td><td>${e.count}</td><td>${e.status}</td><td>${e.verdict ?? "-"}</td><td>${e.gate_reason ?? "-"}</td>`;
    tbody.appendChild(tr);
  }
}

let watcherPaused = false;
async function toggleWatcher() {
  const endpoint = watcherPaused ? "resume" : "pause";
  await fetch(`/api/watcher/${endpoint}`, { method: "POST" });
  watcherPaused = !watcherPaused;
  document.getElementById("watcher-toggle").textContent = watcherPaused ? "Resume watcher" : "Pause watcher";
}

loadContainers();
