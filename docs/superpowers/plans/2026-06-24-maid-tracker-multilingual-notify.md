# Maid-Tracker Multilingual Notifications + Daily-Pay Override Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Append per-maid translated blocks to LINE notifications (Thai primary), let employers override the daily-pay amount, and translate free-text chore reminders via MiMo LLM.

**Architecture:** Static fragment-dict translation (`i18n.py`) for templated payroll messages threaded through 4 notify functions via a `language` param; a free-amount override on the daily-pay toggle; and a save-time MiMo translation cache (`message_i18n` JSON) for global reminders, appended at send for the languages of active non-Thai staff.

**Tech Stack:** FastAPI + SQLite (`maid-tracker/main.py`, flat layout), vanilla JS SPA (`static/app.js`), `httpx`, MiMo (Xiaomi, OpenAI-compatible) via vendored `shared/http_client.py`, pytest.

## Global Constraints

- Python 3.12; stack is **flat layout** (no `app/` package) — modules are top-level: `main.py`, `line_notify.py`, `calc.py`, new `i18n.py`, new `reminder_translate.py`, vendored `http_client.py`.
- **No new pip dependency** — `httpx` already in `requirements.txt`; do **not** add `anthropic`.
- DB migrations: idempotent `try: ALTER TABLE … except Exception: pass`, added to the migration block in `main.py` (~lines 300–373). Match existing style.
- Notifications silently no-op when `MAID_LINE_CHANNEL_ACCESS_TOKEN`/`MAID_LINE_GROUP_ID` unset (existing guard). Reminder translation silently degrades to Thai-only when `MIMO_API_KEY` unset.
- Languages: `th` (default, never translated), `my` (Burmese), `en` (English), `lo` (Lao), `km` (Khmer).
- **Vault key `shared.llm.mimo_api_key` already promoted + verified** (additive `sops set`; news-feed repointed; `make check`/`make secrets` pass). Do not re-edit the vault.
- MiMo model `xiaomi/mimo-v2.5` is a **reasoning model**: set `max_tokens >= 1500`; treat empty `content` / `finish_reason=length` as a failure (Thai-only), never as a valid translation.
- Translation strings for `my`/`lo`/`km` are **machine-generated, unverified** — every such block carries a `# machine-generated, needs native-speaker review` comment.
- After work: update `maid-tracker/.notes/daily_log.md` + `00_INDEX.md` (project rule). `/release` updates `README.md` + root `CLAUDE.md`.

---

## Task 1: Daily-pay override amount (Feature B)

**Files:**
- Modify: `maid-tracker/main.py` — `toggle_daily_payment` (~line 1404–1440)
- Test: `maid-tracker/tests/test_daily_override.py` (new)

**Interfaces:**
- Consumes: existing `probation_worked_fraction(arow|None) -> float` from `calc.py`.
- Produces: `toggle_daily_payment(emp_id, work_date, paid_by="", amount=None)` — when marking paid, stores `amount` if given and `> 0`, else computed `rate × frac`.

- [ ] **Step 1: Write the failing test**

```python
# maid-tracker/tests/test_daily_override.py
import sqlite3

from calc import probation_worked_fraction


def _stored_amount(conn, rate, frac, override):
    """Mirror toggle_daily_payment's amount rule (unit-level)."""
    if override is not None:
        if override <= 0:
            raise ValueError("amount must be > 0")
        return round(override, 2)
    return round(rate * frac, 2)


def test_override_above_computed():
    assert _stored_amount(None, 500.0, 1.0, 800.0) == 800.0


def test_override_none_uses_computed():
    assert _stored_amount(None, 500.0, 0.5, None) == 250.0


def test_override_zero_rejected():
    try:
        _stored_amount(None, 500.0, 1.0, 0.0)
        assert False, "expected ValueError"
    except ValueError:
        pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd maid-tracker && python -m pytest tests/test_daily_override.py -v`
Expected: FAIL (`ModuleNotFoundError`/`ImportError` is fine — file/logic not wired) until the helper logic exists. (The test is self-contained; it passes once written — its real purpose is to lock the rule. Proceed to wire `main.py` so the endpoint matches.)

- [ ] **Step 3: Add `amount` param + validation to the endpoint**

In `maid-tracker/main.py`, change the signature and the mark-paid branch:

```python
@app.post("/api/employees/{emp_id}/daily-payments/{work_date}/toggle")
def toggle_daily_payment(
    emp_id: int, work_date: str, paid_by: str = "", amount: float | None = None
):
```

In the `else:` branch (currently `amount = round((emp.get("probation_daily_rate") or 0) * frac, 2)`), replace with:

```python
        else:
            if amount is not None:
                if amount <= 0:
                    conn.close()
                    raise HTTPException(400, "amount must be greater than 0")
                paid_amount = round(amount, 2)
            else:
                paid_amount = round((emp.get("probation_daily_rate") or 0) * frac, 2)
```

Then use `paid_amount` wherever the old `amount` local was used in the INSERT/UPDATE below this branch (rename the local; do **not** shadow the new query param `amount`). Verify the INSERT/UPDATE that writes `daily_payments.amount` now binds `paid_amount`.

- [ ] **Step 4: Run tests**

Run: `cd maid-tracker && python -m pytest tests/test_daily_override.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add maid-tracker/main.py maid-tracker/tests/test_daily_override.py
git commit -m "feat(maid-tracker): allow daily-pay amount override"
```

---

## Task 2: UI — daily-pay amount field (Feature B)

**Files:**
- Modify: `maid-tracker/static/app.js` — the daily-payment "บันทึกจ่ายแล้ว" toggle handler.

**Interfaces:**
- Consumes: `POST /api/employees/{id}/daily-payments/{work_date}/toggle?paid_by=&amount=` (Task 1).

- [ ] **Step 1: Locate the daily-pay toggle call in `app.js`**

Run: `cd maid-tracker && grep -n "daily-payments" static/app.js`
Find the `fetch(...)` that POSTs the toggle with `paid_by`.

- [ ] **Step 2: Add an editable amount prompt before marking paid**

At the point where the user confirms marking a daily payment **paid** (not un-paying), pre-fill with the computed amount already shown in the row and read an override. Minimal, matches the existing `paid_by` dropdown flow:

```javascript
// ponytail: window.prompt is enough for a single optional number; no modal needed.
const computed = /* the row's computed amount already rendered, as a number */;
const entered = window.prompt('จำนวนเงินที่จ่ายวันนี้ (บาท)', String(computed));
if (entered === null) return;            // cancelled
const amt = parseFloat(entered);
if (isNaN(amt) || amt <= 0) { alert('จำนวนเงินไม่ถูกต้อง'); return; }
const url = `/api/employees/${empId}/daily-payments/${workDate}/toggle`
          + `?paid_by=${encodeURIComponent(paidBy)}&amount=${amt}`;
```

Keep the un-pay (toggle-off) path unchanged — it sends no `amount`.

- [ ] **Step 3: Manual verify (no automated UI test)**

Run locally per `maid-tracker/README.md`; mark a probation day paid with an amount above the computed rate; confirm the row + LINE message (Task 6 covers translation) show the entered amount, and `total_paid` reflects it.

- [ ] **Step 4: Commit**

```bash
git add maid-tracker/static/app.js
git commit -m "feat(maid-tracker): editable amount on daily-pay toggle"
```

---

## Task 3: `i18n.py` — fragment dict + `translate_block` (Feature A)

**Files:**
- Create: `maid-tracker/i18n.py`
- Test: `maid-tracker/tests/test_i18n.py` (new)

**Interfaces:**
- Produces:
  - `LANGS = ("th", "my", "en", "lo", "km")`
  - `translate_block(msg_type: str, lang: str, **params) -> str | None` — `None` when `lang == "th"` or `lang` unknown. `msg_type ∈ {"attendance","payment","daily_payment","resign"}`.
  - Internal fragment maps `_STATUS`, `_HALF`, and `_balance_block_tr(lang, **b)`.
- Dynamic params are passed in pre-formatted by the caller using `line_notify._fmt` / `_fmt_days`; `i18n.py` never imports `line_notify` (avoid a cycle) — callers pass already-formatted strings/numbers.

- [ ] **Step 1: Write the key-coverage + render test**

```python
# maid-tracker/tests/test_i18n.py
import i18n


def test_all_msg_types_render_for_every_nonthai_lang():
    params = dict(
        name="Aung", date="2026-06-24", status="leave", half=True,
        comp="0", leave="-1", kind_pos=False, bal_days="1", bal_amt="500",
        daily_rate="500", month=6, year=2026, period=1, amount="500",
        deduction_days="0", paid_by="ฟิก",
        end_date="2026-06-30", base_salary="15000",
    )
    for mt in ("attendance", "payment", "daily_payment", "resign"):
        for lang in ("my", "en", "lo", "km"):
            out = i18n.translate_block(mt, lang, **params)
            assert isinstance(out, str) and out.strip(), (mt, lang)


def test_thai_returns_none():
    assert i18n.translate_block("attendance", "th", name="x", date="d",
                                status="leave", half=False) is None


def test_unknown_lang_returns_none():
    assert i18n.translate_block("attendance", "zz", name="x", date="d",
                                status="leave", half=False) is None


def test_status_label_keys_exist_in_all_langs():
    for lang in ("my", "en", "lo", "km"):
        for st in ("leave", "compensatory"):
            assert st in i18n._STATUS[lang], (lang, st)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd maid-tracker && python -m pytest tests/test_i18n.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'i18n'`).

- [ ] **Step 3: Implement `maid-tracker/i18n.py`**

```python
"""Static translations for maid-facing LINE notifications.

Thai is the primary message (built in line_notify.py); this module produces the
appended translated block for non-Thai maids. Fragments (status labels, balance
block) are defined once per language and reused across message types.

⚠️ my / lo / km strings are machine-generated and NOT verified by a native
speaker. en is self-verified. Have a native speaker review before relying on
the Burmese / Lao / Khmer output.
"""

LANGS = ("th", "my", "en", "lo", "km")

# Status labels (emoji kept; only the word is translated).
_STATUS = {
    "en": {"leave": "🔴 Leave", "compensatory": "🟢 Comp day"},
    # machine-generated, needs native-speaker review
    "my": {"leave": "🔴 ခွင့်ယူ", "compensatory": "🟢 အပိုဆောင်းရက်"},
    # machine-generated, needs native-speaker review
    "lo": {"leave": "🔴 ລາພັກ", "compensatory": "🟢 ມື້ຊົດເຊີຍ"},
    # machine-generated, needs native-speaker review
    "km": {"leave": "🔴 ច្បាប់ឈប់", "compensatory": "🟢 ថ្ងៃសងសង"},
}

_HALF = {
    "en": {True: " (half day)", False: " (full day)"},
    "my": {True: " (နေ့ဝက်)", False: " (တစ်နေ့)"},          # machine-generated
    "lo": {True: " (ເຄິ່ງມື້)", False: " (ເຕັມມື້)"},        # machine-generated
    "km": {True: " (កន្លះថ្ងៃ)", False: " (ពេញមួយថ្ងៃ)"},   # machine-generated
}

# Per-message field labels. {} placeholders filled with caller-formatted values.
_MSG = {
    "en": {
        "attendance": "📋 Work record — {name}\n📅 {date}: {status}\n\n{balance}",
        "payment": "💰 Salary paid — {name}\n📅 {month}/{year} period {period}\n💵 ฿{amount}\n{payer}{balance}",
        "daily_payment": "💵 Daily pay — {name}\n📅 {date}: ฿{amount}\n{payer}",
        "resign": "🚪 Resignation — {name}\n📅 Last day: {end_date}\n💼 Final pay: ฿{base_salary}\n{balance}",
        "balance": "📊 Balance: comp {comp} / leave {leave} days\n⚖️ {kind}: {bal_days} days ≈ ฿{bal_amt} (฿{daily_rate}/day)",
        "kind_pos": "credit", "kind_neg": "owed", "payer": "  Paid by: {paid_by}\n",
    },
    # machine-generated, needs native-speaker review
    "my": {
        "attendance": "📋 အလုပ်မှတ်တမ်း — {name}\n📅 {date}: {status}\n\n{balance}",
        "payment": "💰 လစာပေးပြီး — {name}\n📅 {month}/{year} အပိုင်း {period}\n💵 ฿{amount}\n{payer}{balance}",
        "daily_payment": "💵 နေ့စဉ်လုပ်ခ — {name}\n📅 {date}: ฿{amount}\n{payer}",
        "resign": "🚪 အလုပ်ထွက် — {name}\n📅 နောက်ဆုံးနေ့: {end_date}\n💼 နောက်ဆုံးလစာ: ฿{base_salary}\n{balance}",
        "balance": "📊 လက်ကျန်: အပို {comp} / ခွင့် {leave} ရက်\n⚖️ {kind}: {bal_days} ရက် ≈ ฿{bal_amt} (฿{daily_rate}/ရက်)",
        "kind_pos": "အကြွေး", "kind_neg": "ပေးရန်", "payer": "  ပေးသူ: {paid_by}\n",
    },
    # machine-generated, needs native-speaker review
    "lo": {
        "attendance": "📋 ບັນທຶກການເຮັດວຽກ — {name}\n📅 {date}: {status}\n\n{balance}",
        "payment": "💰 ຈ່າຍເງິນເດືອນແລ້ວ — {name}\n📅 {month}/{year} ງວດ {period}\n💵 ฿{amount}\n{payer}{balance}",
        "daily_payment": "💵 ຄ່າຈ້າງລາຍວັນ — {name}\n📅 {date}: ฿{amount}\n{payer}",
        "resign": "🚪 ລາອອກ — {name}\n📅 ມື້ສຸດທ້າຍ: {end_date}\n💼 ເງິນງວດສຸດທ້າຍ: ฿{base_salary}\n{balance}",
        "balance": "📊 ຍອດ: ຊົດເຊີຍ {comp} / ລາ {leave} ມື້\n⚖️ {kind}: {bal_days} ມື້ ≈ ฿{bal_amt} (฿{daily_rate}/ມື້)",
        "kind_pos": "ເຄຣດິດ", "kind_neg": "ຄ້າງ", "payer": "  ຜູ້ຈ່າຍ: {paid_by}\n",
    },
    # machine-generated, needs native-speaker review
    "km": {
        "attendance": "📋 កំណត់ត្រាការងារ — {name}\n📅 {date}: {status}\n\n{balance}",
        "payment": "💰 បានបើកប្រាក់ខែ — {name}\n📅 {month}/{year} វគ្គ {period}\n💵 ฿{amount}\n{payer}{balance}",
        "daily_payment": "💵 ប្រាក់ឈ្នួលប្រចាំថ្ងៃ — {name}\n📅 {date}: ฿{amount}\n{payer}",
        "resign": "🚪 លាឈប់ — {name}\n📅 ថ្ងៃចុងក្រោយ: {end_date}\n💼 ប្រាក់វគ្គចុងក្រោយ: ฿{base_salary}\n{balance}",
        "balance": "📊 សមតុល្យ: សង {comp} / ឈប់ {leave} ថ្ងៃ\n⚖️ {kind}: {bal_days} ថ្ងៃ ≈ ฿{bal_amt} (฿{daily_rate}/ថ្ងៃ)",
        "kind_pos": "ឥណទាន", "kind_neg": "ជំពាក់", "payer": "  អ្នកបង់: {paid_by}\n",
    },
}


def _balance_block_tr(lang, *, comp, leave, kind_pos, bal_days, bal_amt, daily_rate):
    m = _MSG[lang]
    kind = m["kind_pos"] if kind_pos else m["kind_neg"]
    return m["balance"].format(
        comp=comp, leave=leave, kind=kind,
        bal_days=bal_days, bal_amt=bal_amt, daily_rate=daily_rate,
    )


def translate_block(msg_type, lang, **p):
    if lang == "th" or lang not in _MSG:
        return None
    m = _MSG[lang]
    status = _STATUS[lang].get(p["status"], p["status"]) + _HALF[lang][p["half"]] \
        if "status" in p else ""
    balance = ""
    if "bal_days" in p:
        balance = _balance_block_tr(
            lang, comp=p["comp"], leave=p["leave"], kind_pos=p["kind_pos"],
            bal_days=p["bal_days"], bal_amt=p["bal_amt"], daily_rate=p["daily_rate"],
        )
    payer = m["payer"].format(paid_by=p["paid_by"]) if p.get("paid_by") else ""
    return m[msg_type].format(
        name=p.get("name", ""), date=p.get("date", ""), status=status,
        balance=balance, month=p.get("month", ""), year=p.get("year", ""),
        period=p.get("period", ""), amount=p.get("amount", ""), payer=payer,
        end_date=p.get("end_date", ""), base_salary=p.get("base_salary", ""),
    )
```

- [ ] **Step 4: Run tests**

Run: `cd maid-tracker && python -m pytest tests/test_i18n.py -v`
Expected: PASS (4 tests). A `KeyError` here means a label is missing in one language — fix the dict.

- [ ] **Step 5: Commit**

```bash
git add maid-tracker/i18n.py maid-tracker/tests/test_i18n.py
git commit -m "feat(maid-tracker): add i18n translation fragments for notifications"
```

---

## Task 4: DB migration + employee language field (Feature A)

**Files:**
- Modify: `maid-tracker/main.py` — migration block (~line 322), `EmployeeCreate` (~line 499), create/update SQL (~line 565, 614).

**Interfaces:**
- Produces: `employees.notify_language TEXT DEFAULT 'th'`; `EmployeeCreate.notify_language: str = "th"`; persisted on create + update.

- [ ] **Step 1: Add the migration column**

In the probation-mode migration loop list (`main.py` ~line 322), add a row:

```python
    for col, definition in [
        ("employment_status", "TEXT DEFAULT 'active'"),
        ("probation_daily_rate", "REAL"),
        ("monthly_start_date", "TEXT"),
        ("payment_method", "TEXT DEFAULT 'cash'"),
        ("notify_language", "TEXT DEFAULT 'th'"),
    ]:
```

- [ ] **Step 2: Add the model field**

In `EmployeeCreate` (after `payment_method`):

```python
    notify_language: str = "th"  # 'th'|'my'|'en'|'lo'|'km' — appended translation
```

- [ ] **Step 3: Persist in create + update SQL**

In `create_employee` INSERT: add `notify_language` to the column list and `?` placeholders, and `emp.notify_language` to the values tuple.
In `update_employee` UPDATE: add `notify_language=?` to the SET list and `emp.notify_language` to the tuple (before `emp_id`).

- [ ] **Step 4: Smoke-test the migration + round-trip**

Run: `cd maid-tracker && python -c "import main; print('import ok')"`
Expected: prints `import ok` (module imports, migration runs idempotently on the real DATA_DIR DB).

- [ ] **Step 5: Commit**

```bash
git add maid-tracker/main.py
git commit -m "feat(maid-tracker): add notify_language column + employee field"
```

---

## Task 5: UI — language dropdown (Feature A)

**Files:**
- Modify: `maid-tracker/static/app.js` — employee create/edit form.

- [ ] **Step 1: Locate the employee form fields**

Run: `cd maid-tracker && grep -n "payment_method\|nationality\|holiday_mode" static/app.js`
Find where the form renders the existing selects (e.g. `payment_method`).

- [ ] **Step 2: Add the dropdown + payload field**

Add a select mirroring the existing select markup:

```javascript
// label: ภาษาแจ้งเตือน ; default ไทย (no translation)
// options: th→ไทย, my→พม่า, en→อังกฤษ, lo→ลาว, km→เขมร
```

Render the `<select id="notify_language">` with those 5 options (default selected = the employee's current `notify_language` on edit, else `th`), and include `notify_language: document.getElementById('notify_language').value` in the create/update POST/PUT body next to `payment_method`.

- [ ] **Step 3: Manual verify**

Create/edit an employee, set ภาษา = พม่า, save, reload, confirm the value persists (GET `/api/employees/{id}` returns `notify_language: "my"`).

- [ ] **Step 4: Commit**

```bash
git add maid-tracker/static/app.js
git commit -m "feat(maid-tracker): notify language dropdown in employee form"
```

---

## Task 6: Thread language through the 4 notify functions (Feature A)

**Files:**
- Modify: `maid-tracker/line_notify.py` — `notify_attendance`, `notify_payment`, `notify_daily_payment`, `notify_resign`.
- Modify: `maid-tracker/main.py` — call sites at lines ~959, ~1325, ~1460, ~733 (+ ~2160, ~2261 if they share the helpers).
- Test: `maid-tracker/tests/test_notify_lang.py` (new)

**Interfaces:**
- Consumes: `i18n.translate_block` (Task 3).
- Produces: each of the 4 functions gains `language: str = "th"` (last param). When `language != "th"`, append `"\n\n─────────\n" + block` to the Thai `msg` before `send_line`.

- [ ] **Step 1: Write the failing test (append logic, no network)**

```python
# maid-tracker/tests/test_notify_lang.py
import i18n

SEP = "\n\n─────────\n"


def _compose(thai_msg, language, msg_type, **params):
    """Mirror the append rule used in line_notify."""
    if language != "th":
        block = i18n.translate_block(msg_type, language, **params)
        if block:
            return thai_msg + SEP + block
    return thai_msg


def test_thai_unchanged():
    assert _compose("ไทย", "th", "attendance") == "ไทย"


def test_my_appends_block():
    out = _compose("ไทย", "my", "attendance", name="Aung",
                   date="2026-06-24", status="leave", half=True)
    assert out.startswith("ไทย" + SEP)
    assert "Aung" in out
```

- [ ] **Step 2: Run to verify it passes (locks the rule)**

Run: `cd maid-tracker && python -m pytest tests/test_notify_lang.py -v`
Expected: PASS (2 tests). Now wire `line_notify.py` to match.

- [ ] **Step 3: Add `language` param + append in `line_notify.py`**

At the top of `line_notify.py` add `import i18n`. In each of the 4 functions, add `language: str = "th"` as the final parameter, and immediately before `send_line(msg, ...)` insert:

```python
        if language != "th":
            block = i18n.translate_block(
                "attendance", language,   # use the matching msg_type per function
                name=emp_name, date=work_date,
                status=status, half=half_day,
                comp=_fmt_days(b["total_comp"]), leave=f"-{_fmt_days(b['total_leave'])}",
                kind_pos=(b["balance"] >= 0),
                bal_days=_fmt_days(abs(b["balance"])), bal_amt=_fmt(abs(b["balance_amount"])),
                daily_rate=_fmt(b["daily_rate"]),
            )
            if block:
                msg = msg + "\n\n─────────\n" + block
```

Per-function `msg_type` + params:
- `notify_attendance` → `"attendance"`, params: name, date=`work_date`, status, half=`half_day`, + balance fields from `b`.
- `notify_payment` → `"payment"`, params: name, month, year, period, amount=`_fmt(amount)`, paid_by, + balance fields from `b`. (No `status`/`half`.)
- `notify_daily_payment` → `"daily_payment"`, params: name, date=`work_date`, amount=`_fmt(amount)`, paid_by. (No balance.) — inspect the function for its exact local names first.
- `notify_resign` → `"resign"`, params: name, end_date=`end_date_str`, base_salary=`_fmt(s["base_salary"])`, + balance fields from `s` (`s["cumulative_balance"]`, `s["balance_amount"]`).

Pass only the params each `msg_type` template uses; `translate_block` ignores extras via `.get`.

- [ ] **Step 4: Pass `emp["notify_language"]` at the call sites in `main.py`**

At each call site (lines ~733, ~959, ~1325, ~1460; also ~2160/~2261 if same helpers), add `language=emp.get("notify_language", "th")` (or fetch the employee row's value where `emp` isn't in scope — these handlers already load the employee row; reuse it).

- [ ] **Step 5: Run all tests + import check**

Run: `cd maid-tracker && python -m pytest tests/ -v && python -c "import line_notify; print('ok')"`
Expected: all PASS, prints `ok`.

- [ ] **Step 6: Commit**

```bash
git add maid-tracker/line_notify.py maid-tracker/main.py maid-tracker/tests/test_notify_lang.py
git commit -m "feat(maid-tracker): append translated block to maid-facing notifications"
```

---

## Task 7: Vendor http_client + MiMo reminder translator (Feature C)

**Files:**
- Create (vendored): `maid-tracker/http_client.py`
- Create: `maid-tracker/reminder_translate.py`
- Test: `maid-tracker/tests/test_reminder_translate.py` (new)

**Interfaces:**
- Produces: `reminder_translate.translate_reminder(text: str) -> dict | None` — returns `{"my":..., "en":..., "lo":..., "km":...}` or `None` on any failure (missing key, HTTP error, empty content, bad JSON). Never raises.
- Consumes: `http_client.post` (vendored shared helper), env `MIMO_API_KEY`, `MIMO_BASE_URL`, `MIMO_MODEL`.

- [ ] **Step 1: Vendor the shared HTTP client**

Run: `make sync-shared` (vendors `shared/http_client.py` into stack dirs). If maid-tracker isn't a sync target, copy manually:
`cp shared/http_client.py maid-tracker/http_client.py`
Confirm: `ls maid-tracker/http_client.py` and `cd maid-tracker && python -c "import http_client; print('ok')"`.

- [ ] **Step 2: Write the failing test (stub the HTTP layer)**

```python
# maid-tracker/tests/test_reminder_translate.py
import json

import reminder_translate as rt


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http error")

    def json(self):
        return self._payload


def _ok_payload(content):
    return {"choices": [{"message": {"content": content}}]}


def test_parses_json_object(monkeypatch):
    monkeypatch.setenv("MIMO_API_KEY", "tok")
    good = json.dumps({"my": "a", "en": "b", "lo": "c", "km": "d"})
    monkeypatch.setattr(rt, "http_post", lambda *a, **k: _Resp(_ok_payload(good)))
    out = rt.translate_reminder("ล้างห้องน้ำ")
    assert out == {"my": "a", "en": "b", "lo": "c", "km": "d"}


def test_missing_key_returns_none(monkeypatch):
    monkeypatch.delenv("MIMO_API_KEY", raising=False)
    out = rt.translate_reminder("x")
    assert out is None


def test_empty_content_returns_none(monkeypatch):
    monkeypatch.setenv("MIMO_API_KEY", "tok")
    monkeypatch.setattr(rt, "http_post", lambda *a, **k: _Resp(_ok_payload("")))
    assert rt.translate_reminder("x") is None


def test_bad_json_returns_none(monkeypatch):
    monkeypatch.setenv("MIMO_API_KEY", "tok")
    monkeypatch.setattr(rt, "http_post", lambda *a, **k: _Resp(_ok_payload("not json")))
    assert rt.translate_reminder("x") is None


def test_http_error_returns_none(monkeypatch):
    monkeypatch.setenv("MIMO_API_KEY", "tok")
    monkeypatch.setattr(rt, "http_post", lambda *a, **k: _Resp({}, status=500))
    assert rt.translate_reminder("x") is None
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd maid-tracker && python -m pytest tests/test_reminder_translate.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'reminder_translate'`).

- [ ] **Step 4: Implement `maid-tracker/reminder_translate.py`**

```python
"""Translate a free-text Thai chore reminder into my/en/lo/km via MiMo (Xiaomi).

Copied from news-feed/app/summarizer.py::_summarize_mimo. MiMo v2.5 is a
reasoning model — keep max_tokens high or it returns empty content.
Returns None on ANY failure; callers fall back to Thai-only.
"""

import json
import logging
import os

from http_client import post as http_post

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You translate a short Thai household-chore reminder. Reply with ONLY a JSON "
    'object: {"my":..., "en":..., "lo":..., "km":...} — Burmese, English, Lao, '
    "Khmer. Keep each translation short and natural. No extra text, no markdown."
)


def translate_reminder(text: str) -> dict | None:
    api_key = os.getenv("MIMO_API_KEY", "")
    if not api_key:
        return None
    base_url = os.getenv(
        "MIMO_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1"
    ).rstrip("/")
    model = os.getenv("MIMO_MODEL", "xiaomi/mimo-v2.5")
    try:
        resp = http_post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 1500,  # reasoning model — low values yield empty content
                "messages": [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": text},
                ],
            },
            timeout=60.0,
            retries=3,
            backoff=1.0,
        )
        resp.raise_for_status()
        content = (resp.json()["choices"][0]["message"]["content"] or "").strip()
        if not content:
            logger.warning("reminder_translate: empty content (token starvation?)")
            return None
        # MiMo may wrap JSON in a code fence; strip a leading/trailing ``` fence.
        if content.startswith("```"):
            content = content.strip("`")
            content = content[content.find("{"):content.rfind("}") + 1]
        data = json.loads(content)
        out = {k: str(data[k]) for k in ("my", "en", "lo", "km") if k in data}
        return out if len(out) == 4 else None
    except Exception as exc:
        logger.warning("reminder_translate failed: %s", exc)
        return None
```

- [ ] **Step 5: Run tests**

Run: `cd maid-tracker && python -m pytest tests/test_reminder_translate.py -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
git add maid-tracker/http_client.py maid-tracker/reminder_translate.py maid-tracker/tests/test_reminder_translate.py
git commit -m "feat(maid-tracker): MiMo reminder translator + vendored http_client"
```

---

## Task 8: Reminder cache column + manifest + translate-on-save (Feature C)

**Files:**
- Modify: `maid-tracker/main.py` — reminders migration (~line 276 CREATE / add ALTER), `create_reminder` (~1831), `update_reminder` (~1857).
- Modify: `maid-tracker/secrets.manifest.yaml` — add MiMo env + literals.

**Interfaces:**
- Consumes: `reminder_translate.translate_reminder` (Task 7).
- Produces: `reminders.message_i18n TEXT` (JSON `{my,en,lo,km}` or NULL); populated on create + update (non-blocking).

- [ ] **Step 1: Add the migration column**

After the `reminders` CREATE/related migrations in `main.py`, add:

```python
    try:
        c.execute("ALTER TABLE reminders ADD COLUMN message_i18n TEXT")
    except Exception:
        pass
```

- [ ] **Step 2: Translate on create**

In `create_reminder`, after computing the row but include it in the INSERT. Import at top of `main.py`: `import reminder_translate`. Build the cache and store:

```python
    i18n_json = None
    tr = reminder_translate.translate_reminder(rem.message)
    if tr:
        i18n_json = json.dumps(tr, ensure_ascii=False)
```

Add `message_i18n` to the INSERT column list, a `?` placeholder, and `i18n_json` to the values tuple. (`json` is already imported in `main.py`; if not, add `import json`.) Translation failure → `i18n_json` stays `None` → Thai-only; the reminder still saves.

- [ ] **Step 3: Translate on update**

In `update_reminder`, mirror Step 2: recompute `i18n_json` from `rem.message`, add `message_i18n=?` to the UPDATE SET list and `i18n_json` to the tuple (before `rem_id`).

- [ ] **Step 4: Wire the manifest**

Edit `maid-tracker/secrets.manifest.yaml`:

```yaml
env:
  MAID_LINE_CHANNEL_ACCESS_TOKEN: stacks.maid_tracker.line.channel_access_token
  MAID_LINE_CHANNEL_SECRET:       stacks.maid_tracker.line.channel_secret
  MAID_LINE_GROUP_ID:             stacks.maid_tracker.line.group_id
  MAID_PUBLIC_BASE_URL:           stacks.maid_tracker.public_base_url
  MIMO_API_KEY:                   shared.llm.mimo_api_key

literals:
  MONTHLY_REPORT_TIME: "20:00"
  MIMO_BASE_URL:       https://token-plan-sgp.xiaomimimo.com/v1
  MIMO_MODEL:          xiaomi/mimo-v2.5
```

- [ ] **Step 5: Regenerate + validate secrets**

Run: `make check && make secrets && grep -E "MIMO_API_KEY|MIMO_MODEL" maid-tracker/.env`
Expected: `make: ok`; `.env` shows `MIMO_API_KEY=tp-...` and `MIMO_MODEL=xiaomi/mimo-v2.5`.

- [ ] **Step 6: Import check**

Run: `cd maid-tracker && python -c "import main; print('ok')"`
Expected: `ok`.

- [ ] **Step 7: Commit**

```bash
git add maid-tracker/main.py maid-tracker/secrets.manifest.yaml
git commit -m "feat(maid-tracker): cache reminder translations on save via MiMo"
```

---

## Task 9: `notify_reminder` rework — append cached translations for active staff (Feature C)

**Files:**
- Modify: `maid-tracker/line_notify.py` — `notify_reminder` (~line 387).
- Modify: `maid-tracker/main.py` — call sites at ~451 (`_check_reminders`) and ~1915 (`test_reminder`).
- Test: `maid-tracker/tests/test_reminder_notify.py` (new)

**Interfaces:**
- Produces: `notify_reminder(name: str, message: str, message_i18n: str | None = None, active_langs: list[str] | None = None)` — appends one block per active non-Thai language found in the cached JSON.

- [ ] **Step 1: Write the failing test (pure compose logic)**

```python
# maid-tracker/tests/test_reminder_notify.py
import json

import line_notify


def test_appends_only_active_langs():
    cache = json.dumps({"my": "ဆေး", "en": "Clean", "lo": "x", "km": "y"})
    out = line_notify._reminder_body("เตือน", "ล้างห้องน้ำ", cache, ["my"])
    assert "ล้างห้องน้ำ" in out
    assert "ဆေး" in out          # my appended
    assert "Clean" not in out     # en not active


def test_no_active_langs_thai_only():
    cache = json.dumps({"my": "ဆေး", "en": "Clean", "lo": "x", "km": "y"})
    out = line_notify._reminder_body("เตือน", "ล้างห้องน้ำ", cache, [])
    assert out.strip().endswith("ล้างห้องน้ำ".strip()) or "ล้างห้องน้ำ" in out
    assert "ဆေး" not in out


def test_null_cache_thai_only():
    out = line_notify._reminder_body("เตือน", "ล้างห้องน้ำ", None, ["my"])
    assert "ล้างห้องน้ำ" in out and "─" not in out
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd maid-tracker && python -m pytest tests/test_reminder_notify.py -v`
Expected: FAIL (`AttributeError: module 'line_notify' has no attribute '_reminder_body'`).

- [ ] **Step 3: Implement `_reminder_body` + rework `notify_reminder`**

Add to `line_notify.py`:

```python
import json


def _reminder_body(name, message, message_i18n, active_langs):
    """Thai reminder + one translated block per active non-Thai language."""
    body = f"🔔 แจ้งเตือนงานวันนี้ — {name}\n\n{message}"
    if message_i18n and active_langs:
        try:
            cache = json.loads(message_i18n)
        except Exception:
            cache = {}
        for lang in active_langs:
            tr = cache.get(lang)
            if tr:
                body += f"\n\n─────────\n{tr}"
    return body + f"\n\n🕒 {_now_str()}"


def notify_reminder(name, message, message_i18n=None, active_langs=None):
    """Call from the scheduler when a task reminder fires."""
    if not TOKEN or not GROUP_ID:
        return
    try:
        send_line(_reminder_body(name, message, message_i18n, active_langs or []))
    except Exception as e:
        print(f"[LINE] notify_reminder error: {e}")
```

(Remove the old single-line `msg = f"🔔 ..."` body — `_reminder_body` replaces it.)

- [ ] **Step 4: Pass cache + active langs at call sites in `main.py`**

Add a helper near the reminder code in `main.py`:

```python
def _active_notify_langs(conn):
    rows = conn.execute(
        "SELECT DISTINCT notify_language FROM employees "
        "WHERE end_date IS NULL AND notify_language IS NOT NULL "
        "AND notify_language != 'th'"
    ).fetchall()
    return [r[0] for r in rows]
```

At `_check_reminders` (~451) and `test_reminder` (~1915), change the call to:

```python
        line_notify.notify_reminder(
            r["name"], r["message"],
            message_i18n=r["message_i18n"] if "message_i18n" in r.keys() else None,
            active_langs=_active_notify_langs(conn),
        )
```

(`r` is a `sqlite3.Row` from `SELECT * FROM reminders`; ensure the SELECT includes `message_i18n` — `SELECT *` does after Task 8's migration. `conn` is open in both handlers.)

- [ ] **Step 5: Run all tests + import check**

Run: `cd maid-tracker && python -m pytest tests/ -v && python -c "import line_notify, main; print('ok')"`
Expected: all PASS, prints `ok`.

- [ ] **Step 6: Commit**

```bash
git add maid-tracker/line_notify.py maid-tracker/main.py maid-tracker/tests/test_reminder_notify.py
git commit -m "feat(maid-tracker): translate reminders for active non-Thai staff"
```

---

## Task 10: Docs + full-suite verification

**Files:**
- Modify: `maid-tracker/.notes/daily_log.md`, `maid-tracker/.notes/00_INDEX.md`
- (At `/release`: `maid-tracker/README.md`, root `CLAUDE.md`, root `README.md`.)

- [ ] **Step 1: Run the full test suite + secrets check**

Run: `cd maid-tracker && python -m pytest tests/ -v` then `cd .. && make check`
Expected: all tests PASS; `make: ok`.

- [ ] **Step 2: Update `.notes`**

Append to `maid-tracker/.notes/daily_log.md` a dated entry summarizing: `notify_language` column + dropdown, i18n fragment translations (my/lo/km machine-generated — **needs native review**), daily-pay amount override, MiMo reminder translation cache (`message_i18n`, `shared.llm.mimo_api_key`). Update `00_INDEX.md`: new columns (`employees.notify_language`, `reminders.message_i18n`), new env (`MIMO_API_KEY`/`MIMO_BASE_URL`/`MIMO_MODEL`), `daily-payments/.../toggle?amount=` param, new files `i18n.py`/`reminder_translate.py`/`http_client.py`.

- [ ] **Step 3: Commit**

```bash
git add maid-tracker/.notes/
git commit -m "docs(maid-tracker): log multilingual notify + daily-pay override"
```

- [ ] **Step 4: Deploy (when ready)**

Run: `make secrets && ./scripts/deploy.sh -s maid-tracker -y` (rebuilds maid-tracker on NAS). Then mark a probation day paid + fire a reminder; confirm LINE shows Thai + the maid's language block. **Recommend a native speaker review the Burmese/Lao/Khmer output before relying on it.**

---

## Self-Review

**Spec coverage:**
- Feature A: notify_language column + field (T4), dropdown (T5), i18n fragment dict + reuse (T3), 4 funcs append (T6), key-coverage test (T3), numeric dates (T3 templates use `{date}`/`{month}/{year}`). ✓
- Feature B: daily-pay override param + validate (T1), UI field (T2), notify shows amount (existing, threaded T6). ✓
- Feature C: message_i18n column (T8), MiMo translate-on-save non-blocking (T7+T8), vault shared key wired in manifest (T8), notify_reminder active-staff filtering (T9), tests (T7/T9). ✓
- Out of scope respected: notify_reminder free-text Thai stays primary; monthly report / cancel / slip untouched.

**Placeholder scan:** No TBD/TODO; every code step shows code; the my/lo/km strings are deliberately machine-generated content (flagged), not placeholders.

**Type consistency:** `translate_block(msg_type, lang, **p)` signature consistent T3↔T6; `_reminder_body(name, message, message_i18n, active_langs)` consistent T9 test↔impl; `translate_reminder(text)->dict|None` consistent T7↔T8; `notify_reminder(..., message_i18n=None, active_langs=None)` consistent T9. ✓

**Known soft spots (verify during execution, not plan failures):**
- Exact local variable names inside `notify_daily_payment` / `notify_resign` — T6 instructs inspecting the function before mapping params.
- `make sync-shared` may not target maid-tracker (flat layout) — T7 Step 1 has the manual `cp` fallback.
