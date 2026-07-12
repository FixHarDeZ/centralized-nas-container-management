# maid-tracker pass-probation month-boundary + payment schedule Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pass-probation mid-month keeps daily pay through month-end and starts the monthly lump on the 1st of the next month; add a per-maid 2-round/1-round payment schedule; add a "ฟิก + ปุ๊ก" payer option.

**Architecture:** Reuse the existing daily-boundary machinery — set `monthly_start_date` to the 1st of the month after `pass_date` and keep `employment_status='probation'` during the tail, so all 15 existing probation branches stay untouched. A small `_promote_pending()` flips `probation→active` once `monthly_start_date <= today` (called at pass time, on startup, and by a daily scheduler job). Payment schedule and payer are small additive changes.

**Tech Stack:** FastAPI + SQLite, APScheduler, vanilla JS SPA, pytest + FastAPI TestClient.

## Global Constraints

- Python 3.12, `python:3.12-slim` container. No new runtime dependencies.
- Tests run with `pytest tests/` from `maid-tracker/`. Endpoint tests use `TestClient(main.app)` with `importlib.reload(calc)` then `importlib.reload(main)` after setting `DATA_DIR` (see `tests/test_probation_views.py`).
- Never add a `Co-Authored-By: Claude` trailer to commits.
- Commit messages: conventional style, Thai or English body fine.
- `working_days_in_month(year, month)` = ALL calendar days (holidays paid). Full month always pays exactly `monthly_salary`.
- Frontend has no JS unit-test framework — verify JS with `node --check static/app.js`.

---

### Task 1: Payment schedule (per-maid 2-round vs 1-round)

**Files:**
- Modify: `maid-tracker/main.py` — migration loop (~327-333), `EmployeeCreate` (~544-562), `create_employee` INSERT (~611-633), `update_employee` UPDATE (~661-682), `get_payments` (~1156-1230)
- Test: `maid-tracker/tests/test_payment_schedule.py` (create)

**Interfaces:**
- Consumes: nothing new.
- Produces: `employees.payment_schedule TEXT DEFAULT 'biweekly'` (`'biweekly'` | `'monthly'`). `get_payments` returns a single period (period 2, full base salary) when `'monthly'`.

- [ ] **Step 1: Write the failing test**

Create `maid-tracker/tests/test_payment_schedule.py`:

```python
"""payment_schedule: 'monthly' → single full period 2; 'biweekly' → two periods."""

import importlib
import tempfile

import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DATA_DIR", tempfile.mkdtemp())
    import calc

    importlib.reload(calc)
    import main

    importlib.reload(main)
    from fastapi.testclient import TestClient

    return TestClient(main.app)


def _mk(client, schedule):
    r = client.post(
        "/api/employees",
        json={
            "name": "S",
            "start_date": "2025-02-01",  # fully-past full month, Feb 2025 = 28 days
            "monthly_salary": 15400,
            "holiday_mode": "sunday",
            "payment_schedule": schedule,
        },
    )
    return r.json()["id"]


def test_biweekly_two_periods(client):
    eid = _mk(client, "biweekly")
    p = client.get(f"/api/employees/{eid}/payments?year=2025&month=2").json()
    assert [x["period"] for x in p] == [1, 2]
    assert p[0]["amount"] == 7700.0  # half
    assert p[1]["amount"] == 7700.0  # base - half


def test_monthly_single_full_period(client):
    eid = _mk(client, "monthly")
    p = client.get(f"/api/employees/{eid}/payments?year=2025&month=2").json()
    assert [x["period"] for x in p] == [2]
    assert p[0]["amount"] == 15400.0  # full base salary, one lump


def test_schedule_defaults_biweekly(client):
    r = client.post(
        "/api/employees",
        json={"name": "D", "start_date": "2025-02-01", "monthly_salary": 15400},
    )
    eid = r.json()["id"]
    got = client.get(f"/api/employees/{eid}").json()
    assert got["payment_schedule"] == "biweekly"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd maid-tracker && pytest tests/test_payment_schedule.py -v`
Expected: FAIL — `payment_schedule` column/field missing (KeyError or single-period assertion fails).

- [ ] **Step 3: Add migration column**

In `main.py`, add to the probation-mode migration loop list (currently ends at `("notify_language", "TEXT DEFAULT 'th'")`):

```python
    for col, definition in [
        ("employment_status", "TEXT DEFAULT 'active'"),
        ("probation_daily_rate", "REAL"),
        ("monthly_start_date", "TEXT"),
        ("payment_method", "TEXT DEFAULT 'cash'"),
        ("notify_language", "TEXT DEFAULT 'th'"),
        ("payment_schedule", "TEXT DEFAULT 'biweekly'"),
    ]:
```

- [ ] **Step 4: Add field to `EmployeeCreate`**

After `notify_language: str = "th"  # ...` in `EmployeeCreate`:

```python
    payment_schedule: str = "biweekly"  # 'biweekly' (15th+end) | 'monthly' (single lump at end)
```

- [ ] **Step 5: Persist in create + update**

In `create_employee`, add `payment_schedule` to the column list, the `VALUES` placeholders, and the tuple:

```python
    c.execute(
        "INSERT INTO employees (name,age,birth_date,nationality,phone,line_id,facebook,start_date,monthly_salary,"
        "max_leave_carry,holiday_mode,monthly_leave_days,employment_status,probation_daily_rate,payment_method,notify_language,payment_schedule) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            emp.name,
            emp.age,
            emp.birth_date,
            emp.nationality,
            emp.phone,
            emp.line_id,
            emp.facebook,
            emp.start_date,
            emp.monthly_salary,
            emp.max_leave_carry,
            emp.holiday_mode,
            emp.monthly_leave_days,
            emp.employment_status,
            emp.probation_daily_rate,
            emp.payment_method,
            emp.notify_language,
            emp.payment_schedule,
        ),
    )
```

In `update_employee`, add `payment_schedule=?` to the SET clause and `emp.payment_schedule` to the tuple (before `emp_id`):

```python
    c.execute(
        "UPDATE employees SET name=?,age=?,birth_date=?,nationality=?,phone=?,line_id=?,facebook=?,start_date=?,monthly_salary=?,"
        "max_leave_carry=?,holiday_mode=?,monthly_leave_days=?,probation_daily_rate=?,payment_method=?,notify_language=?,payment_schedule=? WHERE id=?",
        (
            emp.name,
            emp.age,
            emp.birth_date,
            emp.nationality,
            emp.phone,
            emp.line_id,
            emp.facebook,
            emp.start_date,
            emp.monthly_salary,
            emp.max_leave_carry,
            emp.holiday_mode,
            emp.monthly_leave_days,
            emp.probation_daily_rate,
            emp.payment_method,
            emp.notify_language,
            emp.payment_schedule,
            emp_id,
        ),
    )
```

- [ ] **Step 6: Branch `get_payments` on schedule**

In `get_payments`, after `first_month_after_15` is computed and `period2_amount` is set, replace the `period2_amount` line and guard period 1. Current lines:

```python
    first_month_after_15 = (
        anchor.year == year and anchor.month == month and anchor > mid_day
    )
    period2_amount = base_salary if first_month_after_15 else base_salary - half_salary
```

becomes:

```python
    schedule = emp.get("payment_schedule") or "biweekly"
    first_month_after_15 = (
        anchor.year == year and anchor.month == month and anchor > mid_day
    )
    # 'monthly' schedule = one lump at end of month = full base salary (no period 1).
    if schedule == "monthly" or first_month_after_15:
        period2_amount = base_salary
    else:
        period2_amount = base_salary - half_salary
```

Then in the Period 1 block, add the schedule guard to its condition:

```python
    # Period 1 (15th) — skip for 'monthly' schedule, or if started after 15th / resigned before 15th
    if schedule == "biweekly" and anchor <= mid_day and (end_date is None or end_date >= mid_day):
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd maid-tracker && pytest tests/test_payment_schedule.py -v`
Expected: PASS (3 tests).

- [ ] **Step 8: Full suite + commit**

Run: `cd maid-tracker && pytest tests/ -q && python -m py_compile main.py`
Expected: all pass.

```bash
git add maid-tracker/main.py maid-tracker/tests/test_payment_schedule.py
git commit -m "feat(maid-tracker): per-maid payment schedule (2-round vs single lump)"
```

---

### Task 2: Pass-probation = daily all month, monthly from next month

**Files:**
- Modify: `maid-tracker/main.py` — `PassProbationRequest` (~691-693), `pass_probation` (~696-716), new `_promote_pending()` helper, `lifespan` scheduler block (~72-82)
- Test: `maid-tracker/tests/test_pass_probation_boundary.py` (create)

**Interfaces:**
- Consumes: `payment_schedule` handling from Task 1 (unaffected here).
- Produces: `_promote_pending()` — flips `employment_status` `probation→active` where `monthly_start_date IS NOT NULL AND monthly_start_date <= today`. `pass_probation` sets `monthly_start_date` = 1st-of-next-month (or `pass_date` if it is the 1st), keeps status `probation`, sets `first_month_leave_days = monthly_leave_days`, then calls `_promote_pending()`.

- [ ] **Step 1: Write the failing test**

Create `maid-tracker/tests/test_pass_probation_boundary.py`:

```python
"""Pass mid-month → daily continues through month-end, monthly starts next-month-1st."""

import importlib
import tempfile
from datetime import date

import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DATA_DIR", tempfile.mkdtemp())
    import calc

    importlib.reload(calc)
    import main

    importlib.reload(main)
    from fastapi.testclient import TestClient

    return TestClient(main.app), main


def _mk_prob(client, start="2025-02-01"):
    c, _ = client
    r = c.post(
        "/api/employees",
        json={
            "name": "P",
            "start_date": start,
            "monthly_salary": 15400,
            "employment_status": "probation",
            "probation_daily_rate": 500,
            "holiday_mode": "sunday",
            "monthly_leave_days": 2,
        },
    )
    return r.json()["id"]


def test_pass_midmonth_sets_next_month_anchor_keeps_probation(client):
    c, _ = client
    eid = _mk_prob(client)
    # backdated pass on 2025-02-10 (mid-month, in the past)
    c.post(f"/api/employees/{eid}/pass-probation", json={"pass_date": "2025-02-10"})
    emp = c.get(f"/api/employees/{eid}").json()
    # anchor moved to 1st of March (next month)
    assert emp["monthly_start_date"] == "2025-03-01"
    # promotion already ran (2025-03-01 <= today) → active
    assert emp["employment_status"] == "active"
    # first_month_leave_days set to full monthly_leave_days
    assert emp["first_month_leave_days"] == 2


def test_pass_month_has_no_monthly_period(client):
    c, _ = client
    eid = _mk_prob(client)
    c.post(f"/api/employees/{eid}/pass-probation", json={"pass_date": "2025-02-10"})
    # February (the pass month) has NO monthly periods — pay was daily all month
    p = c.get(f"/api/employees/{eid}/payments?year=2025&month=2").json()
    assert p == []


def test_next_month_full_salary(client):
    c, _ = client
    eid = _mk_prob(client)
    c.post(f"/api/employees/{eid}/pass-probation", json={"pass_date": "2025-02-10"})
    # March = first full monthly month
    p = c.get(f"/api/employees/{eid}/payments?year=2025&month=3").json()
    assert [x["period"] for x in p] == [1, 2]
    assert p[0]["amount"] + p[1]["amount"] == 15400.0


def test_daily_payable_through_pass_month_end(client):
    c, _ = client
    eid = _mk_prob(client)
    c.post(f"/api/employees/{eid}/pass-probation", json={"pass_date": "2025-02-10"})
    # daily-payments window caps at < monthly_start_date (2025-03-01) → includes 2025-02-28
    dp = c.get(f"/api/employees/{eid}/daily-payments?year=2025&month=2").json()
    dates = {d["work_date"] for d in dp}
    assert "2025-02-28" in dates
    assert "2025-02-15" in dates


def test_pass_on_first_of_month_starts_monthly_immediately(client):
    c, _ = client
    eid = _mk_prob(client)
    c.post(f"/api/employees/{eid}/pass-probation", json={"pass_date": "2025-02-01"})
    emp = c.get(f"/api/employees/{eid}").json()
    assert emp["monthly_start_date"] == "2025-02-01"
    assert emp["employment_status"] == "active"
    p = c.get(f"/api/employees/{eid}/payments?year=2025&month=2").json()
    assert [x["period"] for x in p] == [1, 2]


def test_promote_pending_leaves_unpassed_in_probation(client):
    c, main = client
    _mk_prob(client)  # never passed → monthly_start_date NULL
    main._promote_pending()  # must not sweep NULL-anchor maids
    emp = c.get("/api/employees").json()[0]
    assert emp["employment_status"] == "probation"


def test_undo_pass_reverts(client):
    c, _ = client
    eid = _mk_prob(client)
    c.post(f"/api/employees/{eid}/pass-probation", json={"pass_date": "2025-02-10"})
    c.delete(f"/api/employees/{eid}/pass-probation")
    emp = c.get(f"/api/employees/{eid}").json()
    assert emp["employment_status"] == "probation"
    assert emp["monthly_start_date"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd maid-tracker && pytest tests/test_pass_probation_boundary.py -v`
Expected: FAIL — anchor is `2025-02-10` (old behavior), `_promote_pending` undefined.

- [ ] **Step 3: Add `_promote_pending()` helper**

In `main.py`, add near the other module-level helpers (e.g. just above `lifespan`):

```python
def _promote_pending():
    """Flip probation→active once the scheduled monthly start date has arrived.
    A passed maid stays in probation (daily pay) through the tail of the pass month;
    this promotes them on/after their monthly_start_date (always a 1st).
    The NOT NULL guard keeps not-yet-passed maids (NULL anchor) in probation.
    """
    conn = get_db()
    conn.execute(
        "UPDATE employees SET employment_status='active' "
        "WHERE employment_status='probation' AND monthly_start_date IS NOT NULL "
        "AND monthly_start_date <= ?",
        (date.today().isoformat(),),
    )
    conn.commit()
    conn.close()
```

- [ ] **Step 4: Drop the dead field from `PassProbationRequest`**

Replace `PassProbationRequest`:

```python
class PassProbationRequest(BaseModel):
    pass_date: str  # YYYY-MM-DD
```

(The `first_month_leave_days` field is removed; extra keys from an old client are ignored by Pydantic.)

- [ ] **Step 5: Rewrite `pass_probation` for the month-boundary anchor**

Replace the body of `pass_probation` (keep the 404 / not-in-probation / pass_date-before-start guards):

```python
@app.post("/api/employees/{emp_id}/pass-probation")
def pass_probation(emp_id: int, req: PassProbationRequest):
    conn = get_db()
    emp = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
    if not emp:
        conn.close()
        raise HTTPException(404, "Employee not found")
    if emp["employment_status"] != "probation":
        conn.close()
        raise HTTPException(400, "Employee is not in probation")
    if req.pass_date < emp["start_date"]:
        conn.close()
        raise HTTPException(400, "pass_date before start_date")
    # Monthly pay starts on the 1st: the whole pass-month stays daily, the monthly
    # lump begins the 1st of the next month (or this month if passed on the 1st).
    pd = date.fromisoformat(req.pass_date)
    if pd.day == 1:
        anchor = pd
    elif pd.month == 12:
        anchor = date(pd.year + 1, 1, 1)
    else:
        anchor = date(pd.year, pd.month + 1, 1)
    # Transition month is now always a full month → credit full monthly_leave_days.
    conn.execute(
        "UPDATE employees SET monthly_start_date=?, first_month_leave_days=? WHERE id=?",
        (anchor.isoformat(), emp["monthly_leave_days"] or 0.0, emp_id),
    )
    conn.commit()
    conn.close()
    # Flip to active now if the anchor is already here (passed on the 1st / backdated).
    _promote_pending()
    return {"message": "passed", "monthly_start_date": anchor.isoformat()}
```

- [ ] **Step 6: Wire `_promote_pending` into startup + a daily job**

In `lifespan`, alongside the existing `_scheduler.add_job(...)` calls, add:

```python
    _promote_pending()  # heal any promotion missed while the app was down
    _scheduler.add_job(_promote_pending, CronTrigger(hour=0, minute=10), id="promote_probation")
```

(Place the `_promote_pending()` call before `_scheduler.start()`.)

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd maid-tracker && pytest tests/test_pass_probation_boundary.py -v`
Expected: PASS (7 tests).

- [ ] **Step 8: Full suite + commit**

Run: `cd maid-tracker && pytest tests/ -q && python -m py_compile main.py`
Expected: all pass. No existing test should break — `tests/test_probation.py` sets `monthly_start_date` directly against the (unchanged) calc layer, bypassing the endpoint whose anchor rule changed. If one does fail, that's a real regression to investigate, not a rubber-stamp update.

```bash
git add maid-tracker/main.py maid-tracker/tests/test_pass_probation_boundary.py
git commit -m "feat(maid-tracker): pass-probation keeps daily to month-end, monthly from next month"
```

---

### Task 3: Frontend — payer "both", schedule radio, remove leave prompt, passed badge

**Files:**
- Modify: `maid-tracker/static/app.js` — `PAYERS` (~449), employee form (~686 payment-method block), submit body builder (~869), `passProbation` (~2181), list badge (~585), detail badge (~1010) + pass button (~1025), i18n dicts (TH ~30-160, EN ~280-320)
- Test: `node --check static/app.js`

**Interfaces:**
- Consumes: backend `payment_schedule` field (Task 1), `monthly_start_date` on employee objects (already returned by `list_employees`/`get_employee`).
- Produces: form posts `payment_schedule`; pass-probation posts only `pass_date`.

- [ ] **Step 1: Add "ฟิก + ปุ๊ก" to `PAYERS`**

Line 449:

```javascript
const PAYERS = ["ฟิก", "ปุ๊ก", "ฟิก + ปุ๊ก"];
```

- [ ] **Step 2: Add i18n keys (TH + EN)**

In the TH dict add:

```javascript
    fieldPaymentSchedule: "รอบจ่ายเงินเดือน",
    scheduleBiweekly: "2 รอบ (วันที่ 15 + สิ้นเดือน)",
    scheduleMonthly: "รอบเดียว (สิ้นเดือน)",
    passedBadge: (d) => `ผ่านโปรแล้ว — รายเดือนเริ่ม ${d}`,
```

In the EN dict add:

```javascript
    fieldPaymentSchedule: "Payroll schedule",
    scheduleBiweekly: "2 rounds (15th + end)",
    scheduleMonthly: "Single round (end of month)",
    passedBadge: (d) => `Passed probation — monthly from ${d}`,
```

- [ ] **Step 3: Add the schedule radio to the form**

Immediately after the Payment-method `<div class="col-6">…</div>` block (~686-692), insert:

```javascript
            <!-- Payment schedule -->
            <div class="col-6">
              <label class="form-label fw-semibold">${t("fieldPaymentSchedule")}</label>
              <select class="form-select" name="payment_schedule">
                <option value="biweekly" ${(emp?.payment_schedule || "biweekly") === "biweekly" ? "selected" : ""}>${t("scheduleBiweekly")}</option>
                <option value="monthly" ${emp?.payment_schedule === "monthly" ? "selected" : ""}>${t("scheduleMonthly")}</option>
              </select>
            </div>
```

- [ ] **Step 4: Post `payment_schedule` in the submit body**

In the submit handler `body` object (~869), after `payment_method:` line add:

```javascript
      payment_schedule:   fd.get("payment_schedule") || "biweekly",
```

- [ ] **Step 5: Remove the first-month-leave prompt from `passProbation`**

Replace `passProbation` body so it no longer prompts for or sends `first_month_leave_days`:

```javascript
async function passProbation(id, name) {
  const today = new Date().toISOString().split("T")[0];
  const dateStr = prompt(t("passProbationPrompt", name), today);
  if (!dateStr) return;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(dateStr)) {
    alert(t("confirmResignInvalid"));
    return;
  }
  if (!confirm(t("passProbationConfirm", name, formatDate(dateStr)))) return;
  try {
    await api.post(`/api/employees/${id}/pass-probation`, { pass_date: dateStr });
    await render();
  } catch (e) {
    alert(t("errSave") + e.message);
  }
}
```

(Optional cleanup: the now-unused `firstMonthLeavePrompt` i18n keys may be left in place or removed; leaving them is harmless.)

- [ ] **Step 6: Passed badge in the employee list (~585)**

Replace the list-card badge expression:

```javascript
                  ${e.employment_status === "probation"
                    ? (e.monthly_start_date
                        ? `<span class="badge ms-1" style="font-size:0.62rem;background:#dcfce7;color:#15803d">${t("passedBadge", formatDate(e.monthly_start_date))}</span>`
                        : `<span class="badge ms-1" style="font-size:0.62rem;background:#fef3c7;color:#b45309">${t("probationBadge")}</span>`)
                    : ""}
```

- [ ] **Step 7: Passed badge + hide pass button in detail (~1010, ~1025)**

Replace the detail badge (~1010):

```javascript
              ${emp.employment_status === "probation"
                ? (emp.monthly_start_date
                    ? `<span class="badge ms-2" style="font-size:.65rem;background:#dcfce7;color:#15803d;border-radius:6px"><i class="bi bi-check-circle me-1"></i>${t("passedBadge", formatDate(emp.monthly_start_date))}</span>`
                    : `<span class="badge ms-2" style="font-size:.65rem;background:#fef3c7;color:#b45309;border-radius:6px"><i class="bi bi-hourglass-split me-1"></i>${t("probationBadge")}</span>`)
                : ""}
```

Guard the "ผ่านโปร" button (~1024-1025) so it hides once a promotion is pending. The button currently renders when `emp.employment_status === "probation"`; change that condition to also require no anchor yet:

```javascript
              ${emp.employment_status === "probation" && !emp.monthly_start_date
```

(Apply to the `? \`<button ...passProbation...>\`` conditional that starts at ~1024. If the button is one arm of a larger ternary, add `&& !emp.monthly_start_date` to its guard only.)

- [ ] **Step 8: Verify JS parses**

Run: `cd maid-tracker && node --check static/app.js`
Expected: no output (exit 0).

- [ ] **Step 9: Commit**

```bash
git add maid-tracker/static/app.js
git commit -m "feat(maid-tracker): schedule radio, payer both, passed badge, drop leave prompt"
```

---

### Task 4: Cache-bust + docs

**Files:**
- Modify: `maid-tracker/static/index.html` (cache-bust `?v=` on `app.js`)
- Modify: `maid-tracker/.notes/00_INDEX.md`, `maid-tracker/.notes/daily_log.md`
- Modify: `maid-tracker/README.md`, root `CLAUDE.md` (stack row) — per `/release` rule

- [ ] **Step 1: Bump the app.js cache-bust query**

In `static/index.html`, update the `app.js` script tag `?v=` param to today's date (e.g. `?v=20260712`).

- [ ] **Step 2: Update `.notes/00_INDEX.md`**

In the DB-schema block: add `payment_schedule TEXT DEFAULT 'biweekly'` to `employees`. In "Logic การคำนวณ": document the new pass-probation rule (daily through pass-month, monthly anchor = 1st of next month, `_promote_pending` job) and the `payment_schedule` behavior. Add `promote_probation` to the Scheduled Jobs table (daily 00:10). Note `first_month_leave_days` is now always = monthly_leave_days for passed maids.

- [ ] **Step 3: Append a `daily_log.md` entry**

Add a dated `## 2026-07-12 —` entry summarizing the three changes, files touched, and test counts.

- [ ] **Step 4: Update `README.md` + root `CLAUDE.md`**

In root `CLAUDE.md` `maid-tracker/` row: note per-maid payment schedule (2-round/1-round), "ฟิก + ปุ๊ก" payer, and the revised pass-probation month-boundary rule. Mirror in `maid-tracker/README.md`.

- [ ] **Step 5: Full suite + commit (atomic with any remaining code)**

Run: `cd maid-tracker && pytest tests/ -q`
Expected: all pass.

```bash
git add maid-tracker/static/index.html maid-tracker/.notes maid-tracker/README.md CLAUDE.md
git commit -m "docs(maid-tracker): payment schedule + pass-probation boundary + payer both"
```

---

## Self-Review

**Spec coverage:**
- Req 1 (daily through pass-month, monthly next month) → Task 2. `first_month_leave_days` removal → Task 2 step 4/5 + Task 3 step 5. Badge UX → Task 3 steps 6-7.
- Req 2a (payment schedule) → Task 1 + Task 3 steps 2-4.
- Req 2b (payer "both") → Task 3 step 1.
- Docs/`/release` → Task 4.

**Placeholder scan:** No TBD/TODO; every code step shows full code. Task 3 step 7 references the exact detail-button condition — verify the surrounding ternary shape when editing (only note left, code guard explicit).

**Type consistency:** `payment_schedule` values `'biweekly'|'monthly'` consistent across migration, model, `get_payments`, and JS. `_promote_pending()` name consistent in helper def, lifespan, daily job, and Task 2 test. `monthly_start_date` used identically in backend anchor + JS badge/button guards.
