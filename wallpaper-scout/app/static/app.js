async function loadTopics() {
  const res = await fetch("/api/topics");
  const topics = await res.json();
  const tbody = document.querySelector("#topics-table tbody");
  tbody.innerHTML = "";
  for (const t of topics) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${t.query}</td>
      <td>${t.purposes.join(", ")}</td>
      <td>${t.frequency_per_day}</td>
      <td>${t.max_new_per_cycle}</td>
      <td>${t.downloaded_today}</td>
      <td>${t.enabled ? "เปิด" : "หยุด"}</td>
      <td>
        <button data-action="toggle" data-id="${t.id}" data-enabled="${t.enabled ? "true" : "false"}">${t.enabled ? "หยุด" : "เปิด"}</button>
        <button data-action="delete" data-id="${t.id}">ลบ</button>
      </td>`;
    tbody.appendChild(tr);
  }
}

document.getElementById("topic-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const purposes = Array.from(document.querySelectorAll('input[name="purpose"]:checked')).map((c) => c.value);
  if (purposes.length === 0) {
    alert("เลือกอย่างน้อย 1 purpose");
    return;
  }
  await fetch("/api/topics", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query: document.getElementById("query").value,
      purposes,
      frequency_per_day: Number(document.getElementById("frequency").value),
      max_new_per_cycle: Number(document.getElementById("max_new").value),
    }),
  });
  e.target.reset();
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
  }
  loadTopics();
});

loadTopics();
