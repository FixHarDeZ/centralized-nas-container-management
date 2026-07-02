function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

let topicsById = {};
let editingId = null;

async function loadTopics() {
  const res = await fetch("/api/topics");
  const topics = await res.json();
  topicsById = Object.fromEntries(topics.map((t) => [t.id, t]));

  const totalToday = topics.reduce((s, t) => s + (t.downloaded_today || 0), 0);
  document.getElementById("total-today").innerHTML = `วันนี้ <b>${totalToday}</b> รูป`;

  const grid = document.getElementById("topics");
  grid.innerHTML = "";
  if (topics.length === 0) {
    grid.innerHTML = `<div class="empty-state">ยังไม่มี topic — เพิ่มด้านบน</div>`;
    return;
  }

  for (const t of topics) {
    const counts = t.counts_by_purpose || {};
    const purposeChips = t.purposes
      .map((p) => {
        const n = counts[p] || 0;
        return `<span class="pchip${n === 0 ? " empty" : ""}">${escapeHtml(p)} <span class="n">${n}</span></span>`;
      })
      .join("");

    const terms = t.search_terms
      ? `<div class="terms">🔎 ${escapeHtml(t.search_terms.join(", "))}</div>`
      : `<div class="terms ai">🔎 AI คิดให้</div>`;

    const sources = (t.sources || ["wallhaven"]).map((s) => escapeHtml(s)).join(" + ");
    const sourceLine = `<div class="terms">🌐 ${sources}</div>`;

    const card = document.createElement("div");
    card.className = "topic" + (t.enabled ? "" : " disabled");
    card.innerHTML = `
      <div class="topic-head">
        <span class="q">${escapeHtml(t.query)}</span>
        <span class="badge ${t.enabled ? "on" : "off"}">${t.enabled ? "เปิด" : "หยุด"}</span>
      </div>
      ${terms}
      ${sourceLine}
      <div class="purposes">${purposeChips}</div>
      <div class="meta">
        <span>รอบ/วัน <b>${t.frequency_per_day}</b></span>
        <span>รูป/รอบ <b>${t.max_new_per_cycle}</b></span>
        <span>วันนี้ <b>${t.downloaded_today}</b></span>
      </div>
      <div class="topic-actions">
        <button class="primary" data-action="run" data-id="${t.id}">Scout ตอนนี้</button>
        <button data-action="edit" data-id="${t.id}">แก้ไข</button>
        <button data-action="toggle" data-id="${t.id}" data-enabled="${t.enabled ? "true" : "false"}">${t.enabled ? "หยุด" : "เปิด"}</button>
        <button class="danger" data-action="delete" data-id="${t.id}">ลบ</button>
      </div>`;
    grid.appendChild(card);
  }
}

function setFormMode(editing) {
  document.getElementById("form-title").textContent = editing ? "แก้ไข Topic" : "เพิ่ม Topic";
  document.getElementById("submit-btn").textContent = editing ? "บันทึก" : "เพิ่ม Topic";
  document.getElementById("cancel-edit").style.display = editing ? "" : "none";
}

function startEdit(id) {
  const t = topicsById[id];
  if (!t) return;
  editingId = id;
  document.getElementById("query").value = t.query;
  document.getElementById("search_terms").value = t.search_terms ? t.search_terms.join(", ") : "";
  for (const c of document.querySelectorAll('input[name="purpose"]')) {
    c.checked = t.purposes.includes(c.value);
  }
  const srcs = t.sources || ["wallhaven"];
  for (const c of document.querySelectorAll('input[name="source"]')) {
    c.checked = srcs.includes(c.value);
  }
  document.getElementById("frequency").value = t.frequency_per_day;
  document.getElementById("max_new").value = t.max_new_per_cycle;
  setFormMode(true);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function cancelEdit() {
  editingId = null;
  document.getElementById("topic-form").reset();
  setFormMode(false);
}

document.getElementById("cancel-edit").addEventListener("click", cancelEdit);

document.getElementById("topic-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const purposes = Array.from(document.querySelectorAll('input[name="purpose"]:checked')).map((c) => c.value);
  if (purposes.length === 0) {
    alert("เลือกอย่างน้อย 1 purpose");
    return;
  }
  const sources = Array.from(document.querySelectorAll('input[name="source"]:checked')).map((c) => c.value);
  if (sources.length === 0) {
    alert("เลือกอย่างน้อย 1 source");
    return;
  }
  const payload = {
    query: document.getElementById("query").value,
    purposes,
    sources,
    frequency_per_day: Number(document.getElementById("frequency").value),
    max_new_per_cycle: Number(document.getElementById("max_new").value),
  };
  const searchTermsRaw = document.getElementById("search_terms").value.trim();
  if (searchTermsRaw) {
    payload.search_terms = searchTermsRaw.split(",").map((s) => s.trim()).filter(Boolean);
  }
  if (editingId) {
    await fetch(`/api/topics/${editingId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    editingId = null;
  } else {
    await fetch("/api/topics", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }
  e.target.reset();
  setFormMode(false);
  loadTopics();
});

document.getElementById("topics").addEventListener("click", async (e) => {
  const btn = e.target.closest("button");
  if (!btn) return;
  const id = btn.dataset.id;
  if (btn.dataset.action === "delete") {
    if (!confirm("ลบ topic นี้?")) return;
    await fetch(`/api/topics/${id}`, { method: "DELETE" });
  } else if (btn.dataset.action === "toggle") {
    const enabled = btn.dataset.enabled === "true";
    await fetch(`/api/topics/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: !enabled }),
    });
  } else if (btn.dataset.action === "run") {
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = "กำลัง scout...";
    try {
      const res = await fetch(`/api/topics/${id}/run`, { method: "POST" });
      const data = await res.json();
      alert(res.ok ? `Scout เสร็จ: โหลดรูปใหม่ ${data.downloaded} รูป` : `Scout ล้มเหลว: ${data.detail}`);
    } finally {
      btn.disabled = false;
      btn.textContent = originalText;
    }
    loadTopics();
    return;
  } else if (btn.dataset.action === "edit") {
    startEdit(Number(id));
    return;
  }
  loadTopics();
});

loadTopics();
