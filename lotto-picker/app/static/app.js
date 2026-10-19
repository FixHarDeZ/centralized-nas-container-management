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
let activeView = "pick";
let latestDraws = [];
const STYLE = { random: "สุ่มล้วน", hot: "ตามกระแส", cold: "สวนกระแส", overdue: "เลขค้างนาน" };
const fmt = (n) => Number(n).toLocaleString("th-TH", { maximumFractionDigits: 2 });

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
  activeView = view;
  for (const name of ["pick", "history", "stats", "draws", "ledger"]) $("view-" + name).hidden = name !== view;
  document.querySelector(".mode-selector").hidden = view === "ledger";
  if (view === "stats") loadStats();
  if (view === "ledger") loadLedger();
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
  for (const id of ["draws", "picks", "scope", "permute", "style", "stat-window"]) $(id).disabled = !savedSettings;
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
    style: $("style").value, stat_window: Number($("stat-window").value),
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
  return `ค่าที่บันทึก: ${settings.picks} เลข · ย้อนหลัง ${settings.draws} งวด · ${scope}${settings.permute ? two ? " · ตัดเลขกลับ" : " · ตัดโต๊ด" : ""} · สไตล์${STYLE[settings.style || "random"]} · ${settings.notify ? "เปิดอัตโนมัติและแจ้งเตือน" : "ปิดอัตโนมัติและแจ้งเตือน"}`;
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
    profile.draft = { draws: $("draws").value, picks: $("picks").value, scope: $("scope").value, permute: $("permute").checked, style: $("style").value, stat_window: $("stat-window").value };
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
  const style = result.settings.style || "random";
  if (style !== "random" && result.candidates !== undefined) $("poolInfo").textContent += ` · สไตล์${STYLE[style]} สุ่มจาก ${result.candidates} เลข`;
  const reasons = result.reasons || {};
  const span = result.history_draws;
  $("reasons").replaceChildren(...(span ? result.numbers.map((number) => {
    const r = reasons[number] || { count: 0, gap: span };
    const gap = r.gap >= span ? `ไม่ออกเลยใน ${span} งวด` : r.gap === 0 ? "ออกงวดล่าสุด" : `ค้าง ${r.gap} งวด`;
    return el("li", {}, el("b", {}, number), el("span", {}, `ออก ${r.count} ครั้งใน ${span} งวด · ${gap}`));
  }) : []));
  renderSix(result.numbers);
}

function sixPatterns(numbers) {
  if (activeDigits === 2) return numbers.map((n) => ({ pattern: `xxxx${n}`, label: "เลขท้าย 2 ตัว · 2,000 บาท" }));
  return numbers.flatMap((n) => [
    { pattern: `xxx${n}`, label: "เลขท้าย 3 ตัว · 4,000 บาท" },
    { pattern: `${n}xxx`, label: "เลขหน้า 3 ตัว · 4,000 บาท" },
  ]);
}

function renderSix(numbers) {
  const patterns = sixPatterns(numbers);
  $("six-intro").textContent = `x = เลขอะไรก็ได้ ใช้มองหาสลากที่ขึ้นต้น/ลงท้ายตามเลขที่สุ่มได้ · สลากใบหนึ่งได้รางวัลที่ 1 โอกาส 1 ใน 1,000,000 เท่ากันทุกใบ`;
  $("six-list").replaceChildren(...patterns.map((p) => el("li", {}, el("b", {}, p.pattern), el("span", {}, p.label))));
  $("six-copy").disabled = !patterns.length;
}

async function copySix() {
  if (!current?.numbers.length) return;
  try {
    await navigator.clipboard.writeText(sixPatterns(current.numbers).map((p) => p.pattern).join("\n"));
    toast("คัดลอกรูปแบบเลข 6 หลักแล้ว");
  } catch {
    toast("คัดลอกอัตโนมัติไม่ได้ กดค้างที่เลขเพื่อคัดลอกได้");
  }
}

function renderProfile() {
  const profile = profiles[activeDigits];
  ({ savedSettings, current, resultSaved } = profile);
  const draft = profile.draft || { draws: 2, picks: 5, scope: "all", permute: false };
  for (const id of ["draws", "picks", "scope"]) $(id).value = draft[id] === "last2" ? "all" : draft[id];
  $("style").value = draft.style || "random";
  $("stat-window").value = String(draft.stat_window || 0);
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
  $("category-field").hidden = two;
  renderProfile();
  if (!savedSettings) loadSettings();
  loadPicks();
  if (activeView === "stats") loadStats();
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
    latestDraws = draws;
    $("latest").textContent = draws.length ? `ผลล่าสุดที่เก็บไว้ · ${thaiDate(draws[0].date)}` : "ยังไม่มีผลรางวัลที่เก็บไว้";
    $("check-date").replaceChildren(...draws.map((draw, index) => el("option", { value: draw.date }, index === 0 ? `ล่าสุด ${thaiDate(draw.date)}` : thaiDate(draw.date))));
    fillLedgerDates();
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
$("six-copy").addEventListener("click", copySix);
$("category").addEventListener("change", loadFrequency);
$("freq-window").addEventListener("change", loadFrequency);
$("lookup-form").addEventListener("submit", (event) => { event.preventDefault(); lookupNumber(); });
$("run-backtest").addEventListener("click", runBacktest);
$("run-insight").addEventListener("click", runInsight);
$("check-form").addEventListener("submit", (event) => { event.preventDefault(); checkTicket(); });
$("ledger-form").addEventListener("submit", (event) => { event.preventDefault(); saveLedger(); });
$("ledger-tickets").addEventListener("input", autoCost);
$("ledger-cost").addEventListener("input", () => { $("ledger-cost").dataset.touched = $("ledger-cost").value ? "1" : ""; });
updateActions();
updateSettingsActions();
loadMe();
loadSettings();
loadDraws();
loadPicks();

// --- statistics ------------------------------------------------------------------

let frequencyData = null;
let insightTimer = null;

function fact(label, value, note = "", tone = "") {
  return el("div", { class: `fact ${tone}` }, el("span", {}, label), el("strong", {}, String(value)), note ? el("small", {}, note) : "");
}

async function loadStats() {
  $("stats-tag").textContent = `เลข ${activeDigits} ตัว`;
  $("category-field").hidden = activeDigits === 2;
  loadHistoryInfo();
  loadFrequency();
  loadInsight();
  $("backtest-result").replaceChildren();
}

async function loadHistoryInfo() {
  try {
    const h = await api("/api/history");
    const range = h.count ? `${h.count} งวด · ${thaiDate(h.from)} – ${thaiDate(h.to)}` : "ยังไม่มีประวัติ";
    const progress = h.state === "running" ? ` · กำลังโหลดประวัติย้อนหลัง (${h.probed || 0}/${h.todo || "?"} วันที่ตรวจ)`
      : h.state === "error" ? " · โหลดประวัติสะดุด จะลองใหม่ตี 4:30" : "";
    $("history-info").textContent = `ประวัติตั้งแต่ ${thaiDate(h.start)} (เริ่มกติกาเลขหน้า 3 ตัว) · ${range}${progress}`;
  } catch (error) {
    $("history-info").textContent = `โหลดสถานะประวัติไม่ได้: ${error.message}`;
  }
}

async function loadFrequency() {
  const digits = activeDigits;
  const category = digits === 2 ? "last2" : $("category").value;
  const query = `/api/frequency?digits=${digits}&category=${category}&window=${$("freq-window").value}`;
  $("freq-verdict").textContent = "";
  $("freq-facts").replaceChildren(el("p", { class: "muted" }, "กำลังคำนวณ…"));
  try {
    const f = await api(query);
    if (digits !== activeDigits) return;
    frequencyData = f;
    renderFrequency(f);
  } catch (error) {
    $("freq-facts").replaceChildren(retryMessage(error.message, loadFrequency, "div"));
  }
}

function renderFrequency(f) {
  const [lo, hi] = f.band;
  $("freq-range").textContent = f.draws ? `${f.draws} งวด` : "";
  if (!f.draws) {
    $("freq-facts").replaceChildren(el("p", { class: "muted" }, "ยังไม่มีประวัติพอให้นับ รอระบบโหลดผลย้อนหลังก่อน"));
    for (const id of ["rank-hot", "rank-cold", "rank-overdue"]) $(id).replaceChildren();
    $("heatmap").hidden = $("heat-legend").hidden = true;
    return;
  }
  const maxOk = f.max_seen <= f.max_typical[1];
  $("freq-facts").replaceChildren(
    fact("ค่าเฉลี่ยต่อเลข", fmt(f.expected), "ครั้ง ถ้าทุกเลขออกเท่ากันพอดี"),
    fact("ช่วงปกติของการสุ่ม", `${lo}–${hi}`, "ครั้ง · 95% ของเลขควรอยู่ในช่วงนี้"),
    fact("ออกบ่อยสุดที่เห็น", f.max_seen, `ครั้ง · สุ่มล้วนมักได้ ${f.max_typical[0]} (ไม่เกิน ${f.max_typical[1]})`, maxOk ? "good" : "bad"),
    fact("เลขนอกช่วงปกติ", f.outside, `เลข · สุ่มล้วนคาดว่า ~${fmt(f.outside_expected)}`, f.outside <= f.outside_expected * 2 + 3 ? "good" : "bad"),
  );
  $("freq-verdict").textContent = maxOk && f.outside <= f.outside_expected * 2 + 3
    ? `เลขที่ "ออกบ่อย" ยังอยู่ในระดับที่การสุ่มล้วนให้ได้ตามปกติ ไม่มีสัญญาณว่าเลขไหนถูกจับบ่อยกว่าเลขอื่นจริง`
    : `บางเลขออกบ่อย/น้อยเกินช่วงที่คาด ซึ่งเกิดได้จากความบังเอิญเมื่อดูหลายเลขพร้อมกัน ไม่ได้แปลว่างวดหน้าจะออกอีก`;
  const rows = f.numbers;
  const rank = (list, text) => list.slice(0, 10).map((r) => el("li", {}, el("b", {}, r.number), el("span", {}, text(r))));
  $("rank-hot").replaceChildren(...rank([...rows].sort((a, b) => b.count - a.count || a.number.localeCompare(b.number)), (r) => `${r.count} ครั้ง`));
  $("rank-cold").replaceChildren(...rank([...rows].sort((a, b) => a.count - b.count || a.number.localeCompare(b.number)), (r) => `${r.count} ครั้ง`));
  // Never-drawn numbers already head the cold list; overdue ranks the ones that did appear.
  $("rank-overdue").replaceChildren(...rank(rows.filter((r) => r.count).sort((a, b) => b.gap - a.gap || a.number.localeCompare(b.number)), (r) => `${r.gap} งวด`));
  renderHeatmap(f);
}

function renderHeatmap(f) {
  const show = f.digits === 2;
  $("heatmap").hidden = $("heat-legend").hidden = !show;
  if (!show) return $("heatmap").replaceChildren();
  const max = Math.max(1, f.max_seen);
  $("heatmap").replaceChildren(...f.numbers.map((r) => {
    const heat = r.count / max;
    const cell = el("button", { type: "button", class: `heat-cell ${r.band}${heat > 0.55 ? " hot-text" : ""}`,
      style: `--heat:${heat.toFixed(3)}`, "aria-label": `${r.number} ออก ${r.count} ครั้ง`,
      onclick: () => { $("lookup").value = r.number; lookupNumber(); } },
    r.number, el("small", {}, String(r.count)));
    return cell;
  }));
}

function lookupNumber() {
  const value = $("lookup").value.trim();
  if (!frequencyData) return;
  const row = frequencyData.numbers.find((r) => r.number === value);
  if (!row) {
    $("lookup-result").textContent = `ใส่เลข ${activeDigits} หลัก เช่น ${activeDigits === 2 ? "07" : "123"}`;
    return;
  }
  const [lo, hi] = frequencyData.band;
  const band = row.band === "normal" ? "อยู่ในช่วงปกติ" : row.band === "high" ? "มากกว่าช่วงปกติ" : "น้อยกว่าช่วงปกติ";
  const last = row.last ? `ออกล่าสุด ${thaiDate(row.last)} (${row.gap === 0 ? "งวดล่าสุด" : `ค้าง ${row.gap} งวด`})` : `ไม่ออกเลยใน ${frequencyData.draws} งวด`;
  $("lookup-result").textContent = `${row.number}: ออก ${row.count} ครั้งใน ${frequencyData.draws} งวด · ${band} (${lo}–${hi}) · ${last} · โอกาสงวดหน้ายังเท่ากับเลขอื่น`;
}

// --- backtest ----------------------------------------------------------------------

const BT_LABEL = { baseline: "สุ่มทั้งหมด", random: "สุ่มหลังตัดเลข", hot: "🔥 ตามกระแส", cold: "❄️ สวนกระแส", overdue: "⏳ ค้างนาน" };
const BT_COLOR = { random: "var(--muted)", hot: "var(--accent)", cold: "#4f8fc0", overdue: "#9a6fc8" };

async function runBacktest() {
  const button = $("run-backtest");
  const p = params();
  const query = `/api/backtest?digits=${p.digits}&picks=${p.picks}&draws=${p.draws}&scope=${p.scope}&permute=${p.permute}&window=${p.stat_window}`;
  button.disabled = true;
  button.textContent = "กำลังทดสอบ…";
  try {
    renderBacktest(await api(query));
  } catch (error) {
    $("backtest-result").replaceChildren(retryMessage(error.message, runBacktest, "div"));
  } finally {
    button.disabled = false;
    button.textContent = "ทดสอบด้วยค่าปัจจุบัน";
  }
}

function renderBacktest(bt) {
  if (!bt.plays) {
    $("backtest-result").replaceChildren(el("p", { class: "muted" }, "ประวัติยังไม่พอ ต้องมีอย่างน้อย 24 งวดก่อนเริ่มทดสอบ"));
    return;
  }
  const head = el("tr", {}, ["กลยุทธ์", "ถูก", "สุ่มคาดว่า", "เทียบ"].map((t) => el("th", {}, t)));
  const body = bt.strategies.map((r) => el("tr", {},
    el("td", {}, BT_LABEL[r.strategy]),
    el("td", { class: "num" }, fmt(r.hits)),
    el("td", { class: "num" }, fmt(r.expected)),
    el("td", { class: "num" }, r.ratio === null ? "—" : `${r.ratio >= 1 ? "+" : ""}${fmt((r.ratio - 1) * 100)}%${r.significant ? " *" : ""}`)));
  const sig = bt.strategies.filter((r) => r.significant && r.strategy !== "baseline");
  const verdict = sig.length
    ? `${sig.map((r) => BT_LABEL[r.strategy]).join(", ")} ต่างจากสุ่มเกินเกณฑ์ (z ≥ ${bt.z_threshold}) ในช่วงนี้ — เมื่อทดสอบหลายแบบพร้อมกันมีโอกาสเจอแบบนี้ได้โดยบังเอิญ ลองเปลี่ยนช่วงหรือจำนวนเลขดูว่ายังอยู่ไหม`
    : `ไม่มีสไตล์ไหนต่างจากสุ่มอย่างมีนัยสำคัญ ทดสอบ ${bt.plays} งวด (${thaiDate(bt.from)} – ${thaiDate(bt.to)}) — ทุกแบบให้ผลใกล้กับสุ่มล้วน`;
  $("backtest-result").replaceChildren(
    el("table", { class: "bt-table" }, el("thead", {}, head), el("tbody", {}, body)),
    btChart(bt.series),
    el("div", { class: "bt-legend" }, Object.entries(BT_COLOR).map(([s, c]) => el("span", { style: `--c:${c}` }, BT_LABEL[s]))),
    el("p", { class: "verdict" }, verdict),
    el("p", { class: "field-help" }, "“ถูก” คือจำนวนครั้งเฉลี่ยที่คาดว่าจะถูก เมื่อสุ่มในกลุ่มของสไตล์นั้น · กราฟคือส่วนต่างสะสมจากสุ่มล้วน เส้นที่วนรอบศูนย์ = ไม่ต่างจากสุ่ม"),
  );
}

function btChart(series) {
  const ns = "http://www.w3.org/2000/svg";
  const W = 360, H = 200, P = 30;
  const keys = Object.keys(BT_COLOR);
  const values = keys.flatMap((k) => series[k]);
  const lim = Math.max(1, ...values.map(Math.abs));
  const n = series.dates.length;
  const x = (i) => P + (i / Math.max(1, n - 1)) * (W - P * 2);
  const y = (v) => H / 2 - (v / lim) * (H / 2 - P);
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("class", "bt-chart");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "ส่วนต่างสะสมของแต่ละสไตล์เทียบกับสุ่มล้วน");
  const add = (tag, attrs, text) => {
    const node = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    if (text) node.textContent = text;
    svg.append(node);
  };
  add("line", { x1: P, x2: W - P, y1: H / 2, y2: H / 2, stroke: "var(--line)", "stroke-width": 1.5 });
  add("text", { x: 2, y: y(lim) - 6 }, `ถูกมากกว่าสุ่ม +${fmt(lim)} ครั้ง`);
  add("text", { x: 2, y: y(-lim) + 14 }, `น้อยกว่าสุ่ม −${fmt(lim)} ครั้ง`);
  add("text", { x: P, y: H - 4 }, thaiDate(series.dates[0]));
  add("text", { x: W - P, y: H - 4, "text-anchor": "end" }, thaiDate(series.dates[n - 1]));
  for (const k of keys) {
    const points = series[k].map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
    add("polyline", { points, fill: "none", stroke: BT_COLOR[k], "stroke-width": 2, "stroke-linejoin": "round" });
  }
  return svg;
}

// --- summary -------------------------------------------------------------------------

async function loadInsight() {
  clearTimeout(insightTimer);
  const digits = activeDigits;
  try {
    const r = await api(modePath("/api/insight", digits));
    if (digits !== activeDigits) return;
    $("insight-text").textContent = r.text || "ยังไม่มีสรุป กด “สรุปใหม่” เพื่อเริ่ม";
    $("insight-source").textContent = r.running ? "กำลังสรุป…" : r.source === "ai" ? `AI · ${thaiDate(r.draw)}` : r.source ? `อัตโนมัติ · ${thaiDate(r.draw)}` : "";
    $("run-insight").disabled = r.running;
    $("run-insight").textContent = r.running ? "กำลังสรุป อาจใช้เวลาไม่กี่นาที…" : r.stale ? "สรุปงวดล่าสุด" : "สรุปใหม่";
    if (r.running && activeView === "stats") insightTimer = setTimeout(loadInsight, 5000);
  } catch (error) {
    $("insight-text").textContent = `โหลดสรุปไม่ได้: ${error.message}`;
  }
}

async function runInsight() {
  $("run-insight").disabled = true;
  try {
    await api(modePath("/api/insight"), { method: "POST" });
  } catch (error) {
    toast(`สรุปไม่ได้: ${error.message}`);
  }
  loadInsight();
}

// --- ticket check ----------------------------------------------------------------------

const PRIZE = { first: "รางวัลที่ 1", second: "รางวัลที่ 2", third: "รางวัลที่ 3", fourth: "รางวัลที่ 4", fifth: "รางวัลที่ 5", near1: "ข้างเคียงรางวัลที่ 1", last3f: "เลขหน้า 3 ตัว", last3b: "เลขท้าย 3 ตัว", last2: "เลขท้าย 2 ตัว" };

async function checkTicket() {
  const number = $("check-number").value.trim();
  if (!/^[0-9]{6}$/.test(number)) {
    $("check-result").textContent = "ใส่เลขสลาก 6 หลัก";
    return;
  }
  try {
    const date = $("check-date").value;
    const r = await api(`/api/check?number=${number}${date ? `&date=${date}` : ""}`);
    $("check-result").textContent = r.kinds.length
      ? `🎉 ${number} งวด ${thaiDate(r.date)}: ${r.kinds.map((k) => `${PRIZE[k]} ${fmt(r.amounts[k])} บาท`).join(" + ")} · รวม ${fmt(r.total)} บาท`
      : `${number} งวด ${thaiDate(r.date)}: ไม่ถูกรางวัล`;
  } catch (error) {
    $("check-result").textContent = `ตรวจไม่ได้: ${error.message}`;
  }
}

// --- ledger -----------------------------------------------------------------------------

let ticketPrice = 80;

function nextDrawAfter(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  if (d < 16) return `${y}-${String(m).padStart(2, "0")}-16`;
  return m === 12 ? `${y + 1}-01-01` : `${y}-${String(m + 1).padStart(2, "0")}-01`;
}

function fillLedgerDates() {
  const keep = $("ledger-date").value;
  const options = latestDraws.length ? [nextDrawAfter(latestDraws[0].date), ...latestDraws.map((d) => d.date)] : [];
  $("ledger-date").replaceChildren(...options.map((date, i) => el("option", { value: date }, i === 0 ? `งวดถัดไป ${thaiDate(date)} (ตามปฏิทิน)` : thaiDate(date))));
  if (keep && options.includes(keep)) $("ledger-date").value = keep;
}

function parseTickets(text) {
  const tickets = [];
  for (const raw of text.split(/[\n,]+/)) {
    const line = raw.trim();
    if (!line) continue;
    const m = line.match(/^([0-9]{6})(?:\s*[x×*]\s*([0-9]{1,3}))?$/i);
    if (!m) throw new Error(`อ่านบรรทัด “${line}” ไม่ได้ ใช้รูปแบบ 123456 หรือ 123456 x2`);
    tickets.push({ number: m[1], qty: Number(m[2] || 1) });
  }
  return tickets;
}

function autoCost() {
  if ($("ledger-cost").dataset.touched) return;
  try {
    const qty = parseTickets($("ledger-tickets").value).reduce((sum, t) => sum + t.qty, 0);
    $("ledger-cost").value = qty ? String(qty * ticketPrice) : "";
  } catch { /* finish typing first */ }
}

async function loadLedger() {
  try {
    const { entries, summary } = await api("/api/ledger");
    ticketPrice = summary.ticket_price;
    $("ticket-price").textContent = ticketPrice;
    $("ledger-count").textContent = `${entries.length} รายการ`;
    const ret = summary.return === null ? "—" : `${fmt(summary.return * 100)}%`;
    $("ledger-summary").replaceChildren(
      fact("จ่ายไป", `${fmt(summary.cost)}`, `บาท · งวดที่ผลออกแล้ว${summary.pending ? ` (รอผลอีก ${fmt(summary.pending_cost)})` : ""}`),
      fact("ได้รางวัล", `${fmt(summary.won)}`, "บาท"),
      fact("สุทธิ", `${summary.net >= 0 ? "+" : ""}${fmt(summary.net)}`, "บาท", summary.net >= 0 ? "good" : "bad"),
      fact("ได้คืน", ret, `ค่าเฉลี่ยระยะยาวของสลาก ${fmt(summary.expected_return * 100)}%`),
    );
    $("ledger-note").textContent = `ตามตารางรางวัล ซื้อสลาก ${ticketPrice} บาท ได้คืนเฉลี่ย ${fmt(summary.expected_return * ticketPrice)} บาท ยิ่งซื้อนานผลจะเข้าใกล้ ${fmt(summary.expected_return * 100)}% · ตั้งงบที่เสียได้`;
    $("ledger-list").replaceChildren(...(entries.length ? entries.map(ledgerLine)
      : [el("li", { class: "empty-state" }, "ยังไม่มีรายการ บันทึกการซื้อครั้งแรกด้านบน")]));
  } catch (error) {
    $("ledger-list").replaceChildren(retryMessage(error.message, loadLedger));
  }
}

function ledgerLine(e) {
  const status = { pending: ["รอผล", "pending"], won: ["ถูกรางวัล", "won"], lost: ["ไม่ถูก", "checked"], manual: ["กรอกเอง", e.won > 0 ? "won" : "checked"] }[e.status];
  const remove = el("button", { type: "button", class: "ghost del", "aria-label": `ลบรายการงวด ${thaiDate(e.draw_date)}`, onclick: () => removeLedger(e.id, remove) }, "ลบ");
  const item = el("li", { class: "ledger-card" },
    el("div", { class: "pick-header" }, el("div", {}, el("strong", {}, `งวด ${thaiDate(e.draw_date)}`), el("span", { class: `pick-status ${status[1]}` }, status[0])), remove),
    e.label ? el("p", { class: "pick-meta" }, e.label) : "",
    e.result_draw && e.result_draw !== e.draw_date ? el("p", { class: "pick-meta" }, `ออกรางวัลจริง ${thaiDate(e.result_draw)}`) : "",
    el("div", { class: "ledger-money" }, el("span", {}, "จ่าย ", el("b", {}, fmt(e.cost))), el("span", {}, "ได้ ", el("b", { class: e.won > 0 ? "hit" : "" }, e.won === null ? "—" : fmt(e.won)))));
  if (e.tickets.length) item.append(el("div", { class: "number-chips" }, e.tickets.map((t) => {
    const win = e.wins.find((w) => w.number === t.number);
    return el("span", { class: `number-chip ${win ? "hit" : ""}` }, t.qty > 1 ? `${t.number}×${t.qty}` : t.number);
  })));
  for (const w of e.wins) item.append(el("p", { class: "pick-detail" }, `${w.number} · ${w.kinds.map((k) => PRIZE[k]).join(" + ")} · ${fmt(w.amount)} บาท`));
  return item;
}

async function saveLedger() {
  let tickets;
  try {
    tickets = parseTickets($("ledger-tickets").value);
  } catch (error) {
    toast(error.message);
    return;
  }
  const cost = Number($("ledger-cost").value);
  const prizeText = $("ledger-prize").value.trim();
  if (!$("ledger-date").value || !Number.isFinite(cost) || $("ledger-cost").value.trim() === "" || cost < 0) {
    toast("เลือกงวดและใส่จำนวนเงินที่จ่าย");
    return;
  }
  const body = { draw_date: $("ledger-date").value, label: $("ledger-label").value.trim(), tickets, cost,
    prize: prizeText === "" ? null : Number(prizeText) };
  $("ledger-save").disabled = true;
  try {
    await api("/api/ledger", { method: "POST", body });
    for (const id of ["ledger-tickets", "ledger-cost", "ledger-prize", "ledger-label"]) $(id).value = "";
    $("ledger-cost").dataset.touched = "";
    toast("บันทึกรายการแล้ว");
    await loadLedger();
  } catch (error) {
    toast(`บันทึกไม่สำเร็จ: ${error.message}`);
  } finally {
    $("ledger-save").disabled = false;
  }
}

async function removeLedger(id, button) {
  if (!window.confirm("ลบรายการนี้? ย้อนกลับไม่ได้")) return;
  button.disabled = true;
  try {
    await api(`/api/ledger/${id}`, { method: "DELETE" });
    await loadLedger();
  } catch (error) {
    button.disabled = false;
    toast(`ลบไม่สำเร็จ: ${error.message}`);
  }
}

// --- who is logged in ------------------------------------------------------------

async function loadMe() {
  try {
    const me = await api("/api/me");
    $("user-chip").textContent = me.user;
    $("user-chip").hidden = false;
    // Auto picks and Telegram belong to the owner's chat; others save and check in the page only.
    $("automation").hidden = !me.owner;
    $("automation-owner-only").hidden = me.owner;
  } catch { /* chip stays hidden; the server still scopes data by login */ }
}
