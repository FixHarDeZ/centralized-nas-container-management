"use strict";

const $ = (id) => document.getElementById(id);
const MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."];
const KIND = { last2: "เลขท้าย 2 ตัว", first3: "3 ตัวท้ายรางวัลที่ 1", first3_tod: "โต๊ด 3 ตัวท้ายรางวัลที่ 1", last3f: "เลขหน้า 3 ตัว", last3b: "เลขท้าย 3 ตัว" };
let activeDigits = 3;
const profiles = {
  2: { savedSettings: null, draft: null, current: null, resultSaved: false },
  3: { savedSettings: null, draft: null, current: null, resultSaved: false },
};
let current = null;
let savedSettings = null;
let rolling = false;
let saving = false;
let resultSaved = false;
let settingsBusy = false;

function thaiDate(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return `${d} ${MONTHS[m - 1]} ${y + 543}`;
}

function createdDate(value) {
  const [date, time] = value.split(/[T ]/);
  return `${thaiDate(date)} · ${(time || "").slice(0, 5)}`;
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) node.append(child);
  return node;
}

function toast(message) {
  $("toast").textContent = message;
  $("toast").hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => ($("toast").hidden = true), 5000);
}

async function api(path, opts = {}) {
  let response;
  try {
    response = await fetch(path, {
      ...opts,
      headers: { "Content-Type": "application/json", ...opts.headers },
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    });
  } catch {
    throw new Error("เชื่อมต่อไม่ได้ ตรวจอินเทอร์เน็ตแล้วลองอีกครั้ง");
  }
  if (!response.ok) {
    if (response.status === 401) throw new Error("กรุณาโหลดหน้าใหม่เพื่อเข้าสู่ระบบ");
    if (response.status === 422) throw new Error("ค่าที่ระบุไม่ถูกต้อง กรุณาตรวจจำนวนงวดและจำนวนเลข");
    if (response.status === 404) throw new Error("ไม่พบรายการนี้ ลองโหลดข้อมูลใหม่");
    throw new Error(`ระบบยังไม่พร้อม (${response.status}) ลองอีกครั้งได้`);
  }
  return response.status === 204 ? null : response.json();
}

function selectView(view) {
  for (const name of ["pick", "history", "draws"]) $("view-" + name).hidden = name !== view;
  window.scrollTo({ top: 0, behavior: "instant" });
  document.querySelectorAll("[data-view]").forEach((button) => {
    const active = button.dataset.view === view;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
}

function normalizeField(id) {
  const input = $(id);
  const value = input.value.trim() === "" ? (id === "draws" ? 2 : 5) : Number(input.value);
  input.value = Math.max(Number(input.min), Math.min(Number(input.max), Math.trunc(Number.isFinite(value) ? value : 1)));
  updateControls();
  return Number(input.value);
}

function updateControls() {
  for (const id of ["draws", "picks", "scope", "permute"]) $(id).disabled = !savedSettings;
  document.querySelectorAll("[data-step-target]").forEach((button) => {
    const input = $(button.dataset.stepTarget);
    button.disabled = !savedSettings || (Number(button.dataset.step) < 0
      ? Number(input.value) <= Number(input.min)
      : Number(input.value) >= Number(input.max));
  });
  document.querySelectorAll("[data-preset-target]").forEach((button) => {
    button.disabled = !savedSettings;
    const active = Number($(button.dataset.presetTarget).value) === Number(button.dataset.value);
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}

function params() {
  return {
    digits: activeDigits, draws: normalizeField("draws"), picks: normalizeField("picks"),
    scope: activeDigits === 2 ? "last2" : $("scope").value, permute: $("permute").checked,
  };
}

function updateActions() {
  const busy = rolling || saving || settingsBusy;
  document.querySelectorAll(".mode-selector button").forEach((button) => { button.disabled = busy; });
  $("go").disabled = busy || !savedSettings;
  $("again").disabled = busy || !savedSettings;
  $("save").disabled = busy || resultSaved || !current?.numbers.length;
  $("copy").disabled = busy || !current?.numbers.length;
  $("go").textContent = rolling ? "กำลังสุ่ม…" : "สุ่มเลข";
  $("again").textContent = rolling ? "กำลังสุ่ม…" : "สุ่มใหม่";
  $("save").textContent = saving ? "กำลังบันทึก…" : resultSaved ? "บันทึกแล้ว ✓" : "บันทึกไว้ตรวจผล";
  $("result").setAttribute("aria-busy", String(busy));
  updateSettingsActions();
}

async function roll() {
  if (rolling || saving || settingsBusy || !savedSettings) return;
  const body = params();
  rolling = true;
  updateActions();
  try {
    const result = await api("/api/pick", { method: "POST", body });
    current = result;
    resultSaved = false;
    profiles[activeDigits].current = result;
    profiles[activeDigits].resultSaved = false;
    renderResult();
    if (result.numbers.length < result.settings.picks) toast(`เหลือเลขให้สุ่ม ${result.numbers.length} เลข ลองลดจำนวนงวดหรือปิด${activeDigits === 2 ? "ตัดเลขกลับ" : "ตัดโต๊ด"}`);
    $("result").scrollIntoView({ block: "nearest", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" });
  } catch (error) {
    toast(`สุ่มไม่สำเร็จ: ${error.message}`);
  } finally {
    rolling = false;
    updateActions();
  }
}

async function savePick() {
  if (!current?.numbers.length || rolling || saving || settingsBusy || resultSaved) return;
  saving = true;
  $("result-status").textContent = "กำลังบันทึก…";
  updateActions();
  try {
    await api("/api/picks", { method: "POST", body: { numbers: current.numbers, settings: current.settings } });
    resultSaved = true;
    profiles[activeDigits].resultSaved = true;
    $("result-status").textContent = "บันทึกแล้ว · รอตรวจผล";
    toast("บันทึกแล้ว จะตรวจให้เมื่อผลรางวัลครบ");
    await loadPicks();
  } catch (error) {
    $("result-status").textContent = "ยังไม่ได้บันทึก · ลองอีกครั้งได้";
    toast(`บันทึกไม่สำเร็จ: ${error.message}`);
  } finally {
    saving = false;
    updateActions();
  }
}

async function copyNumbers() {
  if (!current?.numbers.length) return;
  try {
    await navigator.clipboard.writeText(current.numbers.join(" "));
    toast("คัดลอกเลขแล้ว");
  } catch {
    toast("คัดลอกอัตโนมัติไม่ได้ กดค้างที่เลขเพื่อคัดลอกได้");
  }
}

function settingsText(settings) {
  const two = settings.digits === 2;
  const scope = two ? "เลขท้าย 2 ตัว" : settings.scope === "all" ? "ทุกรางวัล" : "เฉพาะหน้า/ท้าย 3 ตัว";
  return `ค่าที่บันทึก: ${settings.picks} เลข · ย้อนหลัง ${settings.draws} งวด · ${scope}${settings.permute ? two ? " · ตัดเลขกลับ" : " · ตัดโต๊ด" : ""} · ${settings.notify ? "เปิดอัตโนมัติและแจ้งเตือน" : "ปิดอัตโนมัติและแจ้งเตือน"}`;
}

function updateSettingsActions() {
  const busy = settingsBusy || rolling || saving;
  $("notify").disabled = busy || !savedSettings;
  $("saveSettings").disabled = busy || !savedSettings;
  $("saveSettings").textContent = settingsBusy ? "กำลังบันทึก…" : "ใช้ค่าชุดนี้กับเลขอัตโนมัติ";
}

async function saveSettings(notifyOnly = false) {
  if (settingsBusy || rolling || saving || !savedSettings) return;
  const requestedNotify = $("notify").checked;
  settingsBusy = true;
  updateSettingsActions();
  updateActions();
  try {
    if (notifyOnly) savedSettings = await api(modePath("/api/settings"));
    const body = { ...(notifyOnly ? savedSettings : params()), digits: activeDigits, notify: requestedNotify };
    savedSettings = await api("/api/settings", { method: "PUT", body });
    profiles[activeDigits].savedSettings = savedSettings;
    $("settingsInfo").textContent = settingsText(savedSettings);
    toast("บันทึกการตั้งค่าแล้ว");
  } catch (error) {
    $("notify").checked = savedSettings.notify;
    $("settingsInfo").textContent = settingsText(savedSettings);
    toast(`บันทึกตั้งค่าไม่สำเร็จ: ${error.message}`);
  } finally {
    settingsBusy = false;
    updateSettingsActions();
    updateActions();
  }
}

function retryMessage(message, retry, tag = "li") {
  return el(tag, { class: "section-error" }, el("span", {}, message),
    el("button", { type: "button", class: "ghost retry", onclick: retry }, "ลองโหลดอีกครั้ง"));
}

function modePath(path, digits = activeDigits) {
  return digits === 3 ? path : `${path}?digits=${digits}`;
}

function cacheProfile() {
  const profile = profiles[activeDigits];
  if (savedSettings) {
    profile.draft = { draws: $("draws").value, picks: $("picks").value, scope: $("scope").value, permute: $("permute").checked };
  }
  Object.assign(profile, { savedSettings, current, resultSaved });
}

function renderResult() {
  $("result-empty").hidden = Boolean(current);
  $("result").hidden = !current;
  $("numbers").replaceChildren();
  $("excluded").replaceChildren();
  $("poolInfo").textContent = "";
  if (!current) return;
  const result = current;
  $("result-status").textContent = resultSaved ? "บันทึกแล้ว · รอตรวจผล" : result.numbers.length ? "ยังไม่ได้บันทึก" : "ไม่มีเลขให้สุ่ม";
  $("numbers").replaceChildren(...(result.numbers.length
    ? result.numbers.map((number) => el("span", { class: "number-ticket" }, number))
    : [el("p", { class: "empty-state" }, `ไม่มีเลขเหลือในเงื่อนไขนี้ ลองลดจำนวนงวดหรือปิด${activeDigits === 2 ? "ตัดเลขกลับ" : "ตัดโต๊ด"}`)]));
  const used = result.draws_used.length
    ? `ใช้ผล ${result.draws_used.length} งวด: ${result.draws_used.map(thaiDate).join(", ")}`
    : `ยังไม่มีผลรางวัล ใช้เลขทั้งหมด ${activeDigits === 2 ? "00–99" : "000–999"}`;
  $("poolInfo").textContent = `${used} · ตัดออก ${result.excluded_count} เลข · เหลือ ${result.pool_size} เลข`;
  $("exSummary").textContent = `ดูเลขที่ตัดออก ${result.excluded.length} เลข`;
  $("excluded").replaceChildren(...result.excluded.map((number) => el("span", {}, number)));
}

function renderProfile() {
  const profile = profiles[activeDigits];
  ({ savedSettings, current, resultSaved } = profile);
  const draft = profile.draft || { draws: 2, picks: 5, scope: "all", permute: false };
  for (const id of ["draws", "picks", "scope"]) $(id).value = draft[id] === "last2" ? "all" : draft[id];
  $("permute").checked = draft.permute;
  $("notify").checked = savedSettings?.notify || false;
  $("settingsInfo").textContent = savedSettings ? settingsText(savedSettings) : "กำลังโหลดการตั้งค่า…";
  if (profile.settingsError) $("settingsInfo").replaceChildren(retryMessage(`โหลดตั้งค่าไม่ได้: ${profile.settingsError}`, () => loadSettings(), "span"));
  renderResult();
  updateControls();
  updateActions();
  updateSettingsActions();
}

function selectMode(digits) {
  if (digits === activeDigits || rolling || saving || settingsBusy) return;
  cacheProfile();
  activeDigits = digits;
  document.body.dataset.digits = digits;
  document.querySelectorAll(".mode-selector button").forEach((button) => button.setAttribute("aria-pressed", String(Number(button.dataset.digits) === digits)));
  const two = digits === 2;
  $("mode-label").textContent = `เลขท้าย ${digits} ตัว`;
  $("ticket-stamp").textContent = `PICK / 00${digits}`;
  $("scope-options").hidden = two;
  $("fixed-scope").hidden = !two;
  $("advanced-caption").textContent = two ? "เลขท้าย 2 ตัว · ตัดเลขกลับ" : "รางวัลที่ใช้ · ตัดเลขโต๊ด";
  $("permute-label").textContent = two ? "ตัดเลขกลับด้วย" : "ตัดเลขโต๊ดด้วย";
  $("permute-help").textContent = two ? "เช่น 07 ออก จะตัด 70 ด้วย · ตรวจรางวัลเฉพาะเลขตรงตัว" : "เช่น 058 ออก จะตัด 085, 508, 580, 805, 850";
  $("tod-stat").hidden = two;
  $("probability-note").textContent = `ทุกเลขมีโอกาสออก 1 ใน ${two ? "100" : "1,000"} เท่ากันทุกงวด การตัดเลขที่เคยออกไม่ได้ทำให้โอกาสถูกเพิ่มขึ้น สถิติมีไว้ติดตามผลเท่านั้น`;
  $("toast").hidden = true;
  renderProfile();
  if (!savedSettings) loadSettings();
  loadPicks();
}

async function loadSettings(digits = activeDigits) {
  const profile = profiles[digits];
  if (profile.settingsLoading) return;
  profile.settingsLoading = true;
  try {
    profile.savedSettings = await api(modePath("/api/settings", digits));
    profile.draft ||= { ...profile.savedSettings };
    profile.settingsError = null;
  } catch (error) {
    profile.settingsError = error.message;
    if (digits === activeDigits) toast("โหลดตั้งค่าไม่ได้ เปิดตัวเลือกเลขอัตโนมัติเพื่อลองโหลดอีกครั้ง");
  } finally {
    profile.settingsLoading = false;
    if (digits === activeDigits) renderProfile();
  }
}

function prize(label, value, extra = "") {
  return el("div", { class: `prize ${extra}` }, el("span", { class: "prize-label" }, label),
    el("strong", { class: "prize-number" }, value));
}

async function loadDraws() {
  try {
    const draws = await api("/api/draws");
    $("latest").textContent = draws.length ? `ผลล่าสุดที่เก็บไว้ · ${thaiDate(draws[0].date)} · ${draws.length} งวด` : "ยังไม่มีผลรางวัลที่เก็บไว้";
    $("draws-list").replaceChildren(...(draws.length ? draws.slice(0, 12).map((draw, index) =>
      el("li", { class: "draw-card" },
        el("div", { class: "draw-header" }, el("h3", {}, `งวด ${thaiDate(draw.date)}`),
          index === 0 ? el("span", { class: "latest-badge" }, "ล่าสุดที่เก็บไว้") : el("span", { class: "when" }, `${draw.count} เลข 3 ตัว`)),
        el("div", { class: "prize-grid" }, prize("รางวัลที่ 1", draw.first, "first-prize"),
          prize("เลขท้าย 2 ตัว", draw.last2.join(" · ")), prize("เลขหน้า 3 ตัว", draw.last3f.join(" · ")),
          prize("เลขท้าย 3 ตัว", draw.last3b.join(" · ")))))
      : [el("li", { class: "empty-state" }, "ยังไม่มีผลรางวัล กดดึงผลล่าสุดเพื่อเริ่มเก็บข้อมูล")]));
  } catch (error) {
    $("latest").textContent = "โหลดผลรางวัลไม่ได้ · ลองใหม่ในหน้าผลรางวัล";
    $("draws-list").replaceChildren(retryMessage(error.message, loadDraws));
  }
}

function pickLine(pick) {
  const checked = pick.result !== null && Boolean(pick.result_draw);
  const hits = pick.result?.hits || [];
  const kinds = new Map(hits.map((hit) => [hit.number, hit.kinds]));
  const status = !checked ? "รอผล" : hits.length ? "มีเลขถูกรางวัล" : "ตรวจแล้ว · ไม่ถูก";
  const item = el("li", { class: "pick-card" });
  const remove = el("button", { type: "button", class: "ghost del", "aria-label": `ลบเลขชุด ${pick.numbers.join(" ")}`,
    onclick: () => removePick(pick.id, remove) }, "ลบชุดนี้");
  item.append(el("div", { class: "pick-header" },
    el("span", { class: `pick-status ${!checked ? "pending" : hits.length ? "hit" : "checked"}` }, status), remove),
  el("div", { class: "pick-meta" }, el("span", { class: "mode-badge" }, `${pick.settings.digits || 3} ตัว`), `${pick.source === "auto" ? "อัตโนมัติ" : "บันทึกเอง"} · ${createdDate(pick.created_at)}`),
  el("div", { class: "number-chips" }, pick.numbers.map((number) => {
    const awards = kinds.get(number);
    const hitClass = !awards ? "" : awards.every((kind) => kind === "first3_tod") ? "tod" : "hit";
    return el("span", { class: `number-chip ${hitClass}` }, number);
  })));
  if (checked) item.append(el("p", { class: "pick-meta" }, `ตรวจงวด ${thaiDate(pick.result_draw)}`));
  for (const hit of hits) item.append(el("p", { class: "pick-detail" }, `${hit.number} · ${hit.kinds.map((kind) => KIND[kind] || kind).join(" / ")}`));
  return item;
}

async function removePick(id, button) {
  if (!window.confirm("ลบเลขชุดนี้และผลตรวจออกจากประวัติ? ย้อนกลับไม่ได้")) return;
  button.disabled = true;
  try {
    await api(`/api/picks/${id}`, { method: "DELETE" });
    await loadPicks();
    toast("ลบเลขชุดนี้แล้ว");
  } catch (error) {
    button.disabled = false;
    toast(`ลบไม่สำเร็จ: ${error.message}`);
  }
}

async function loadPicks(digits = activeDigits) {
  const request = profiles[digits].historyRequest = (profiles[digits].historyRequest || 0) + 1;
  $("history-count").textContent = "กำลังโหลด…";
  $("picks-list").replaceChildren(el("li", { class: "empty-state" }, "กำลังโหลดเลขที่บันทึก…"));
  for (const id of ["stat-picks", "stat-exact", "stat-tod", "stat-expected"]) $(id).textContent = "—";
  $("stats").textContent = "กำลังโหลดสถิติ…";
  const [picksResult, statsResult] = await Promise.allSettled([api(modePath("/api/picks", digits)), api(modePath("/api/stats", digits))]);
  if (digits !== activeDigits || request !== profiles[digits].historyRequest) return;
  if (picksResult.status === "fulfilled") {
    const picks = picksResult.value;
    $("history-count").textContent = `${picks.length} ชุดล่าสุด`;
    $("picks-list").replaceChildren(...(picks.length ? picks.map(pickLine) :
      [el("li", { class: "empty-state" }, "ยังไม่มีเลขที่บันทึก สุ่มเลขแล้วกด ‘บันทึกไว้ตรวจผล’ เพื่อเริ่มเก็บชุดแรก")]));
  } else {
    $("history-count").textContent = "โหลดไม่สำเร็จ";
    $("picks-list").replaceChildren(retryMessage(picksResult.reason.message, () => loadPicks()));
  }
  if (statsResult.status === "fulfilled") {
    const stats = statsResult.value;
    for (const [id, value] of Object.entries({ "stat-picks": stats.picks, "stat-exact": stats.exact_hits, "stat-tod": stats.tod_hits, "stat-expected": stats.expected.toFixed(2) })) $(id).textContent = value;
    $("stats").textContent = stats.picks ? `จาก ${stats.numbers} เลขที่ตรวจแล้วทั้งหมด · “คาดว่าถูก” ใช้เทียบกับการสุ่มธรรมดา` : "สถิติจะเริ่มนับเมื่อเลขที่บันทึกได้รับการตรวจผล";
  } else {
    for (const id of ["stat-picks", "stat-exact", "stat-tod", "stat-expected"]) $(id).textContent = "—";
    $("stats").replaceChildren(retryMessage(`โหลดสถิติไม่ได้: ${statsResult.reason.message}`, () => loadPicks(), "span"));
  }
}

async function syncNow() {
  const button = $("sync");
  if (button.disabled) return;
  button.disabled = true;
  button.textContent = "กำลังดึงผล…";
  try {
    await api("/api/sync", { method: "POST" });
    await Promise.all([loadDraws(), loadPicks()]);
    toast("ดึงข้อมูลแล้ว แสดงผลล่าสุดที่ระบบเก็บไว้");
  } catch (error) {
    toast(`ดึงผลไม่สำเร็จ: ${error.message}`);
  } finally {
    button.disabled = false;
    button.textContent = "ดึงผลล่าสุด";
  }
}

document.querySelectorAll(".mode-selector button").forEach((button) => button.addEventListener("click", () => selectMode(Number(button.dataset.digits))));
document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => selectView(button.dataset.view)));
document.querySelectorAll("[data-step-target]").forEach((button) => button.addEventListener("click", () => {
  const id = button.dataset.stepTarget;
  $(id).value = normalizeField(id) + Number(button.dataset.step);
  normalizeField(id);
}));
document.querySelectorAll("[data-preset-target]").forEach((button) => button.addEventListener("click", () => {
  $(button.dataset.presetTarget).value = button.dataset.value;
  normalizeField(button.dataset.presetTarget);
}));
for (const id of ["draws", "picks"]) {
  $(id).addEventListener("blur", () => normalizeField(id));
  $(id).addEventListener("input", updateControls);
}
$("pick-form").addEventListener("submit", (event) => { event.preventDefault(); roll(); });
$("again").addEventListener("click", roll);
$("save").addEventListener("click", savePick);
$("copy").addEventListener("click", copyNumbers);
$("saveSettings").addEventListener("click", () => saveSettings(false));
$("notify").addEventListener("change", () => saveSettings(true));
$("sync").addEventListener("click", syncNow);
updateActions();
updateSettingsActions();
loadSettings();
loadDraws();
loadPicks();
