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
  const tbody = document.querySelector("#topics-table tbody");
  tbody.innerHTML = "";
  for (const t of topics) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(t.query)}</td>
      <td>${escapeHtml(t.purposes.join(", "))}</td>
      <td>${t.frequency_per_day}</td>
      <td>${t.max_new_per_cycle}</td>
      <td>${t.downloaded_today}</td>
      <td>${t.enabled ? "เปิด" : "หยุด"}</td>
      <td>
        <button data-action="run" data-id="${t.id}">Scout ตอนนี้</button>
        <button data-action="edit" data-id="${t.id}">แก้ไข</button>
        <button data-action="toggle" data-id="${t.id}" data-enabled="${t.enabled ? "true" : "false"}">${t.enabled ? "หยุด" : "เปิด"}</button>
        <button data-action="delete" data-id="${t.id}">ลบ</button>
      </td>`;
    tbody.appendChild(tr);
  }
}

function setFormMode(editing) {
  const form = document.getElementById("topic-form");
  form.querySelector('button[type="submit"]').textContent = editing ? "บันทึก" : "เพิ่ม Topic";
  document.getElementById("cancel-edit").style.display = editing ? "" : "none";
}

function startEdit(id) {
  const t = topicsById[id];
  if (!t) return;
  editingId = id;
  document.getElementById("query").value = t.query;
  for (const c of document.querySelectorAll('input[name="purpose"]')) {
    c.checked = t.purposes.includes(c.value);
  }
  document.getElementById("frequency").value = t.frequency_per_day;
  document.getElementById("max_new").value = t.max_new_per_cycle;
  setFormMode(true);
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
  const payload = {
    query: document.getElementById("query").value,
    purposes,
    frequency_per_day: Number(document.getElementById("frequency").value),
    max_new_per_cycle: Number(document.getElementById("max_new").value),
  };
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

document.querySelector("#topics-table tbody").addEventListener("click", async (e) => {
  const btn = e.target.closest("button");
  if (!btn) return;
  const id = btn.dataset.id;
  if (btn.dataset.action === "delete") {
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
      if (res.ok) {
        alert(`Scout เสร็จแล้ว: โหลดรูปใหม่ ${data.downloaded} รูป`);
      } else {
        alert(`Scout ล้มเหลว: ${data.detail}`);
      }
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
