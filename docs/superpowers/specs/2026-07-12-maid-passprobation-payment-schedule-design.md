# maid-tracker — Pass-probation month-boundary + payment schedule + payer "both"

Date: 2026-07-12

## Problem

1. **Pass-probation mid-month.** Currently pressing "ผ่านโปร" on `pass_date` splits the
   month: days `< pass_date` are daily, days `>= pass_date` are prorated monthly. Owner
   wants the whole pass-month to stay daily (same amounts as probation), and the monthly
   lump to start on the 1st of the *next* month.
2. **Payment schedule.** Monthly salary is always split into 2 rounds (15th + end). Owner
   wants a per-maid choice: 2 rounds, or 1 round (whole salary at end of month).
3. **Payer "both".** `paid_by` offers ฟิก / ปุ๊ก. Owner wants a "ฟิก + ปุ๊ก" option for a
   single lump paid by both.

## Design

### Req 1 — pass-probation = daily all month, monthly from next month

**Rule:** press "ผ่านโปร" any day mid-month → daily pay continues (same rate) through the
end of that month → full monthly lump starts on the 1st of the next month, automatically.
If `pass_date` is already the 1st, the monthly starts that same month (full month).

**Mechanism (reuses the existing daily-boundary machinery — the 15 `employment_status ==
'probation'` branches stay UNTOUCHED):**

- `pass_probation` endpoint sets `monthly_start_date = pass_date` if `pass_date.day == 1`,
  else the **1st of the following month**. It **keeps `employment_status = 'probation'`**
  during the tail (does not flip to active). Because status is genuinely still probation:
  - `get_payments` early-returns `[]` (no monthly periods this month).
  - `get_daily_payments` caps `work_date < monthly_start_date` → tail days are payable daily.
  - All summary/overall/resign/webhook/report probation branches keep daily framing.
  - The probation-branch math uses `start_date`/month-start, NOT `monthly_start_date` as
    anchor, so setting `monthly_start_date` during the tail is safe.
- **`promote()`** — flips `probation → active` where
  `employment_status='probation' AND monthly_start_date IS NOT NULL AND monthly_start_date <= today`.
  Called: (a) inline at the end of `pass_probation` (handles day-1 / backdated pass
  immediately), (b) on app startup in `lifespan` (heals a missed midnight), (c) a daily
  APScheduler job at 00:10. Idempotent. The `monthly_start_date IS NOT NULL` guard keeps
  not-yet-passed maids (NULL anchor) in probation.
- `undo_pass_probation` is unchanged (sets `probation` + `monthly_start_date=NULL`) — this
  cancels a pending promotion during the tail and reverts a completed one.

**`first_month_leave_days` removed.** Anchor is always a 1st now → the pass-month has no
monthly at all and the next month is full → the field can no longer prorate a partial first
month. Remove the pass-probation popup that asks for it. At pass time, set
`first_month_leave_days = monthly_leave_days` (so the transition-month = full-month credit
via the existing `compute_monthly_leave_balance` branch, no calc change needed). Keep the DB
column and the calc param (avoids a migration + signature churn); it just always equals a
full month for passed maids.

**Badge UX.** During the tail, stored status is still `probation`. Detail view: when
`employment_status == 'probation' AND monthly_start_date` is set, show
**"ผ่านโปรแล้ว — รายเดือนเริ่ม \<monthly_start_date\>"** instead of the "ทดลองงาน" badge.

### Req 2a — payment schedule (per maid)

New column `payment_schedule TEXT DEFAULT 'biweekly'` on `employees` (`'biweekly'` = 15th +
end, current behaviour; `'monthly'` = single lump at end of month).

`get_payments`: when `payment_schedule == 'monthly'`, emit **period 2 only**, amount = full
`base_salary` (prorated first month for directly-hired active maids still applies), no
period 1. Period-2 due date, leave deduction, slip, notify, toggle all work unchanged
(period 2 is already "สิ้นเดือน"). `biweekly` keeps the current two-period output.

Form: radio "รอบจ่ายเงินเดือน" (2 รอบ / รอบเดียวสิ้นเดือน) in create + edit. `EmployeeCreate`
/ update carry the field.

Note: `first_month_after_15` proration stays relevant for directly-hired active maids with a
mid-month `start_date`; passed maids never hit it (anchor always a 1st).

### Req 2b — payer "both"

Add `"ฟิก + ปุ๊ก"` to the `PAYERS` const in `static/app.js`. Label-only — stored verbatim in
`paid_by`, no amount split. One line.

## Files

- `main.py` — `pass_probation` (anchor = next-1st, keep probation, drop popup field, inline
  `promote()`), new `promote()` + daily job + lifespan call, `get_payments` (payment_schedule
  branch), `EmployeeCreate`/update + INSERT/UPDATE + migration `payment_schedule`, badge data
  (return `monthly_start_date` where detail reads it — already returned).
- `calc.py` — no change (first_month_leave_days branch already handles full-month credit).
- `static/app.js` — `PAYERS` add "ฟิก + ปุ๊ก"; remove first-month-leave prompt in
  `passProbation`; payment_schedule radio in form; badge "ผ่านโปรแล้ว — รายเดือนเริ่ม …".
- `tests/` — pass mid-month → tail daily + no monthly period this month + full monthly next
  month + promote() flips on/after anchor; payment_schedule='monthly' → single full period;
  composition (monthly-schedule maid passing probation mid-month).

## Out of scope

- Payer amount split (50/50 tracking) — label only unless asked.
- Any change to directly-hired active maids' proration.
