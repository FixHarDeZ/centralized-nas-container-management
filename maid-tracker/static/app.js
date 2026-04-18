/* ============================================================
   Maid Tracker — Single-Page Application
   Routes (hash-based):
     #/                    → employee list
     #/employee/new        → new employee form
     #/employee/:id        → profile + tabs
     #/employee/:id/edit   → edit employee form
   ============================================================ */

// ─── i18n ────────────────────────────────────────────────────

const TRANSLATIONS = {
  th: {
    appTitle: "ระบบบันทึกการทำงานแม่บ้าน",
    langBtn: "EN",
    months: ["","มกราคม","กุมภาพันธ์","มีนาคม","เมษายน","พฤษภาคม","มิถุนายน",
             "กรกฎาคม","สิงหาคม","กันยายน","ตุลาคม","พฤศจิกายน","ธันวาคม"],
    daysShort: ["อา","จ","อ","พ","พฤ","ศ","ส"],
    yearOffset: 543,
    // Status
    statusWork: "ทำงาน", statusLeave: "ลา", statusHoliday: "หยุด",
    statusCompensatory: "ชดเชย", statusBeforeStart: "—",
    // Common
    home: "หน้าหลัก", save: "บันทึก", cancel: "ยกเลิก", edit: "แก้ไข",
    baht: "บาท", perDay: "บาท/วัน", errGeneral: "เกิดข้อผิดพลาด: ",
    errSave: "บันทึกไม่สำเร็จ: ", errDelete: "ลบไม่สำเร็จ: ",
    errCancelResign: "ยกเลิกไม่สำเร็จ: ", errEditNote: "แก้ไขไม่สำเร็จ: ",
    // Employee list
    listTitle: "รายชื่อแม่บ้าน", addBtn: "เพิ่มแม่บ้าน",
    emptyList: "ยังไม่มีแม่บ้านในระบบ กดปุ่มด้านบนเพื่อเพิ่ม",
    resignedBadge: "ลาออกแล้ว", labelStarted: "เริ่มงาน:", labelResigned: "ลาออก:",
    labelSalary: "เงินเดือน",
    // Employee form
    formTitleNew: "เพิ่มแม่บ้านใหม่", formTitleEdit: "แก้ไขข้อมูลแม่บ้าน",
    fieldName: "ชื่อ", fieldAge: "อายุ", fieldNationality: "สัญชาติ",
    fieldPhone: "เบอร์โทร", fieldLineId: "LINE ID", fieldFacebook: "Facebook (ไม่บังคับ)",
    fieldStartDate: "วันเริ่มงาน", fieldSalary: "เงินเดือน (บาท)",
    fieldMaxLeaveCarry: "วันลาค้างสูงสุด (ไม่บังคับ)",
    fieldMaxLeaveCarryHint: "จำนวนวันลาที่ค้างสะสมได้โดยไม่ถูกหักเงิน เช่น ใส่ 3 = ค้างได้ไม่เกิน 3 วัน ถ้าเกินจะหักจากรอบ 2 ของเดือนนั้น",
    nationalityOptions: ["ไทย","เมียนมา","กัมพูชา","ลาว","เวียดนาม","อื่นๆ"],
    salaryPreview: (dr) => `อัตราค่าจ้างรายวัน ≈ <strong>${dr} บาท/วัน</strong> (คิดจาก 26 วันทำงาน/เดือน)`,
    btnSaveEdit: "บันทึกการแก้ไข", btnAddNew: "เพิ่มแม่บ้าน",
    // Employee detail
    detailDuration: "ระยะเวลาทำงาน", detailWorkDays: "วันที่ทำงาน",
    detailLeaveDays: "วันที่ลา", detailCompDays: "วันชดเชย",
    overallCredit: (n) => `เครดิตสะสม: +${n} วัน`,
    overallDebt: (n) => `ยอดค้าง: ${n} วัน`,
    overallBalDetail: (c, l, b) => `ชดเชย ${c} วัน − ลา ${l} วัน = ${b >= 0 ? "+" : ""}${b}`,
    overallNote: "ยอดนี้จะชำระเมื่อลาออก",
    labelStartedOn: "เริ่มงาน", labelSalaryPerMonth: "บาท/เดือน",
    btnCalendar: "ปฏิทินการทำงาน", btnMonthlySummary: "สรุปรายเดือน", btnPayment: "จ่ายเงินเดือน",
    btnResign: "แจ้งลาออก", btnCancelResign: "ยกเลิกลาออก",
    resignSummaryTitle: (d) => `สรุปการลาออก — ${d}`,
    resignLastMonth: "เงินเดือนเดือนสุดท้าย",
    resignCreditAll: (n, dr) => `เครดิตชดเชยสะสมทั้งหมด (+${n} วัน × ${fmtMoney(dr)} บาท)`,
    resignDeductAll: (n, dr) => `หักวันลาสะสมทั้งหมด (${n} วัน × ${fmtMoney(dr)} บาท)`,
    resignFinalLabel: "ยอดที่ต้องจ่ายวันลาออก",
    resignFinalDeduct: (a) => `หัก ${fmtMoney(a)} บาท`,
    // Attendance
    attendanceTitle: "บันทึกการทำงาน", btnThisMonthSummary: "สรุปเดือนนี้",
    calHint: "คลิกที่วันเพื่อเปลี่ยนสถานะ · วันอาทิตย์สลับระหว่าง <strong>หยุด ↔ ชดเชย</strong> · วันทำงานสลับ <strong>ทำงาน ↔ ลา</strong>",
    legendLabel: "คำอธิบาย:",
    // Summary
    summaryTitle: "สรุปรายเดือน", btnViewCalendar: "ดูปฏิทิน",
    labelWorkDays: "วันทำงาน", labelLeaveDays: "วันที่ลา",
    labelHolidayDays: "วันหยุดอาทิตย์", labelCompDays: "วันชดเชย",
    salaryCalcTitle: "การคำนวณเงินเดือน",
    rowFullSalary: "เงินเดือน (ทั้งเดือน)", rowDailyRate: "อัตราค่าจ้างรายวัน",
    rowBaseSalary: "ฐานเงินเดือนเดือนนี้",
    rowLeaveAccum: (n) => `วันลา ${n} วัน → สะสมรอชำระวันลาออก`,
    rowCompAccum: (n) => `วันชดเชย ${n} วัน → สะสมรอชำระวันลาออก`,
    rowLeaveDeduct: (n) => `หักวันลาเกินสะสม ${n} วัน (รอบ 2)`,
    rowActualPay: "ยอดที่ควรจ่ายเดือนนี้",
    carryoverLabel: "ยอดยกมาจากเดือนก่อน:",
    cumulativeLabel: "ยอดสะสมรวมเดือนนี้:",
    cumulativeCredit: "(เครดิตสะสม)", cumulativeDebt: (n) => `(ยังค้างชดเชย ${n} วัน)`,
    summaryPolicyNote: "วันลาและชดเชยสะสมตลอด ไม่มีการหักเงินเดือนรายเดือน · จะชำระยอดรวมในวันลาออก",
    summaryPolicyNoteCapped: (n) => `วันลาเกินสะสม ${n} วัน/เดือน จะถูกหักจากรอบ 2 ของเดือนนั้น · ส่วนที่เหลือชำระเมื่อลาออก`,
    p2DeductLabel: (days) => `หักวันลาเกินสะสม ${days} วัน`,
    p2GrossLabel: "เงินเดือนครึ่งหลัง (ก่อนหัก)",
    p2NetLabel: "ยอดหลังหัก",
    // Leave log
    leaveCalTitle: "ปฏิทินการทำงาน", calHint2: "คลิกที่วันเพื่อเปลี่ยนสถานะ · อาทิตย์: <strong>หยุด ↔ ชดเชย</strong> · วันทำงาน: <strong>ทำงาน ↔ ลา</strong>",
    leaveSectionTitle: (m) => `วันลาเดือน${m}`, noLeaveMonth: "ไม่มีวันลาในเดือนนี้",
    noLeaveNote: "ไม่ระบุสาเหตุ", editLeavePrompt: "แก้ไขสาเหตุการลา:",
    // Payments
    paymentTitle: "จ่ายเงินเดือน", period1Label: "รอบแรก — วันที่ 15",
    period2Label: "รอบสอง — สิ้นเดือน", dueDateLabel: "ครบกำหนด",
    period2Note: "เงินเดือนครึ่งหลัง",
    paidAtLabel: "จ่ายแล้ว —", badgePaid: "จ่ายแล้ว", badgePending: "รอจ่าย",
    btnMarkPaid: "บันทึกจ่ายแล้ว", btnUnmarkPaid: "ยกเลิก",
    alertAllPaid: "จ่ายครบทั้งเดือนแล้ว",
    alertPending: (n, a) => `ยังค้างจ่าย ${n} รอบ — รวม ${fmtMoney(a)} บาท`,
    noPaymentMonth: "ไม่มีรายการจ่ายในเดือนนี้",
    paymentNote: "รอบแรกจ่ายครึ่งเดือน · รอบสองจ่ายครึ่งที่เหลือ (หักวันลาเกินสะสมถ้ามีการตั้งค่าไว้)",
    // Confirmations
    confirmLeave: (d) => `บันทึก "ลา" วันที่ ${d}?`,
    confirmComp: (d) => `บันทึก "ชดเชย" (ทำวันอาทิตย์) วันที่ ${d}?`,
    confirmDeleteMsg: (n) => `ลบข้อมูลแม่บ้าน "${n}" ทั้งหมดออกจากระบบ?\nการกระทำนี้ไม่สามารถยกเลิกได้`,
    confirmResignPrompt: (n) => `วันที่ ${n} ลาออก (YYYY-MM-DD):`,
    confirmResignInvalid: "รูปแบบวันที่ไม่ถูกต้อง กรุณาใช้ YYYY-MM-DD เช่น 2026-04-14",
    confirmResignNotePrompt: "เหตุผลการลาออก (ไม่บังคับ):",
    confirmResignFinal: (n, d) => `ยืนยันบันทึกการลาออกของ "${n}" วันที่ ${d}?`,
    confirmCancelResign: (n) => `ยืนยันยกเลิกการลาออกของ "${n}"?`,
    // Half-day dialog
    confirmLeaveTitle: "บันทึกวันลา",
    confirmCompTitle: "บันทึกวันชดเชย",
    fullDay: "เต็มวัน",
    halfDay: "ครึ่งวัน",
    statusLeaveHalf: "ลา ½",
    statusCompHalf: "ชดเชย ½",
    // Balance preview (before resign)
    overallBalAmount: (a) => `≈ ${a >= 0 ? "+" : ""}${fmtMoney(a)} บาท`,
    overallBalRate: (dr) => `(อัตราวันละ ${fmtMoney(dr)} บาท)`,
    // Reminders
    remindersTitle: "การแจ้งเตือนงาน",
    reminderAdd: "เพิ่มการแจ้งเตือน",
    reminderEmpty: "ยังไม่มีการแจ้งเตือน กดปุ่มด้านบนเพื่อเพิ่ม",
    reminderName: "ชื่องาน",
    reminderMessage: "ข้อความแจ้งเตือน",
    reminderScheduleType: "รูปแบบกำหนดการ",
    schedTypeDigit: "ทุกวันที่ลงท้ายด้วยตัวเลข (รายเดือน)",
    schedTypeWeekday: "ทุกวันในสัปดาห์ที่เลือก (รายสัปดาห์)",
    reminderDigits: "เลือกตัวเลขท้ายวันที่",
    digitHint: "เช่น เลือก 0 = ส่งทุกวันที่ 10, 20, 30",
    reminderWeekdays: "เลือกวันในสัปดาห์",
    reminderTime: "เวลาแจ้งเตือน",
    reminderEnabled: "เปิดการแจ้งเตือน",
    reminderOn: "เปิด",
    reminderOff: "ปิด",
    reminderTest: "ทดสอบส่ง",
    reminderAddTitle: "เพิ่มการแจ้งเตือน",
    reminderEditTitle: "แก้ไขการแจ้งเตือน",
    reminderTestOk: (n) => `ส่งข้อความทดสอบ "${n}" แล้ว (ถ้าตั้งค่า LINE ไว้)`,
    reminderDeleteConfirm: "ลบการแจ้งเตือนนี้?",
  },
  en: {
    appTitle: "Household Staff Tracker",
    langBtn: "TH",
    months: ["","January","February","March","April","May","June",
             "July","August","September","October","November","December"],
    daysShort: ["Su","Mo","Tu","We","Th","Fr","Sa"],
    yearOffset: 0,
    // Status
    statusWork: "Work", statusLeave: "Leave", statusHoliday: "Day Off",
    statusCompensatory: "Comp.", statusBeforeStart: "—",
    // Common
    home: "Home", save: "Save", cancel: "Cancel", edit: "Edit",
    baht: "Baht", perDay: "Baht/day", errGeneral: "Error: ",
    errSave: "Save failed: ", errDelete: "Delete failed: ",
    errCancelResign: "Cancel failed: ", errEditNote: "Edit failed: ",
    // Employee list
    listTitle: "Household Staff", addBtn: "Add Staff",
    emptyList: "No staff in the system. Click above to add.",
    resignedBadge: "Resigned", labelStarted: "Started:", labelResigned: "Resigned:",
    labelSalary: "Salary",
    // Employee form
    formTitleNew: "Add New Staff", formTitleEdit: "Edit Staff Info",
    fieldName: "Full Name", fieldAge: "Age", fieldNationality: "Nationality",
    fieldPhone: "Phone", fieldLineId: "LINE ID", fieldFacebook: "Facebook (optional)",
    fieldStartDate: "Start Date", fieldSalary: "Monthly Salary (Baht)",
    fieldMaxLeaveCarry: "Max Leave Carry (optional)",
    fieldMaxLeaveCarryHint: "Max leave-debt days allowed per month without salary deduction. E.g. 3 = up to 3 days owed before deduction kicks in for Period 2.",
    nationalityOptions: ["Thai","Myanmar","Cambodian","Lao","Vietnamese","Other"],
    salaryPreview: (dr) => `Daily rate ≈ <strong>${dr} Baht/day</strong> (based on 26 working days/month)`,
    btnSaveEdit: "Save Changes", btnAddNew: "Add Staff",
    // Employee detail
    detailDuration: "Duration", detailWorkDays: "Work Days",
    detailLeaveDays: "Leave Days", detailCompDays: "Comp. Days",
    overallCredit: (n) => `Credit Balance: +${n} days`,
    overallDebt: (n) => `Outstanding: ${n} days`,
    overallBalDetail: (c, l, b) => `Comp ${c}d − Leave ${l}d = ${b >= 0 ? "+" : ""}${b}`,
    overallNote: "Settled on resignation",
    labelStartedOn: "Started", labelSalaryPerMonth: "Baht/month",
    btnCalendar: "Work Calendar", btnMonthlySummary: "Monthly Summary", btnPayment: "Pay Salary",
    btnResign: "Record Resignation", btnCancelResign: "Cancel Resignation",
    resignSummaryTitle: (d) => `Resignation Summary — ${d}`,
    resignLastMonth: "Last Month Salary",
    resignCreditAll: (n, dr) => `Accumulated Comp. Credit (+${n} days × ${fmtMoney(dr)} Baht)`,
    resignDeductAll: (n, dr) => `Accumulated Leave Deduction (${n} days × ${fmtMoney(dr)} Baht)`,
    resignFinalLabel: "Final Amount on Resignation Day",
    resignFinalDeduct: (a) => `Deduct ${fmtMoney(a)} Baht`,
    // Attendance
    attendanceTitle: "Attendance Record", btnThisMonthSummary: "This Month's Summary",
    calHint: "Click a day to change status · Sunday toggles <strong>Day Off ↔ Comp.</strong> · Weekday toggles <strong>Work ↔ Leave</strong>",
    legendLabel: "Legend:",
    // Summary
    summaryTitle: "Monthly Summary", btnViewCalendar: "View Calendar",
    labelWorkDays: "Work Days", labelLeaveDays: "Leave Days",
    labelHolidayDays: "Sundays Off", labelCompDays: "Comp. Days",
    salaryCalcTitle: "Salary Calculation",
    rowFullSalary: "Monthly Salary (full)", rowDailyRate: "Daily Rate",
    rowBaseSalary: "Base Salary This Month",
    rowLeaveAccum: (n) => `Leave ${n} days → tracked, settled on resignation`,
    rowCompAccum: (n) => `Comp. ${n} days → tracked, settled on resignation`,
    rowLeaveDeduct: (n) => `Leave cap exceeded by ${n} days — deducted (Period 2)`,
    rowActualPay: "Amount to Pay This Month",
    carryoverLabel: "Carried from prior months:",
    cumulativeLabel: "Cumulative balance this month:",
    cumulativeCredit: "(credit balance)", cumulativeDebt: (n) => `(${n} days still owed)`,
    summaryPolicyNote: "Leave & comp. days accumulate — no monthly deduction · Full settlement on resignation",
    summaryPolicyNoteCapped: (n) => `Leave debt exceeding ${n} day(s)/month is deducted from Period 2 · Remainder settled on resignation`,
    p2DeductLabel: (days) => `Leave cap exceeded by ${days} day(s) — deducted`,
    p2GrossLabel: "Second-half salary (before deduction)",
    p2NetLabel: "Net after deduction",
    // Leave log
    leaveCalTitle: "Work Calendar", calHint2: "Click a day to change status · Sunday: <strong>Day Off ↔ Comp.</strong> · Weekday: <strong>Work ↔ Leave</strong>",
    leaveSectionTitle: (m) => `Leave Days — ${m}`, noLeaveMonth: "No leave days this month",
    noLeaveNote: "No reason provided", editLeavePrompt: "Edit leave reason:",
    // Payments
    paymentTitle: "Pay Salary", period1Label: "Period 1 — 15th",
    period2Label: "Period 2 — End of Month", dueDateLabel: "Due",
    period2Note: "Second half salary",
    paidAtLabel: "Paid —", badgePaid: "Paid", badgePending: "Pending",
    btnMarkPaid: "Mark as Paid", btnUnmarkPaid: "Undo",
    alertAllPaid: "All payments for this month are complete",
    alertPending: (n, a) => `${n} payment(s) pending — Total ${fmtMoney(a)} Baht`,
    noPaymentMonth: "No payments for this month",
    paymentNote: "Period 1 = half salary · Period 2 = remaining half (leave cap deducted if configured)",
    // Confirmations
    confirmLeave: (d) => `Mark as "Leave" on ${d}?`,
    confirmComp: (d) => `Mark as "Compensatory" (worked Sunday) on ${d}?`,
    confirmDeleteMsg: (n) => `Delete all records for "${n}"?\nThis action cannot be undone.`,
    confirmResignPrompt: (n) => `Resignation date for ${n} (YYYY-MM-DD):`,
    confirmResignInvalid: "Invalid date format. Use YYYY-MM-DD e.g. 2026-04-14",
    confirmResignNotePrompt: "Reason for resignation (optional):",
    confirmResignFinal: (n, d) => `Confirm resignation of "${n}" on ${d}?`,
    confirmCancelResign: (n) => `Cancel resignation of "${n}"?`,
    // Half-day dialog
    confirmLeaveTitle: "Record Leave",
    confirmCompTitle: "Record Compensatory",
    fullDay: "Full Day",
    halfDay: "Half Day",
    statusLeaveHalf: "Leave ½",
    statusCompHalf: "Comp. ½",
    // Balance preview (before resign)
    overallBalAmount: (a) => `≈ ${a >= 0 ? "+" : ""}${fmtMoney(a)} Baht`,
    overallBalRate: (dr) => `(${fmtMoney(dr)} Baht/day)`,
    // Reminders
    remindersTitle: "Task Reminders",
    reminderAdd: "Add Reminder",
    reminderEmpty: "No reminders set up yet. Click above to add one.",
    reminderName: "Task Name",
    reminderMessage: "Reminder Message",
    reminderScheduleType: "Schedule Type",
    schedTypeDigit: "Monthly (by last digit of date)",
    schedTypeWeekday: "Weekly (select days of week)",
    reminderDigits: "Select day-ending digits",
    digitHint: "e.g. digit 0 = sends on day 10, 20, 30",
    reminderWeekdays: "Select days of week",
    reminderTime: "Send Time",
    reminderEnabled: "Notifications enabled",
    reminderOn: "On",
    reminderOff: "Off",
    reminderTest: "Test Send",
    reminderAddTitle: "Add Reminder",
    reminderEditTitle: "Edit Reminder",
    reminderTestOk: (n) => `Test message "${n}" sent (if LINE is configured)`,
    reminderDeleteConfirm: "Delete this reminder?",
  },
};

let currentLang = localStorage.getItem("maidTrackerLang") || "th";

function t(key, ...args) {
  const val = TRANSLATIONS[currentLang]?.[key] ?? TRANSLATIONS.th[key] ?? key;
  return typeof val === "function" ? val(...args) : val;
}

// Status label helper (language-aware)
function sl(status) {
  const map = {
    work: t("statusWork"), leave: t("statusLeave"),
    holiday: t("statusHoliday"), compensatory: t("statusCompensatory"),
    before_start: "—",
  };
  return map[status] || status;
}

// Status label with half-day suffix
function slLabel(status, halfDay = false) {
  if (!halfDay) return sl(status);
  if (status === "leave") return t("statusLeaveHalf");
  if (status === "compensatory") return t("statusCompHalf");
  return sl(status);
}

function switchLang() {
  currentLang = currentLang === "th" ? "en" : "th";
  localStorage.setItem("maidTrackerLang", currentLang);
  document.getElementById("langToggle").textContent = t("langBtn");
  const brand = document.getElementById("navBrand");
  if (brand) brand.innerHTML = `<i class="bi bi-house-heart-fill me-2"></i>${t("appTitle")}`;
  document.title = t("appTitle");
  render();
}

// ─── Root ────────────────────────────────────────────────────

const ROOT = document.getElementById("app");

// Nationality display mapping (DB stores Thai strings)
const NAT_DISPLAY = {
  "ไทย": { th: "ไทย", en: "Thai" },
  "เมียนมา": { th: "เมียนมา", en: "Myanmar" },
  "กัมพูชา": { th: "กัมพูชา", en: "Cambodian" },
  "ลาว": { th: "ลาว", en: "Lao" },
  "เวียดนาม": { th: "เวียดนาม", en: "Vietnamese" },
  "อื่นๆ": { th: "อื่นๆ", en: "Other" },
};
function dispNat(nat) { return NAT_DISPLAY[nat]?.[currentLang] || nat; }

const STATUS_CSS = {
  work: "status-work",
  leave: "status-leave",
  holiday: "status-holiday",
  compensatory: "status-compensatory",
  before_start: "status-before_start",
};

// Weekday names indexed by Python weekday() value: 0=Mon … 6=Sun
const WEEKDAY_NAMES = {
  th: ["จันทร์","อังคาร","พุธ","พฤหัส","ศุกร์","เสาร์","อาทิตย์"],
  en: ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"],
};

// ─── API ────────────────────────────────────────────────────

const api = {
  async get(path) {
    const r = await fetch(path);
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },
  async post(path, body) {
    const r = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },
  async put(path, body) {
    const r = await fetch(path, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },
  async del(path) {
    const r = await fetch(path, { method: "DELETE" });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },
};

// ─── Router ─────────────────────────────────────────────────

function navigate(path) {
  location.hash = "#" + path;
}

function parseRoute() {
  const hash = (location.hash.replace(/^#/, "") || "/").split("?")[0];
  const parts = hash.split("/").filter(Boolean);

  if (parts.length === 0) return { view: "list" };
  if (parts[0] === "reminders") return { view: "reminders" };
  if (parts[0] === "employee") {
    if (parts[1] === "new") return { view: "employee-form", id: null };
    if (parts[2] === "edit") return { view: "employee-form", id: +parts[1] };
    if (parts[2] === "attendance") return { view: "attendance", id: +parts[1] };
    if (parts[2] === "summary") return { view: "summary", id: +parts[1] };
    if (parts[2] === "leaves") return { view: "leaves", id: +parts[1] };
    if (parts[2] === "payments") return { view: "payments", id: +parts[1] };
    return { view: "employee-detail", id: +parts[1] };
  }
  return { view: "list" };
}

window.addEventListener("hashchange", render);

async function render() {
  const route = parseRoute();
  window.__refreshLeaveList = null;
  ROOT.innerHTML = spinner();
  try {
    switch (route.view) {
      case "list":           await viewList(); break;
      case "reminders":      await viewReminders(); break;
      case "employee-form":  await viewEmployeeForm(route.id); break;
      case "employee-detail":await viewEmployeeDetail(route.id); break;
      case "attendance":     await viewAttendance(route.id); break;
      case "summary":        await viewSummary(route.id); break;
      case "leaves":         await viewLeaveLog(route.id); break;
      case "payments":       await viewPayments(route.id); break;
      default:               await viewList();
    }
  } catch (e) {
    ROOT.innerHTML = `<div class="alert alert-danger mt-4">${t("errGeneral")}${e.message}</div>`;
  }
}

// ─── Spinner ────────────────────────────────────────────────

function spinner() {
  return `<div class="spinner-wrap"><div class="spinner-border text-primary" role="status"></div></div>`;
}

// ─── View: Employee List ─────────────────────────────────────

async function viewList() {
  const employees = await api.get("/api/employees");

  const cards = employees.length === 0
    ? `<div class="col-12 text-center text-muted py-5">
         <i class="bi bi-person-x fs-1 d-block mb-2"></i>
         ${t("emptyList")}
       </div>`
    : employees.map(e => {
        const resigned = !!e.end_date;
        return `
        <div class="col-12 col-sm-6 col-lg-4">
          <div class="card emp-card p-3${resigned ? " border-secondary opacity-75" : ""}" onclick="navigate('/employee/${e.id}')">
            <div class="d-flex align-items-center gap-3">
              <div class="rounded-circle ${resigned ? "bg-secondary" : "bg-primary"} text-white d-flex align-items-center justify-content-center"
                   style="width:52px;height:52px;font-size:1.4rem;font-weight:700;flex-shrink:0">
                ${e.name.charAt(0)}
              </div>
              <div class="flex-grow-1 overflow-hidden">
                <div class="fw-bold fs-5 text-truncate">
                  ${e.name}
                  ${resigned ? `<span class="badge bg-secondary ms-1" style="font-size:0.65rem">${t("resignedBadge")}</span>` : ""}
                </div>
                <div class="text-muted small">${dispNat(e.nationality)}${e.age ? " · " + e.age + (currentLang === "th" ? " ปี" : " yrs") : ""}</div>
                <div class="text-muted small">${e.phone || (currentLang === "th" ? "ไม่ระบุเบอร์" : "No phone")}</div>
              </div>
            </div>
            <hr class="my-2" />
            <div class="d-flex justify-content-between small">
              <span class="text-muted">${resigned ? t("labelResigned") + " " + formatDate(e.end_date) : t("labelStarted") + " " + formatDate(e.start_date)}</span>
              <span class="${resigned ? "text-secondary" : "text-success"} fw-semibold">${fmtDuration(e.total_days_employed)}</span>
            </div>
            <div class="d-flex justify-content-between small mt-1">
              <span class="text-muted">${t("labelSalary")}</span>
              <span class="fw-bold">${fmtMoney(e.monthly_salary)} ${t("baht")}</span>
            </div>
          </div>
        </div>`;
      }).join("");

  ROOT.innerHTML = `
    <div class="d-flex justify-content-between align-items-center mb-4">
      <h4 class="fw-bold mb-0"><i class="bi bi-people-fill me-2 text-primary"></i>${t("listTitle")}</h4>
      <button class="btn btn-primary" onclick="navigate('/employee/new')">
        <i class="bi bi-plus-lg me-1"></i>${t("addBtn")}
      </button>
    </div>
    <div class="row g-3">${cards}</div>`;
}

// ─── View: Employee Form (Create / Edit) ─────────────────────

async function viewEmployeeForm(id) {
  let emp = null;
  if (id) emp = await api.get(`/api/employees/${id}`);
  const isEdit = !!id;
  const today = new Date().toISOString().split("T")[0];

  const natOptions = ["ไทย","เมียนมา","กัมพูชา","ลาว","เวียดนาม","อื่นๆ"];
  const natLabels  = t("nationalityOptions");

  ROOT.innerHTML = `
    <div class="page-breadcrumb mb-2">
      <a href="#/" onclick="navigate('/')">${t("home")}</a>
      ${isEdit ? ` › <a href="#/employee/${id}" onclick="navigate('/employee/${id}')">${emp.name}</a> › ${t("edit")}` : ` › ${t("formTitleNew")}`}
    </div>
    <h4 class="fw-bold mb-4">
      <i class="bi bi-person-${isEdit ? "gear" : "plus-fill"} me-2 text-primary"></i>
      ${isEdit ? t("formTitleEdit") : t("formTitleNew")}
    </h4>
    <div class="card border-0 shadow-sm" style="max-width:640px">
      <div class="card-body p-4">
        <form id="empForm">
          <div class="row g-3">
            <div class="col-12">
              <label class="form-label fw-semibold">${t("fieldName")} <span class="text-danger">*</span></label>
              <input type="text" class="form-control" name="name" required value="${emp?.name || ""}" placeholder="${t("fieldName")}" />
            </div>
            <div class="col-6">
              <label class="form-label fw-semibold">${t("fieldAge")}</label>
              <input type="number" class="form-control" name="age" min="18" max="80" value="${emp?.age || ""}" placeholder="${currentLang === "th" ? "ปี" : "yrs"}" />
            </div>
            <div class="col-6">
              <label class="form-label fw-semibold">${t("fieldNationality")}</label>
              <select class="form-select" name="nationality">
                ${natOptions.map((v, i) =>
                  `<option value="${v}" ${(emp?.nationality || "ไทย") === v ? "selected" : ""}>${natLabels[i]}</option>`
                ).join("")}
              </select>
            </div>
            <div class="col-6">
              <label class="form-label fw-semibold">${t("fieldPhone")}</label>
              <input type="tel" class="form-control" name="phone" value="${emp?.phone || ""}" placeholder="08X-XXX-XXXX" />
            </div>
            <div class="col-6">
              <label class="form-label fw-semibold">${t("fieldLineId")}</label>
              <input type="text" class="form-control" name="line_id" value="${emp?.line_id || ""}" placeholder="@lineID" />
            </div>
            <div class="col-12">
              <label class="form-label fw-semibold">${t("fieldFacebook")}</label>
              <input type="text" class="form-control" name="facebook" value="${emp?.facebook || ""}" placeholder="Facebook" />
            </div>
            <div class="col-6">
              <label class="form-label fw-semibold">วันเริ่มงาน <span class="text-danger">*</span></label>
              <input type="date" class="form-control" name="start_date" required value="${emp?.start_date || today}" max="${today}" />
            </div>
            <div class="col-6">
              <label class="form-label fw-semibold">${t("fieldSalary")} <span class="text-danger">*</span></label>
              <input type="number" class="form-control" name="monthly_salary" required min="1" step="1"
                     value="${emp?.monthly_salary || ""}" placeholder="13000" />
            </div>
            <div class="col-12">
              <label class="form-label fw-semibold">${t("fieldMaxLeaveCarry")}</label>
              <input type="number" class="form-control" name="max_leave_carry" min="0" step="0.5"
                     value="${emp?.max_leave_carry ?? ""}" placeholder="${currentLang === "th" ? "เช่น 3" : "e.g. 3"}" />
              <div class="form-text text-muted">${t("fieldMaxLeaveCarryHint")}</div>
            </div>
          </div>
          <div id="salaryPreview" class="alert alert-info mt-3 small d-none"></div>
          <div class="d-flex gap-2 mt-4">
            <button type="submit" class="btn btn-primary px-4">
              <i class="bi bi-check-lg me-1"></i>${isEdit ? t("btnSaveEdit") : t("btnAddNew")}
            </button>
            <button type="button" class="btn btn-outline-secondary" onclick="history.back()">${t("cancel")}</button>
          </div>
        </form>
      </div>
    </div>`;

  // Live salary preview
  const salInput = document.querySelector("[name='monthly_salary']");
  const preview  = document.getElementById("salaryPreview");
  function updatePreview() {
    const sal = parseFloat(salInput.value);
    if (sal > 0) {
      const dr = sal / 26;
      preview.classList.remove("d-none");
      preview.innerHTML = `<i class="bi bi-info-circle me-1"></i>${t("salaryPreview", fmtMoney(dr))}`;
    } else {
      preview.classList.add("d-none");
    }
  }
  salInput.addEventListener("input", updatePreview);
  updatePreview();

  document.getElementById("empForm").addEventListener("submit", async e => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = {
      name:             fd.get("name"),
      age:              fd.get("age") ? +fd.get("age") : null,
      nationality:      fd.get("nationality"),
      phone:            fd.get("phone") || null,
      line_id:          fd.get("line_id") || null,
      facebook:         fd.get("facebook") || null,
      start_date:       fd.get("start_date"),
      monthly_salary:   +fd.get("monthly_salary"),
      max_leave_carry:  fd.get("max_leave_carry") !== "" ? +fd.get("max_leave_carry") : null,
    };
    const btn = e.target.querySelector("[type=submit]");
    btn.disabled = true;
    try {
      if (isEdit) {
        await api.put(`/api/employees/${id}`, body);
        navigate(`/employee/${id}`);
      } else {
        const res = await api.post("/api/employees", body);
        navigate(`/employee/${res.id}`);
      }
    } catch (err) {
      alert(t("errGeneral") + err.message);
      btn.disabled = false;
    }
  });
}

// ─── View: Employee Detail ───────────────────────────────────

async function viewEmployeeDetail(id) {
  const [emp, overall, resignSummary] = await Promise.all([
    api.get(`/api/employees/${id}`),
    api.get(`/api/employees/${id}/overall`),
    api.get(`/api/employees/${id}/resign-summary`).catch(() => null),
  ]);

  const today = new Date();
  const yr = today.getFullYear();
  const mo = today.getMonth() + 1;
  const resigned = !!emp.end_date;

  const balClass = overall.overall_balance >= 0 ? "text-success" : "text-danger";
  const balIcon  = overall.overall_balance >= 0 ? "bi-piggy-bank-fill" : "bi-exclamation-triangle-fill";

  const monthLabel = `${t("months")[mo]} ${yr + t("yearOffset")}`;

  ROOT.innerHTML = `
    <div class="page-breadcrumb mb-2">
      <a href="#/" onclick="navigate('/')">${t("home")}</a> › ${emp.name}
    </div>

    <!-- Profile header -->
    <div class="card border-0 shadow-sm mb-4">
      <div class="card-body p-4">
        <div class="d-flex align-items-start gap-4 flex-wrap">
          <div class="rounded-circle bg-primary text-white d-flex align-items-center justify-content-center flex-shrink-0"
               style="width:72px;height:72px;font-size:2rem;font-weight:800">
            ${emp.name.charAt(0)}
          </div>
          <div class="flex-grow-1">
            <h4 class="fw-bold mb-1">${emp.name}</h4>
            <div class="text-muted mb-2">${dispNat(emp.nationality)}${emp.age ? " · " + emp.age + (currentLang === "th" ? " ปี" : " yrs") : ""}</div>
            <div class="row g-2 small">
              ${emp.phone    ? `<div class="col-auto"><i class="bi bi-telephone me-1 text-primary"></i>${emp.phone}</div>` : ""}
              ${emp.line_id  ? `<div class="col-auto"><i class="bi bi-chat-fill me-1 text-success"></i>${emp.line_id}</div>` : ""}
              ${emp.facebook ? `<div class="col-auto"><i class="bi bi-facebook me-1 text-primary"></i>${emp.facebook}</div>` : ""}
            </div>
          </div>
          <div class="d-flex gap-2 flex-wrap">
            <button class="btn btn-sm btn-outline-primary" onclick="navigate('/employee/${id}/edit')">
              <i class="bi bi-pencil me-1"></i>${t("edit")}
            </button>
            ${resigned
              ? `<button class="btn btn-sm btn-outline-secondary" onclick="cancelResign(${id}, '${emp.name}')">
                   <i class="bi bi-arrow-counterclockwise me-1"></i>${t("btnCancelResign")}
                 </button>`
              : `<button class="btn btn-sm btn-outline-warning" onclick="confirmResign(${id}, '${emp.name}')">
                   <i class="bi bi-door-open me-1"></i>${t("btnResign")}
                 </button>`}
            <button class="btn btn-sm btn-outline-danger" onclick="confirmDelete(${id}, '${emp.name}')">
              <i class="bi bi-trash"></i>
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Stats row -->
    <div class="row g-3 mb-4">
      <div class="col-6 col-md-3">
        <div class="stat-card bg-white">
          <div class="stat-num text-primary">${fmtDuration(overall.total_days_employed)}</div>
          <div class="stat-label text-muted">${t("detailDuration")}</div>
        </div>
      </div>
      <div class="col-6 col-md-3">
        <div class="stat-card bg-white">
          <div class="stat-num text-success">${overall.total_work_days}</div>
          <div class="stat-label text-muted">${t("detailWorkDays")}</div>
        </div>
      </div>
      <div class="col-6 col-md-3">
        <div class="stat-card bg-white">
          <div class="stat-num text-danger">${overall.total_leave_days}</div>
          <div class="stat-label text-muted">${t("detailLeaveDays")}</div>
        </div>
      </div>
      <div class="col-6 col-md-3">
        <div class="stat-card bg-white">
          <div class="stat-num text-info">${overall.total_compensatory_days}</div>
          <div class="stat-label text-muted">${t("detailCompDays")}</div>
        </div>
      </div>
    </div>

    <!-- Overall balance -->
    <div class="finance-banner bg-white mb-4">
      <div class="d-flex align-items-center gap-3 flex-wrap">
        <i class="bi ${balIcon} fs-2 ${balClass}"></i>
        <div class="flex-grow-1">
          <div class="fw-bold fs-5 ${balClass}">
            ${overall.overall_balance >= 0
              ? t("overallCredit", overall.overall_balance)
              : t("overallDebt", Math.abs(overall.overall_balance))}
          </div>
          <div class="text-muted small">
            ${t("overallBalDetail", overall.total_compensatory_days, overall.total_leave_days, overall.overall_balance)}
          </div>
          ${overall.overall_balance !== 0 ? `
          <div class="fw-semibold ${balClass} mt-1">
            ${t("overallBalAmount", overall.balance_amount)}
            <span class="text-muted fw-normal small">${t("overallBalRate", overall.daily_rate)}</span>
          </div>` : ""}
          <div class="text-muted small fst-italic">${t("overallNote")}</div>
        </div>
        <div class="text-end">
          <div class="fw-bold fs-4">${fmtMoney(emp.monthly_salary)} ${t("labelSalaryPerMonth")}</div>
          <div class="text-muted small">${t("labelStartedOn")} ${formatDate(emp.start_date)}</div>
        </div>
      </div>
    </div>

    <!-- Resign summary (shown only when resigned) -->
    ${resignSummary ? `
    <div class="card border-warning border-2 shadow-sm mb-4">
      <div class="card-header bg-warning bg-opacity-25 fw-bold py-2 d-flex align-items-center gap-2">
        <i class="bi bi-door-open text-warning fs-5"></i>
        ${t("resignSummaryTitle", formatDate(resignSummary.end_date))}
        ${resignSummary.resign_note ? `<span class="text-muted fw-normal small ms-auto">${escHtml(resignSummary.resign_note)}</span>` : ""}
      </div>
      <div class="card-body p-0">
        <table class="table mb-0">
          <tbody>
            <tr>
              <td class="ps-4">
                ${t("resignLastMonth")}
                <span class="text-muted small">(${resignSummary.billable_days}${currentLang === "th" ? " วัน" : "d"} × ${fmtMoney(resignSummary.daily_rate)} ${t("baht")})</span>
              </td>
              <td class="text-end pe-4 fw-semibold">${fmtMoney(resignSummary.base_salary)} ${t("baht")}</td>
            </tr>
            ${resignSummary.balance_amount !== 0 ? `
            <tr class="${resignSummary.balance_amount > 0 ? "table-success" : "table-danger"}">
              <td class="ps-4">
                ${resignSummary.balance_amount > 0
                  ? t("resignCreditAll", resignSummary.cumulative_balance, resignSummary.daily_rate)
                  : t("resignDeductAll", Math.abs(resignSummary.cumulative_balance), resignSummary.daily_rate)}
              </td>
              <td class="text-end pe-4 fw-bold ${resignSummary.balance_amount > 0 ? "text-success" : "text-danger"}">
                ${resignSummary.balance_amount > 0 ? "+" : ""}${fmtMoney(resignSummary.balance_amount)} ${t("baht")}
              </td>
            </tr>` : ""}
            <tr class="table-light fw-bold fs-5">
              <td class="ps-4">${t("resignFinalLabel")}</td>
              <td class="text-end pe-4 ${resignSummary.final_amount >= 0 ? "text-success" : "text-danger"}">
                ${resignSummary.final_amount < 0
                  ? t("resignFinalDeduct", Math.abs(resignSummary.final_amount))
                  : `${fmtMoney(resignSummary.final_amount)} ${t("baht")}`}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>` : ""}

    <!-- Quick action buttons -->
    <div class="row g-3">
      <div class="col-6 col-md-3">
        <button class="btn btn-success w-100 py-3" onclick="navigate('/employee/${id}/leaves?y=${yr}&m=${mo}')">
          <i class="bi bi-calendar3 fs-4 d-block mb-1"></i>
          <span class="fw-semibold">${t("btnCalendar")}</span>
          <div class="small opacity-75">${monthLabel}</div>
        </button>
      </div>
      <div class="col-6 col-md-3">
        <button class="btn btn-outline-primary w-100 py-3" onclick="navigate('/employee/${id}/summary?y=${yr}&m=${mo}')">
          <i class="bi bi-bar-chart-line fs-4 d-block mb-1"></i>
          <span class="fw-semibold">${t("btnMonthlySummary")}</span>
          <div class="small opacity-75">${monthLabel}</div>
        </button>
      </div>
      <div class="col-6 col-md-3">
        <button class="btn btn-outline-success w-100 py-3" onclick="navigate('/employee/${id}/payments?y=${yr}&m=${mo}')">
          <i class="bi bi-cash-coin fs-4 d-block mb-1"></i>
          <span class="fw-semibold">${t("btnPayment")}</span>
          <div class="small opacity-75">${monthLabel}</div>
        </button>
      </div>
    </div>`;
}

// ─── View: Attendance Calendar ───────────────────────────────

async function viewAttendance(id) {
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const today  = new Date();
  let year  = +(params.get("y") || today.getFullYear());
  let month = +(params.get("m") || today.getMonth() + 1);

  const [emp, days] = await Promise.all([
    api.get(`/api/employees/${id}`),
    api.get(`/api/employees/${id}/attendance?year=${year}&month=${month}`),
  ]);

  const cells = buildCalendarCells(id, days);
  const legend = buildLegend();

  ROOT.innerHTML = `
    <div class="page-breadcrumb mb-2">
      <a href="#/" onclick="navigate('/')">${t("home")}</a> ›
      <a href="#/employee/${id}" onclick="navigate('/employee/${id}')">${emp.name}</a> ›
      ${t("attendanceTitle")}
    </div>

    <div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
      <h5 class="fw-bold mb-0">
        <i class="bi bi-calendar3 me-2 text-primary"></i>
        ${t("months")[month]} ${year + t("yearOffset")}
      </h5>
      <div class="month-nav">
        <button class="btn btn-sm btn-outline-secondary" onclick="shiftMonth(${id}, ${year}, ${month}, -1)">
          <i class="bi bi-chevron-left"></i>
        </button>
        <button class="btn btn-sm btn-outline-secondary" onclick="shiftMonth(${id}, ${year}, ${month}, 1)">
          <i class="bi bi-chevron-right"></i>
        </button>
        <button class="btn btn-sm btn-outline-primary" onclick="navigate('/employee/${id}/summary?y=${year}&m=${month}')">
          <i class="bi bi-bar-chart-line me-1"></i>${t("btnThisMonthSummary")}
        </button>
      </div>
    </div>

    <!-- Day-of-week headers -->
    <div class="calendar-grid mb-1">
      ${t("daysShort").map((d, i) => `<div class="cal-header ${i === 0 ? "sunday" : ""}">${d}</div>`).join("")}
    </div>

    <div class="calendar-grid mb-4" id="calGrid">${cells}</div>

    <div class="d-flex flex-wrap gap-2 mb-3 align-items-center">
      <span class="text-muted small me-1">${t("legendLabel")}</span>${legend}
    </div>
    <div class="text-muted small">
      <i class="bi bi-info-circle me-1"></i>
      ${t("calHint")}
    </div>`;
}

function shiftMonth(id, year, month, delta) {
  let m = month + delta;
  let y = year;
  if (m < 1)  { m = 12; y--; }
  if (m > 12) { m = 1;  y++; }
  navigate(`/employee/${id}/attendance?y=${y}&m=${m}`);
}

// Returns "full", "half", or null (cancelled)
function askHalfDay(dateStr, type) {
  return new Promise(resolve => {
    let chosen = null;
    const el = document.createElement("div");
    el.className = "modal fade";
    el.setAttribute("tabindex", "-1");
    const title   = type === "leave" ? t("confirmLeaveTitle") : t("confirmCompTitle");
    const btnCss  = type === "leave" ? "btn-danger" : "btn-primary";
    const outCss  = type === "leave" ? "btn-outline-danger" : "btn-outline-primary";
    el.innerHTML = `
      <div class="modal-dialog modal-sm modal-dialog-centered">
        <div class="modal-content">
          <div class="modal-header border-0 pb-0">
            <span class="fw-bold">${title}</span>
            <span class="text-muted small ms-2">${formatDate(dateStr)}</span>
          </div>
          <div class="modal-body pt-2 pb-3">
            <div class="d-grid gap-2">
              <button class="btn btn-sm ${btnCss}" data-val="full">
                <i class="bi bi-brightness-high-fill me-1"></i>${t("fullDay")}
              </button>
              <button class="btn btn-sm ${outCss}" data-val="half">
                <i class="bi bi-circle-half me-1"></i>${t("halfDay")}
              </button>
              <button class="btn btn-sm btn-outline-secondary" data-val="">
                ${t("cancel")}
              </button>
            </div>
          </div>
        </div>
      </div>`;
    document.body.appendChild(el);
    const bsModal = new bootstrap.Modal(el);
    el.querySelectorAll("[data-val]").forEach(btn => {
      btn.addEventListener("click", () => {
        chosen = btn.dataset.val || null;
        bsModal.hide();
      });
    });
    el.addEventListener("hidden.bs.modal", () => { el.remove(); resolve(chosen); }, { once: true });
    bsModal.show();
  });
}

async function cycleDay(empId, dateStr, currentStatus, el) {
  // Cycle logic
  let nextStatus;
  const dow = new Date(dateStr).getDay(); // 0=Sun
  if (dow === 0) {
    nextStatus = currentStatus === "holiday" ? "compensatory" : "holiday";
  } else {
    nextStatus = currentStatus === "work" ? "leave" : "work";
  }

  // For leave / compensatory: ask full day or half day via modal
  let halfDay = false;
  if (nextStatus === "leave" || nextStatus === "compensatory") {
    const choice = await askHalfDay(dateStr, nextStatus === "leave" ? "leave" : "comp");
    if (!choice) return; // user cancelled
    halfDay = choice === "half";
  }

  // Optimistic UI update
  el.className = el.className
    .replace(/status-\S+/, "")
    .trimEnd() + " " + (STATUS_CSS[nextStatus] || "");

  el.querySelector(".status-label").textContent = slLabel(nextStatus, halfDay);
  el.dataset.status = nextStatus;
  el.dataset.halfDay = halfDay ? "1" : "0";
  el.setAttribute("onclick", `cycleDay(${empId},'${dateStr}','${nextStatus}',this)`);

  try {
    await api.post(`/api/employees/${empId}/attendance`, {
      work_date: dateStr,
      status: nextStatus,
      half_day: halfDay,
    });
    if (window.__refreshLeaveList) await window.__refreshLeaveList();
  } catch (e) {
    alert(t("errSave") + e.message);
  }
}

// ─── View: Monthly Summary ───────────────────────────────────

async function viewSummary(id) {
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const today  = new Date();
  const year   = +(params.get("y") || today.getFullYear());
  const month  = +(params.get("m") || today.getMonth() + 1);

  const [emp, summary] = await Promise.all([
    api.get(`/api/employees/${id}`),
    api.get(`/api/employees/${id}/summary?year=${year}&month=${month}`),
  ]);

  const s = summary;
  const isCredit  = s.balance >= 0;
  const finClass  = isCredit ? "bg-success text-white" : "bg-danger text-white";
  ROOT.innerHTML = `
    <div class="page-breadcrumb mb-2">
      <a href="#/" onclick="navigate('/')">${t("home")}</a> ›
      <a href="#/employee/${id}" onclick="navigate('/employee/${id}')">${emp.name}</a> ›
      ${t("summaryTitle")}
    </div>

    <div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
      <h5 class="fw-bold mb-0">
        <i class="bi bi-bar-chart-line me-2 text-primary"></i>
        ${t("summaryTitle")} — ${t("months")[month]} ${year + t("yearOffset")}
      </h5>
      <div class="month-nav">
        <button class="btn btn-sm btn-outline-secondary" onclick="shiftSummary(${id}, ${year}, ${month}, -1)">
          <i class="bi bi-chevron-left"></i>
        </button>
        <button class="btn btn-sm btn-outline-secondary" onclick="shiftSummary(${id}, ${year}, ${month}, 1)">
          <i class="bi bi-chevron-right"></i>
        </button>
        <button class="btn btn-sm btn-outline-success" onclick="navigate('/employee/${id}/attendance?y=${year}&m=${month}')">
          <i class="bi bi-calendar3 me-1"></i>${t("btnViewCalendar")}
        </button>
      </div>
    </div>

    <!-- Stat cards -->
    <div class="row g-3 mb-4">
      <div class="col-6 col-md-3">
        <div class="stat-card bg-white">
          <div class="stat-num text-success">${s.work_days}</div>
          <div class="stat-label text-muted">${t("labelWorkDays")}</div>
        </div>
      </div>
      <div class="col-6 col-md-3">
        <div class="stat-card bg-white">
          <div class="stat-num text-danger">${s.leave_days}</div>
          <div class="stat-label text-muted">${t("labelLeaveDays")}</div>
        </div>
      </div>
      <div class="col-6 col-md-3">
        <div class="stat-card bg-white">
          <div class="stat-num text-secondary">${s.holiday_days}</div>
          <div class="stat-label text-muted">${t("labelHolidayDays")}</div>
        </div>
      </div>
      <div class="col-6 col-md-3">
        <div class="stat-card bg-white">
          <div class="stat-num text-primary">${s.compensatory_days}</div>
          <div class="stat-label text-muted">${t("labelCompDays")}</div>
        </div>
      </div>
    </div>

    <!-- Financial breakdown -->
    <div class="card border-0 shadow-sm mb-4">
      <div class="card-header bg-white fw-bold py-3">
        <i class="bi bi-currency-dollar me-2 text-warning"></i>${t("salaryCalcTitle")}
      </div>
      <div class="card-body p-0">
        <table class="table mb-0">
          <tbody>
            <tr>
              <td class="ps-4">${t("rowFullSalary")}</td>
              <td class="text-end pe-4 fw-semibold">${fmtMoney(s.monthly_salary)} ${t("baht")}</td>
            </tr>
            <tr>
              <td class="ps-4">
                ${t("rowDailyRate")}
                <span class="text-muted small">(${s.monthly_salary.toLocaleString()} ÷ ${s.working_days_in_month}${currentLang === "th" ? " วัน" : "d"})</span>
              </td>
              <td class="text-end pe-4">${fmtMoney(s.daily_rate)} ${t("perDay")}</td>
            </tr>
            <tr>
              <td class="ps-4">${t("rowBaseSalary")}</td>
              <td class="text-end pe-4">${fmtMoney(s.base_salary)} ${t("baht")}</td>
            </tr>
            ${s.leave_days > 0 ? `
            <tr class="table-warning">
              <td class="ps-4 text-warning-emphasis">${t("rowLeaveAccum", s.leave_days)}</td>
              <td class="text-end pe-4 text-muted">—</td>
            </tr>` : ""}
            ${s.compensatory_days > 0 ? `
            <tr class="table-info">
              <td class="ps-4 text-info-emphasis">${t("rowCompAccum", s.compensatory_days)}</td>
              <td class="text-end pe-4 text-muted">—</td>
            </tr>` : ""}
            ${s.leave_deduction_days > 0 ? `
            <tr class="table-danger">
              <td class="ps-4 text-danger-emphasis">${t("rowLeaveDeduct", s.leave_deduction_days)}</td>
              <td class="text-end pe-4 text-danger fw-semibold">-${fmtMoney(s.deduction_amount)} ${t("baht")}</td>
            </tr>` : ""}
            <tr class="table-light fw-bold fs-5">
              <td class="ps-4">${t("rowActualPay")}</td>
              <td class="text-end pe-4 text-primary">${fmtMoney(s.actual_pay)} ${t("baht")}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Cumulative balance -->
    ${s.cumulative_balance !== 0 ? `
    <div class="card border-0 shadow-sm mb-4">
      <div class="card-body py-3 px-4 d-flex align-items-center gap-3">
        <i class="bi bi-arrow-repeat fs-4 ${s.cumulative_balance > 0 ? "text-success" : "text-danger"}"></i>
        <div class="flex-grow-1">
          ${s.carryover_balance !== 0 ? `
          <div class="fw-semibold">
            ${t("carryoverLabel")}
            <span class="${s.carryover_balance > 0 ? "text-success" : "text-danger"} ms-1">
              ${s.carryover_balance > 0 ? "+" : ""}${s.carryover_balance}${currentLang === "th" ? " วัน" : "d"}
            </span>
          </div>` : ""}
          <div class="text-muted small">
            ${t("cumulativeLabel")}
            <strong class="${s.cumulative_balance >= 0 ? "text-success" : "text-danger"}">
              ${s.cumulative_balance >= 0 ? "+" : ""}${s.cumulative_balance}${currentLang === "th" ? " วัน" : "d"}
            </strong>
            ${s.cumulative_balance < 0 ? t("cumulativeDebt", Math.abs(s.cumulative_balance)) : t("cumulativeCredit")}
          </div>
        </div>
      </div>
    </div>` : ""}

    <div class="alert ${s.max_leave_carry != null ? "alert-warning" : "alert-info"} d-flex align-items-start gap-2 small mb-0">
      <i class="bi bi-info-circle-fill flex-shrink-0 mt-1"></i>
      <span>${s.max_leave_carry != null ? t("summaryPolicyNoteCapped", s.max_leave_carry) : t("summaryPolicyNote")}</span>
    </div>`;
}

function shiftSummary(id, year, month, delta) {
  let m = month + delta;
  let y = year;
  if (m < 1)  { m = 12; y--; }
  if (m > 12) { m = 1;  y++; }
  navigate(`/employee/${id}/summary?y=${y}&m=${m}`);
}

// ─── View: Calendar + Leave Log (merged) ─────────────────────

async function viewLeaveLog(id) {
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const today  = new Date();
  let year  = +(params.get("y") || today.getFullYear());
  let month = +(params.get("m") || today.getMonth() + 1);

  const [emp, days] = await Promise.all([
    api.get(`/api/employees/${id}`),
    api.get(`/api/employees/${id}/attendance?year=${year}&month=${month}`),
  ]);

  const cells = buildCalendarCells(id, days);
  const legend = buildLegend();

  ROOT.innerHTML = `
    <div class="page-breadcrumb mb-2">
      <a href="#/" onclick="navigate('/')">${t("home")}</a> ›
      <a href="#/employee/${id}" onclick="navigate('/employee/${id}')">${emp.name}</a> ›
      ${t("leaveCalTitle")}
    </div>

    <div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
      <h5 class="fw-bold mb-0">
        <i class="bi bi-calendar3 me-2 text-primary"></i>
        ${t("months")[month]} ${year + t("yearOffset")}
      </h5>
      <div class="month-nav">
        <button class="btn btn-sm btn-outline-secondary" onclick="shiftLeaves(${id}, ${year}, ${month}, -1)">
          <i class="bi bi-chevron-left"></i>
        </button>
        <button class="btn btn-sm btn-outline-secondary" onclick="shiftLeaves(${id}, ${year}, ${month}, 1)">
          <i class="bi bi-chevron-right"></i>
        </button>
        <button class="btn btn-sm btn-outline-primary" onclick="navigate('/employee/${id}/summary?y=${year}&m=${month}')">
          <i class="bi bi-bar-chart-line me-1"></i>${t("btnThisMonthSummary")}
        </button>
      </div>
    </div>

    <div class="calendar-grid mb-1">
      ${t("daysShort").map((d, i) => `<div class="cal-header ${i === 0 ? "sunday" : ""}">${d}</div>`).join("")}
    </div>
    <div class="calendar-grid mb-3" id="calGrid">${cells}</div>

    <div class="d-flex flex-wrap gap-2 mb-2 align-items-center">
      <span class="text-muted small me-1">${t("legendLabel")}</span>${legend}
    </div>
    <div class="text-muted small mb-4">
      <i class="bi bi-info-circle me-1"></i>
      ${t("calHint2")}
    </div>

    <div id="leaveListSection"></div>`;

  renderLeaveList(id, days, month);

  // After cycleDay saves, refresh both calendar cells and leave list
  window.__refreshLeaveList = async () => {
    const fresh = await api.get(`/api/employees/${id}/attendance?year=${year}&month=${month}`);
    // update calendar cells in place
    for (const d of fresh) {
      const cell = document.querySelector(`#calGrid [data-date="${d.date}"]`);
      if (!cell) continue;
      const isBefore = d.status === "before_start";
      const isFuture = d.is_future;
      const disabled = isBefore || isFuture;
      const statusCss = isFuture ? "status-future" : (STATUS_CSS[d.status] || "");
      cell.className = `cal-day ${statusCss}${disabled ? " cal-disabled" : ""}${isFuture ? " cal-future" : ""}`;
      cell.querySelector(".status-label").textContent = isFuture ? "—" : slLabel(d.status, d.half_day);
      cell.dataset.status = d.status;
      cell.dataset.halfDay = d.half_day ? "1" : "0";
      if (!disabled) {
        cell.setAttribute("onclick", `cycleDay(${id},'${d.date}','${d.status}',this)`);
      } else {
        cell.removeAttribute("onclick");
      }
      // update note display
      let noteEl = cell.querySelector(".cal-note");
      if (d.note) {
        if (!noteEl) {
          noteEl = document.createElement("span");
          noteEl.className = "cal-note text-muted";
          noteEl.style.cssText = "font-size:0.65rem;white-space:nowrap;overflow:hidden;max-width:100%;text-overflow:ellipsis";
          cell.appendChild(noteEl);
        }
        noteEl.textContent = d.note;
        noteEl.title = d.note;
      } else if (noteEl) {
        noteEl.remove();
      }
    }
    renderLeaveList(id, fresh, month);
  };
}

function buildCalendarCells(id, days) {
  const firstDate = days[0]?.date;
  if (!firstDate) return "";
  const firstDow = new Date(firstDate).getDay();
  let html = "";
  for (let i = 0; i < firstDow; i++) html += `<div></div>`;
  for (const d of days) {
    const isBefore  = d.status === "before_start";
    const isFuture  = d.is_future;
    const disabled  = isBefore || isFuture;
    const statusCss = isFuture ? "status-future" : (STATUS_CSS[d.status] || "");
    const label     = isFuture ? "—" : slLabel(d.status, d.half_day);
    const dayNum    = d.date.split("-")[2];
    const noteHtml  = d.note
      ? `<span class="cal-note text-muted" title="${escHtml(d.note)}" style="font-size:0.65rem;white-space:nowrap;overflow:hidden;max-width:100%;text-overflow:ellipsis">${escHtml(d.note)}</span>`
      : "";
    html += `
      <div class="cal-day ${statusCss}${disabled ? " cal-disabled" : ""}${isFuture ? " cal-future" : ""}"
           ${!disabled ? `onclick="cycleDay(${id},'${d.date}','${d.status}',this)"` : ""}
           data-date="${d.date}" data-status="${d.status}" data-half-day="${d.half_day ? 1 : 0}">
        <span class="day-num">${+dayNum}</span>
        <span class="status-label">${label}</span>
        ${noteHtml}
      </div>`;
  }
  return html;
}

function buildLegend() {
  return [
    { css: "status-work",         key: "statusWork",         suffix: "" },
    { css: "status-leave",        key: "statusLeave",        suffix: "" },
    { css: "status-holiday",      key: "statusHoliday",      suffix: currentLang === "th" ? " (อาทิตย์)" : " (Sun)" },
    { css: "status-compensatory", key: "statusCompensatory", suffix: currentLang === "th" ? " (ทำอาทิตย์)" : " (worked Sun)" },
  ].map(l =>
    `<span class="cal-day ${l.css} px-2 py-1" style="min-height:0;border-radius:8px;cursor:default;font-size:0.75rem">${t(l.key)}${l.suffix}</span>`
  ).join("");
}

function renderLeaveList(id, days, month) {
  const section = document.getElementById("leaveListSection");
  if (!section) return;

  const leaveDays = days.filter(d => d.status === "leave");
  const rows = leaveDays.length === 0
    ? `<div class="text-center text-muted py-3 small">${t("noLeaveMonth")}</div>`
    : leaveDays.map(l => `
        <div class="d-flex align-items-center gap-3 py-2 border-bottom">
          <div class="text-danger fw-semibold" style="min-width:130px">
            ${formatDate(l.date)}
            ${l.half_day ? `<span class="badge bg-warning text-dark ms-1" style="font-size:0.6rem">½</span>` : ""}
          </div>
          <div class="flex-grow-1 text-muted small">
            ${l.note ? escHtml(l.note) : `<span class="fst-italic">${t("noLeaveNote")}</span>`}
          </div>
          <button class="btn btn-sm btn-outline-secondary" onclick="editLeaveNote(${id},'${l.date}','${escHtml(l.note || "")}')">
            <i class="bi bi-pencil"></i>
          </button>
        </div>`).join("");

  section.innerHTML = `
    <div class="card border-0 shadow-sm" style="max-width:600px">
      <div class="card-header bg-white fw-semibold py-3 d-flex justify-content-between align-items-center">
        <span><i class="bi bi-calendar-x me-2 text-danger"></i>${t("leaveSectionTitle", t("months")[month])}</span>
        <span class="badge bg-danger">${leaveDays.length}${currentLang === "th" ? " วัน" : "d"}</span>
      </div>
      <div class="card-body px-4 py-2">${rows}</div>
    </div>`;
}

function shiftLeaves(id, year, month, delta) {
  let m = month + delta;
  let y = year;
  if (m < 1)  { m = 12; y--; }
  if (m > 12) { m = 1;  y++; }
  navigate(`/employee/${id}/leaves?y=${y}&m=${m}`);
}

async function editLeaveNote(empId, dateStr, currentNote) {
  const note = prompt(t("editLeavePrompt"), currentNote || "");
  if (note === null) return;
  try {
    await api.post(`/api/employees/${empId}/attendance`, {
      work_date: dateStr,
      status: "leave",
      note: note || null,
    });
    if (window.__refreshLeaveList) await window.__refreshLeaveList();
  } catch (e) {
    alert(t("errEditNote") + e.message);
  }
}

function escHtml(str) {
  if (!str) return "";
  return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// ─── View: Salary Payments ───────────────────────────────────

async function viewPayments(id) {
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const today  = new Date();
  let year  = +(params.get("y") || today.getFullYear());
  let month = +(params.get("m") || today.getMonth() + 1);

  const [emp, payments] = await Promise.all([
    api.get(`/api/employees/${id}`),
    api.get(`/api/employees/${id}/payments?year=${year}&month=${month}`),
  ]);

  function periodCard(p) {
    const isPaid    = p.paid;
    const label     = p.period === 1 ? t("period1Label") : t("period2Label");
    const hasDeduct = p.period === 2 && p.leave_deduction_days > 0;
    const grossAmt  = hasDeduct ? p.amount + p.deduction_amount : p.amount;

    const deductBreakdown = hasDeduct ? `
      <div class="mt-2 p-2 rounded bg-danger bg-opacity-10 border border-danger border-opacity-25 small">
        <div class="d-flex justify-content-between">
          <span class="text-muted">${t("p2GrossLabel")}</span>
          <span>${fmtMoney(grossAmt)} ${t("baht")}</span>
        </div>
        <div class="d-flex justify-content-between text-danger">
          <span>${t("p2DeductLabel", p.leave_deduction_days)}</span>
          <span>-${fmtMoney(p.deduction_amount)} ${t("baht")}</span>
        </div>
        <div class="d-flex justify-content-between fw-bold border-top mt-1 pt-1">
          <span>${t("p2NetLabel")}</span>
          <span>${fmtMoney(p.amount)} ${t("baht")}</span>
        </div>
      </div>` : `<div class="text-muted small mt-1">${t("period2Note")}</div>`;

    const noteSection = p.period === 2 ? deductBreakdown : "";

    return `
      <div class="card border-0 shadow-sm mb-3">
        <div class="card-body">
          <div class="d-flex align-items-start gap-3">
            <div class="flex-grow-1">
              <div class="fw-bold">${label}</div>
              <div class="text-muted small mb-2">${t("dueDateLabel")} ${formatDate(p.due_date)}</div>
              <div class="text-dark fw-bold fs-5">${fmtMoney(p.amount)} ${t("baht")}</div>
              ${noteSection}
              ${isPaid ? `<div class="text-success small mt-1"><i class="bi bi-check-circle-fill me-1"></i>${t("paidAtLabel")} ${escHtml(p.paid_at || "")}</div>` : ""}
            </div>
            <div class="text-end flex-shrink-0">
              <div class="badge ${isPaid ? "bg-success" : "bg-warning text-dark"} mb-2">${isPaid ? t("badgePaid") : t("badgePending")}</div>
              <br>
              <button class="btn btn-sm ${isPaid ? "btn-outline-secondary" : "btn-primary"}"
                      onclick="togglePayment(${id}, ${year}, ${month}, ${p.period}, this)">
                <i class="bi ${isPaid ? "bi-x-circle" : "bi-check-circle"} me-1"></i>${isPaid ? t("btnUnmarkPaid") : t("btnMarkPaid")}
              </button>
            </div>
          </div>
        </div>
      </div>`;
  }

  const cards = payments.length === 0
    ? `<div class="text-center text-muted py-5"><i class="bi bi-calendar-x fs-1 d-block mb-2"></i>${t("noPaymentMonth")}</div>`
    : payments.map(periodCard).join("");

  const allPaid = payments.length > 0 && payments.every(p => p.paid);
  const pending = payments.filter(p => !p.paid);

  ROOT.innerHTML = `
    <div class="page-breadcrumb mb-2">
      <a href="#/" onclick="navigate('/')">${t("home")}</a> ›
      <a href="#/employee/${id}" onclick="navigate('/employee/${id}')">${emp.name}</a> ›
      ${t("paymentTitle")}
    </div>

    <div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
      <h5 class="fw-bold mb-0">
        <i class="bi bi-cash-coin me-2 text-success"></i>
        ${t("paymentTitle")} — ${t("months")[month]} ${year + t("yearOffset")}
      </h5>
      <div class="month-nav">
        <button class="btn btn-sm btn-outline-secondary" onclick="shiftPayments(${id}, ${year}, ${month}, -1)">
          <i class="bi bi-chevron-left"></i>
        </button>
        <button class="btn btn-sm btn-outline-secondary" onclick="shiftPayments(${id}, ${year}, ${month}, 1)">
          <i class="bi bi-chevron-right"></i>
        </button>
      </div>
    </div>

    ${allPaid ? `<div class="alert alert-success d-flex align-items-center gap-2 mb-3"><i class="bi bi-check-circle-fill fs-5"></i> ${t("alertAllPaid")}</div>` : ""}
    ${pending.length > 0 ? `<div class="alert alert-warning d-flex align-items-center gap-2 mb-3"><i class="bi bi-clock fs-5"></i> ${t("alertPending", pending.length, pending.reduce((s, p) => s + p.amount, 0))}</div>` : ""}

    ${cards}

    <div class="text-muted small mt-2">
      <i class="bi bi-info-circle me-1"></i>
      ${t("paymentNote")}
    </div>`;
}

function shiftPayments(id, year, month, delta) {
  let m = month + delta;
  let y = year;
  if (m < 1)  { m = 12; y--; }
  if (m > 12) { m = 1;  y++; }
  navigate(`/employee/${id}/payments?y=${y}&m=${m}`);
}

async function togglePayment(empId, year, month, period, btn) {
  btn.disabled = true;
  try {
    await api.post(`/api/employees/${empId}/payments/${period}/toggle?year=${year}&month=${month}`, {});
    await viewPayments(empId);
  } catch (e) {
    alert(t("errSave") + e.message);
    btn.disabled = false;
  }
}

// ─── Resign / Cancel Resign ──────────────────────────────────

async function confirmResign(id, name) {
  const today = new Date().toISOString().split("T")[0];
  const dateStr = prompt(t("confirmResignPrompt", name), today);
  if (!dateStr) return;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(dateStr)) {
    alert(t("confirmResignInvalid"));
    return;
  }
  const note = prompt(t("confirmResignNotePrompt"), "") || null;
  if (!confirm(t("confirmResignFinal", name, formatDate(dateStr)))) return;
  try {
    await api.post(`/api/employees/${id}/resign`, { end_date: dateStr, resign_note: note });
    await render();
  } catch (e) {
    alert(t("errSave") + e.message);
  }
}

async function cancelResign(id, name) {
  if (!confirm(t("confirmCancelResign", name))) return;
  try {
    await api.del(`/api/employees/${id}/resign`);
    await render();
  } catch (e) {
    alert(t("errCancelResign") + e.message);
  }
}

// ─── Delete confirmation ─────────────────────────────────────

async function confirmDelete(id, name) {
  if (!confirm(t("confirmDeleteMsg", name))) return;
  try {
    await api.del(`/api/employees/${id}`);
    navigate("/");
  } catch (e) {
    alert(t("errDelete") + e.message);
  }
}

// ─── View: Reminders ────────────────────────────────────────

let _remindersCache = [];

function describeSchedule(r) {
  if (r.schedule_type === "month_day_digit") {
    const digits = r.schedule_value.split(",").map(s => s.trim()).filter(Boolean);
    const exDays = [];
    for (const d of digits) {
      for (let day = 1; day <= 31; day++) {
        if (String(day).endsWith(d)) exDays.push(day);
      }
    }
    exDays.sort((a, b) => a - b);
    if (exDays.length === 0) return r.schedule_value;
    return currentLang === "th"
      ? `ทุกวันที่ ${exDays.join(", ")} ของเดือน`
      : `Monthly: day ${exDays.join(", ")}`;
  }
  if (r.schedule_type === "weekday") {
    const names = WEEKDAY_NAMES[currentLang];
    const dayList = r.schedule_value.split(",")
      .map(s => names[parseInt(s.trim())])
      .filter(Boolean);
    if (dayList.length === 0) return r.schedule_value;
    return currentLang === "th"
      ? `ทุกวัน ${dayList.join(", ")}`
      : `Weekly: ${dayList.join(", ")}`;
  }
  return r.schedule_value;
}

async function viewReminders() {
  _remindersCache = await api.get("/api/reminders");
  const wdNames = WEEKDAY_NAMES[currentLang];

  const digitBtns = [0,1,2,3,4,5,6,7,8,9].map(d =>
    `<input type="checkbox" class="btn-check" id="remDigit${d}" value="${d}" autocomplete="off">` +
    `<label class="btn btn-sm btn-outline-primary rounded-pill px-2" for="remDigit${d}">${d}</label>`
  ).join("");

  const wdBtns = [0,1,2,3,4,5,6].map(d =>
    `<input type="checkbox" class="btn-check" id="remWd${d}" value="${d}" autocomplete="off">` +
    `<label class="btn btn-sm btn-outline-primary rounded-pill px-2" for="remWd${d}">${wdNames[d]}</label>`
  ).join("");

  const listHtml = _remindersCache.length === 0
    ? `<div class="text-center text-muted py-5">
         <i class="bi bi-bell-slash fs-1 d-block mb-2"></i>
         ${t("reminderEmpty")}
       </div>`
    : _remindersCache.map(r => `
        <div class="card border-0 shadow-sm" id="remCard${r.id}">
          <div class="card-body p-3">
            <div class="d-flex align-items-start justify-content-between gap-2">
              <div class="flex-grow-1">
                <div class="d-flex align-items-center gap-2 mb-1">
                  <span class="fw-bold">${escHtml(r.name)}</span>
                  <span class="badge ${r.enabled ? "bg-success" : "bg-secondary"}" id="remBadge${r.id}">
                    ${r.enabled ? t("reminderOn") : t("reminderOff")}
                  </span>
                </div>
                <div class="text-muted small mb-1">
                  <i class="bi bi-calendar-event me-1"></i>${describeSchedule(r)}
                  &nbsp;·&nbsp;<i class="bi bi-clock me-1"></i>${r.send_time}
                </div>
                <div class="text-secondary small fst-italic">${escHtml(r.message)}</div>
              </div>
              <div class="form-check form-switch mb-0 flex-shrink-0 pt-1" style="padding-left:2.5em">
                <input class="form-check-input" type="checkbox" id="remToggle${r.id}"
                  ${r.enabled ? "checked" : ""}
                  onchange="toggleReminder(${r.id}, this)">
              </div>
            </div>
            <div class="d-flex gap-2 mt-2">
              <button class="btn btn-sm btn-outline-secondary" onclick="testReminder(${r.id})">
                <i class="bi bi-send me-1"></i>${t("reminderTest")}
              </button>
              <button class="btn btn-sm btn-outline-primary" onclick="editReminder(${r.id})">
                <i class="bi bi-pencil me-1"></i>${t("edit")}
              </button>
              <button class="btn btn-sm btn-outline-danger" onclick="deleteReminder(${r.id})">
                <i class="bi bi-trash"></i>
              </button>
            </div>
          </div>
        </div>`
    ).join("");

  ROOT.innerHTML = `
    <div class="page-breadcrumb mb-2">
      <a href="#/" onclick="navigate('/')">${t("home")}</a> › ${t("remindersTitle")}
    </div>
    <div class="d-flex justify-content-between align-items-center mb-4">
      <h4 class="fw-bold mb-0">
        <i class="bi bi-bell-fill me-2 text-primary"></i>${t("remindersTitle")}
      </h4>
      <button class="btn btn-primary" onclick="_openReminderModal(null)">
        <i class="bi bi-plus-lg me-1"></i>${t("reminderAdd")}
      </button>
    </div>

    <div id="reminderList" class="d-flex flex-column gap-3">${listHtml}</div>

    <!-- Add / Edit Modal -->
    <div class="modal fade" id="reminderModal" tabindex="-1">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title" id="remModalTitle">${t("reminderAddTitle")}</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
          </div>
          <div class="modal-body">
            <div class="mb-3">
              <label class="form-label fw-semibold">${t("reminderName")} <span class="text-danger">*</span></label>
              <input type="text" class="form-control" id="remFormName"
                placeholder="${currentLang === "th" ? "เช่น เปลี่ยนผ้าปูที่นอน" : "e.g. Change bed sheets"}" />
            </div>
            <div class="mb-3">
              <label class="form-label fw-semibold">${t("reminderMessage")} <span class="text-danger">*</span></label>
              <textarea class="form-control" id="remFormMessage" rows="2"
                placeholder="${currentLang === "th" ? "🛏️ วันนี้เปลี่ยนผ้าปูที่นอนด้วยนะคะ" : "🛏️ Please change the bed sheets today"}"></textarea>
            </div>
            <div class="mb-3">
              <label class="form-label fw-semibold">${t("reminderScheduleType")}</label>
              <div class="d-flex flex-column gap-1 mt-1">
                <div class="form-check">
                  <input class="form-check-input" type="radio" name="remSchedType"
                    id="remTypeDigit" value="month_day_digit" checked>
                  <label class="form-check-label" for="remTypeDigit">${t("schedTypeDigit")}</label>
                </div>
                <div class="form-check">
                  <input class="form-check-input" type="radio" name="remSchedType"
                    id="remTypeWeekday" value="weekday">
                  <label class="form-check-label" for="remTypeWeekday">${t("schedTypeWeekday")}</label>
                </div>
              </div>
            </div>
            <div id="remDigitSection" class="mb-3">
              <label class="form-label fw-semibold">${t("reminderDigits")}</label>
              <div class="d-flex flex-wrap gap-2">${digitBtns}</div>
              <div class="form-text mt-1">${t("digitHint")}</div>
            </div>
            <div id="remWdSection" class="mb-3 d-none">
              <label class="form-label fw-semibold">${t("reminderWeekdays")}</label>
              <div class="d-flex flex-wrap gap-2">${wdBtns}</div>
            </div>
            <div class="row g-3 align-items-end">
              <div class="col-auto">
                <label class="form-label fw-semibold">${t("reminderTime")}</label>
                <input type="time" class="form-control" id="remFormTime" value="07:00" style="max-width:160px">
              </div>
              <div class="col-auto pb-2">
                <div class="form-check form-switch">
                  <input class="form-check-input" type="checkbox" id="remFormEnabled" checked>
                  <label class="form-check-label" for="remFormEnabled">${t("reminderEnabled")}</label>
                </div>
              </div>
            </div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">${t("cancel")}</button>
            <button type="button" class="btn btn-primary" id="remSaveBtn">
              <i class="bi bi-check-lg me-1"></i>${t("save")}
            </button>
          </div>
        </div>
      </div>
    </div>`;

  // ── Schedule type toggle ──
  const typeDigit   = document.getElementById("remTypeDigit");
  const typeWeekday = document.getElementById("remTypeWeekday");
  const digitSec    = document.getElementById("remDigitSection");
  const wdSec       = document.getElementById("remWdSection");

  function syncSchedSections() {
    if (typeDigit.checked) {
      digitSec.classList.remove("d-none");
      wdSec.classList.add("d-none");
    } else {
      digitSec.classList.add("d-none");
      wdSec.classList.remove("d-none");
    }
  }
  typeDigit.addEventListener("change", syncSchedSections);
  typeWeekday.addEventListener("change", syncSchedSections);

  // ── Modal open helper (exposed as window._openReminderModal) ──
  let _bsModal  = null;
  let _editingId = null;

  window._openReminderModal = function(r) {
    _editingId = r ? r.id : null;
    document.getElementById("remModalTitle").textContent = r ? t("reminderEditTitle") : t("reminderAddTitle");
    document.getElementById("remFormName").value    = r ? r.name    : "";
    document.getElementById("remFormMessage").value = r ? r.message : "";
    document.getElementById("remFormTime").value    = r ? r.send_time : "07:00";
    document.getElementById("remFormEnabled").checked = r ? !!r.enabled : true;

    const stype = r ? r.schedule_type : "month_day_digit";
    typeDigit.checked   = stype === "month_day_digit";
    typeWeekday.checked = stype === "weekday";
    syncSchedSections();

    // Clear all selectors
    for (let d = 0; d <= 9; d++) { const cb = document.getElementById(`remDigit${d}`); if (cb) cb.checked = false; }
    for (let d = 0; d <= 6; d++) { const cb = document.getElementById(`remWd${d}`);    if (cb) cb.checked = false; }

    // Restore saved values
    if (r) {
      r.schedule_value.split(",").map(s => s.trim()).forEach(v => {
        const el = document.getElementById(stype === "month_day_digit" ? `remDigit${v}` : `remWd${v}`);
        if (el) el.checked = true;
      });
    }

    if (!_bsModal) _bsModal = new bootstrap.Modal(document.getElementById("reminderModal"));
    _bsModal.show();
  };

  // ── Save ──
  document.getElementById("remSaveBtn").addEventListener("click", async () => {
    const name      = document.getElementById("remFormName").value.trim();
    const message   = document.getElementById("remFormMessage").value.trim();
    const send_time = document.getElementById("remFormTime").value;
    const enabled   = document.getElementById("remFormEnabled").checked;
    const schedule_type = typeDigit.checked ? "month_day_digit" : "weekday";

    if (!name || !message) {
      alert(currentLang === "th" ? "กรุณากรอกชื่อและข้อความ" : "Please fill in name and message");
      return;
    }

    const selVals = [];
    if (schedule_type === "month_day_digit") {
      for (let d = 0; d <= 9; d++) { const cb = document.getElementById(`remDigit${d}`); if (cb?.checked) selVals.push(String(d)); }
    } else {
      for (let d = 0; d <= 6; d++) { const cb = document.getElementById(`remWd${d}`);    if (cb?.checked) selVals.push(String(d)); }
    }
    if (selVals.length === 0) {
      alert(currentLang === "th" ? "กรุณาเลือกกำหนดการอย่างน้อย 1 รายการ" : "Please select at least one schedule option");
      return;
    }

    const body = { name, message, enabled, schedule_type, schedule_value: selVals.join(","), send_time };
    const btn  = document.getElementById("remSaveBtn");
    btn.disabled = true;
    try {
      if (_editingId) await api.put(`/api/reminders/${_editingId}`, body);
      else             await api.post("/api/reminders", body);
      _bsModal.hide();
      await viewReminders();
    } catch (err) {
      alert(t("errSave") + err.message);
      btn.disabled = false;
    }
  });
}

async function toggleReminder(id, checkbox) {
  try {
    const res = await api.post(`/api/reminders/${id}/toggle`);
    const badge = document.getElementById(`remBadge${id}`);
    if (badge) {
      badge.className = `badge ${res.enabled ? "bg-success" : "bg-secondary"}`;
      badge.textContent = res.enabled ? t("reminderOn") : t("reminderOff");
    }
    // Keep cache in sync
    const cached = _remindersCache.find(r => r.id === id);
    if (cached) cached.enabled = res.enabled ? 1 : 0;
  } catch (err) {
    alert(t("errSave") + err.message);
    checkbox.checked = !checkbox.checked;
  }
}

async function testReminder(id) {
  const r = _remindersCache.find(x => x.id === id);
  try {
    await api.post(`/api/reminders/${id}/test`);
    alert(t("reminderTestOk", r ? r.name : String(id)));
  } catch (err) {
    alert(t("errGeneral") + err.message);
  }
}

async function deleteReminder(id) {
  if (!confirm(t("reminderDeleteConfirm"))) return;
  try {
    await api.del(`/api/reminders/${id}`);
    await viewReminders();
  } catch (err) {
    alert(t("errDelete") + err.message);
  }
}

function editReminder(id) {
  const r = _remindersCache.find(x => x.id === id);
  if (r && window._openReminderModal) window._openReminderModal(r);
}

// ─── Utility ────────────────────────────────────────────────

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function fmtMoney(n) {
  return Number(n).toLocaleString("th-TH", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
}

function fmtDuration(totalDays) {
  const totalMonths = Math.floor(totalDays / 30);
  const years  = Math.floor(totalMonths / 12);
  const months = totalMonths % 12;
  const days   = totalDays % 30;
  if (currentLang === "th") {
    return (years  > 0 ? years  + "ปี "    : "")
         + (months > 0 ? months + "เดือน " : "")
         + days + "วัน";
  }
  return (years  > 0 ? years  + "y " : "")
       + (months > 0 ? months + "m " : "")
       + days + "d";
}

function formatDate(isoStr) {
  if (!isoStr) return "—";
  const [y, m, d] = isoStr.split("-");
  return `${+d} ${t("months")[+m]} ${+y + t("yearOffset")}`;
}

// Expose globals called from inline handlers
window.switchLang      = switchLang;
window.navigate        = navigate;
window.cycleDay        = cycleDay;
window.shiftMonth      = shiftMonth;
window.shiftSummary    = shiftSummary;
window.shiftLeaves     = shiftLeaves;
window.shiftPayments   = shiftPayments;
window.confirmDelete   = confirmDelete;
window.editLeaveNote   = editLeaveNote;
window.togglePayment   = togglePayment;
window.confirmResign   = confirmResign;
window.cancelResign    = cancelResign;
window.toggleReminder  = toggleReminder;
window.testReminder    = testReminder;
window.deleteReminder  = deleteReminder;
window.editReminder    = editReminder;

// ─── Boot ────────────────────────────────────────────────────
document.title = t("appTitle");
document.getElementById("langToggle").textContent = t("langBtn");
render();
