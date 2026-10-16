"use strict";

const $ = (id) => document.getElementById(id);
const MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."];
const KIND = {
  first3: "3 ตัวท้ายรางวัลที่ 1",
  first3_tod: "โต๊ด 3 ตัวท้ายรางวัลที่ 1",
  last3f: "เลขหน้า 3 ตัว",
  last3b: "เลขท้าย 3 ตัว",
};

let current = null; // last pick shown, saved by the "บันทึก" button

function thaiDate(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return `${d} ${MONTHS[m - 1]} ${y + 543}`;
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of children.flat()) node.append(c);
  return node;
}

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), 2500);
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.status === 204 ? null : res.json();
}

function params() {
  return {
    draws: Number($("draws").value) || 2,
    picks: Number($("picks").value) || 5,
    scope: $("scope").value,
    permute: $("permute").checked,
  };
}

async function roll() {
  const btn = $("go");
  btn.disabled = true;
  btn.textContent = "กำลังสุ่ม…";
  try {
    const r = await api("/api/pick", { method: "POST", body: params() });
    current = r;
    $("result").hidden = false;
    $("numbers").replaceChildren(...r.numbers.map((n) => el("span", {}, n)));
    const used = r.draws_used.length
      ? `${r.draws_used.length} งวด (${r.draws_used.map(thaiDate).join(", ")})`
      : "ยังไม่มีผลรางวัลในเครื่อง";
    $("poolInfo").textContent =
      `ตัดออก ${r.excluded_count} เลข จาก ${used} · เหลือให้สุ่ม ${r.pool_size} เลข`;
    if (r.numbers.length < r.settings.picks) {
      toast(`เลขเหลือแค่ ${r.pool_size} ตัว สุ่มได้ไม่ครบ`);
    }
    $("exSummary").textContent = `เลขที่ถูกตัดออก (${r.excluded.length})`;
    $("excluded").replaceChildren(...r.excluded.map((n) => el("span", {}, n)));
    $("save").disabled = !r.numbers.length;
  } catch (e) {
    toast(`สุ่มไม่สำเร็จ: ${e.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "สุ่มเลข";
  }
}

async function savePick() {
  if (!current) return;
  $("save").disabled = true;
  try {
    await api("/api/picks", {
      method: "POST",
      body: { numbers: current.numbers, settings: current.settings },
    });
    toast("บันทึกแล้ว จะตรวจผลให้เมื่อออกรางวัล");
    loadPicks();
  } catch (e) {
    $("save").disabled = false;
    toast(`บันทึกไม่สำเร็จ: ${e.message}`);
  }
}

function settingsText(s) {
  const scope = s.scope === "all" ? "ทุกรางวัล" : "เฉพาะเลขหน้า/ท้าย";
  return `เลขอัตโนมัติ: ${s.picks} เลข · ย้อนหลัง ${s.draws} งวด · ${scope}${s.permute ? " · ตัดโต๊ด" : ""}`;
}

async function saveSettings(notifyOnly = false) {
  const body = notifyOnly
    ? { ...(await api("/api/settings")), notify: $("notify").checked }
    : { ...params(), notify: $("notify").checked };
  const s = await api("/api/settings", { method: "PUT", body });
  $("settingsInfo").textContent = settingsText(s);
  toast("บันทึกการตั้งค่าแล้ว");
}

async function loadSettings() {
  const s = await api("/api/settings");
  $("draws").value = s.draws;
  $("picks").value = s.picks;
  $("scope").value = s.scope;
  $("permute").checked = s.permute;
  $("notify").checked = s.notify;
  $("settingsInfo").textContent = settingsText(s);
}

async function loadDraws() {
  const draws = await api("/api/draws");
  $("latest").textContent = draws.length
    ? `ผลล่าสุดในเครื่อง: งวด ${thaiDate(draws[0].date)} · เก็บไว้ ${draws.length} งวด`
    : "ยังไม่มีผลรางวัลในเครื่อง — กำลังดึงจากกองสลาก";
  $("draws-list").replaceChildren(
    ...draws.slice(0, 12).map((d) =>
      el("li", {},
        el("div", {}, el("b", {}, thaiDate(d.date)), " ",
          el("span", { class: "when" }, `(${d.count} เลข 3 ตัว)`)),
        el("div", {}, "รางวัลที่ 1 ", el("b", { class: "mono" }, d.first)),
        el("div", {},
          "หน้า 3 ตัว ", el("b", { class: "mono" }, d.last3f.join(" ")),
          " · ท้าย 3 ตัว ", el("b", { class: "mono" }, d.last3b.join(" ")),
          " · 2 ตัว ", el("b", { class: "mono" }, d.last2.join(" ")))
      )
    )
  );
}

function pickLine(p) {
  const hits = Object.fromEntries((p.result?.hits || []).map((h) => [h.number, h.kinds]));
  const nums = p.numbers.map((n) => {
    const k = hits[n];
    if (!k) return el("span", {}, n);
    const cls = k.length === 1 && k[0] === "first3_tod" ? "tod" : "hit";
    return el("span", { class: cls, title: k.map((x) => KIND[x]).join(", ") }, n);
  });
  const spaced = nums.flatMap((n, i) => (i ? [" ", n] : [n]));
  const status = p.result_draw
    ? `ตรวจกับงวด ${thaiDate(p.result_draw)}${p.result.hits.length ? "" : " · ไม่ถูก"}`
    : "รอผล";
  const detail = (p.result?.hits || []).map((h) =>
    el("div", { class: "when" }, `${h.number} → ${h.kinds.map((x) => KIND[x]).join(", ")}`)
  );
  return el("li", {},
    el("button", { class: "ghost del", onclick: () => removePick(p.id) }, "ลบ"),
    el("div", { class: "when" },
      `${p.source === "auto" ? "อัตโนมัติ" : "บันทึกเอง"} · ${p.created_at.slice(0, 16)} · ${status}`),
    el("div", { class: "mono" }, spaced),
    detail
  );
}

async function removePick(id) {
  await api(`/api/picks/${id}`, { method: "DELETE" });
  loadPicks();
}

async function loadPicks() {
  const [picks, st] = await Promise.all([api("/api/picks"), api("/api/stats")]);
  $("picks-list").replaceChildren(...picks.map(pickLine));
  $("stats").textContent = st.picks
    ? `ตรวจแล้ว ${st.picks} ชุด ${st.numbers} เลข · ถูกตรงตัว ${st.exact_hits} · โต๊ด ${st.tod_hits} · สุ่มธรรมดาคาดว่าถูก ${st.expected.toFixed(2)}`
    : "ยังไม่มีเลขที่ตรวจผลแล้ว";
}

async function syncNow() {
  const btn = $("sync");
  btn.disabled = true;
  btn.textContent = "กำลังดึง…";
  try {
    await api("/api/sync", { method: "POST" });
    await Promise.all([loadDraws(), loadPicks()]);
    toast("อัปเดตแล้ว");
  } catch (e) {
    toast(`ดึงไม่สำเร็จ: ${e.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "ดึงผลล่าสุดตอนนี้";
  }
}

$("go").addEventListener("click", roll);
$("again").addEventListener("click", roll);
$("save").addEventListener("click", savePick);
$("saveSettings").addEventListener("click", () => saveSettings(false));
$("notify").addEventListener("change", () => saveSettings(true));
$("sync").addEventListener("click", syncNow);

loadSettings().catch((e) => toast(e.message));
loadDraws().catch((e) => toast(e.message));
loadPicks().catch((e) => toast(e.message));
