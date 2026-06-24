# Maid-Tracker Multilingual Notifications + Daily-Pay Override — Design

**Date:** 2026-06-24
**Stack:** `maid-tracker/`
**Status:** Design — awaiting user review

## Problem

LINE notifications are Thai-only. Non-Thai maids (Burmese / Lao / Khmer / English
speakers) can't read them. Owner wants the Thai message to stay primary, with a
translation appended below so the maid understands. Separately, daily-pay (probation)
should allow the employer to pay **more** than the computed amount on a given day.

Three features, one stack, one session — bundled because Feature B and C both touch
notification paths that Feature A also modifies.

---

## Feature A — Multilingual payroll notifications (static templates)

**Languages:** `th` (default, no translation), `my` (Burmese), `en` (English),
`lo` (Lao), `km` (Khmer).

**Flow:** Thai message stays primary on top. If the maid's language ≠ `th`, append a
translated block below in the **same** LINE text message (keeps them paired, doesn't
touch the `messages[:5]` cap in `send_line`).

```
📋 บันทึกการทำงาน — Aung
📅 2026-06-24:  🔴 ลา (เต็มวัน)
📊 ยอดสะสม...
🕒 ...
─────────
📋 Work record — Aung
📅 2026-06-24:  🔴 Leave (full day)
📊 Balance...
```

### Components

1. **DB** — add column to `employees`:
   `notify_language TEXT DEFAULT 'th'` (values `th|my|en|lo|km`). Idempotent
   `ALTER TABLE ADD COLUMN` migration, matching existing migration style in `main.py`
   (the `("col","TYPE")` migration list).

2. **UI** (`static/app.js`) — dropdown in the employee create/edit form,
   label "ภาษาแจ้งเตือน", options ไทย/พม่า/อังกฤษ/ลาว/เขมร. Default ไทย → no translation.
   Wire into the existing create/update payload + `EmployeeIn` model in `main.py`.

3. **New `maid-tracker/i18n.py`** — a **fragment dict**, NOT one full template per
   message. Shared sub-blocks (status labels ลา/ชดเชย, the `_balance_block`, period
   label) are translated **once** and reused across message types. Public API:
   `translate_block(msg_type: str, lang: str, **params) -> str | None` — returns
   `None` for `th`. Dynamic values (฿ amounts, day counts, dates, name) are passed in
   verbatim and formatted with the existing `_fmt` / `_fmt_days` helpers.
   **Month/date kept numeric** (`06/2026`, `2026-06-24`) — skip translating 12 Thai
   month names × 4 languages.

   ⚠️ **Translation strings are machine-generated and frozen.** English is
   self-verifiable; Burmese / Lao / Khmer are generated and **cannot be proofread** by
   author or owner. Each non-English block carries a `# machine-generated, needs
   native-speaker review` comment. Recommend a native speaker eyeballs them before the
   owner relies on them.

4. **`line_notify.py`** — these 4 maid-facing functions gain a `language: str = "th"`
   parameter. After building the Thai `msg`, if `language != "th"`, append
   `"\n\n─────────\n" + translate_block(...)`:
   - `notify_attendance` (leave/comp recorded)
   - `notify_payment` (monthly period paid)
   - `notify_daily_payment` (probation daily pay)
   - `notify_resign` (resignation settlement)

   Out of scope (owner confirmed): `notify_reminder` (free-text → Feature C),
   monthly report, cancel notifications, slip-image. Free-text fields inside in-scope
   messages (`resign_note`) stay Thai — only fixed labels translate.

5. **`main.py`** — pass `emp["notify_language"]` into those 4 notify calls at their
   call sites.

6. **Test** (`tests/`) — assert every label key used by `translate_block` exists in all
   5 languages (catches a missing key → silent Thai-leak / `KeyError` before ship).

---

## Feature B — Daily-pay override amount

Employer can pay more than the computed `rate × frac` on a probation day.

- `toggle_daily_payment` (`main.py:1404`) gains an optional `amount: float | None = None`
  query param. When **marking paid**: `amount is None` → compute `rate × frac`
  (current behavior); `amount` provided → validate `amount > 0` (reject ≤0 /
  non-numeric with `HTTPException(400)`) and store as-is. **No upper cap** — employer
  may overpay. Unmark path unchanged.
- **No migration** — `daily_payments.amount` already stores a per-day snapshot.
- **UI** (`app.js`) — the "บันทึกจ่ายแล้ว" action for a daily payment shows an editable
  amount field pre-filled with the computed value; the entered value is sent as
  `?amount=`.
- `total_paid` / summary auto-reflect (they already sum stored `amount`). Overpay →
  `total_paid > total_earned`, which is expected and correct.
- `notify_daily_payment` already displays the actual `amount`, so it shows the override
  + its translated block (Feature A).

ponytail: no bonus column, no computed-vs-paid display — one editable field covers
"pay what the employer wants."

---

## Feature C — Reminder translation (LLM at save-time, cached)

Reminders (`reminders.message`) are **free-text Thai** typed by the owner — static
templates can't translate arbitrary text, and the owner can't type Burmese/Khmer
script. So: translate once with an LLM at save-time, cache the result, append at send.

### Components

1. **DB** — add column to `reminders`:
   `message_i18n TEXT` (JSON cache, nullable). Same idempotent migration style.

2. **Translate on save** — in the reminder create/update handler (`main.py`,
   `POST /api/reminders`), after writing the row, make **one** LLM call that returns
   all 4 translations as JSON, store in `message_i18n`. **Copy the news-feed pattern**
   (`news-feed/app/summarizer.py::_summarize_mimo`):
   - **Provider:** Xiaomi MiMo, OpenAI-compatible. POST `{MIMO_BASE_URL}/chat/completions`
     with `Authorization: Bearer {MIMO_API_KEY}`, via the shared `http_client.post`
     (httpx wrapper with retries) — **no `anthropic` SDK, no new requirement** (httpx
     already in `requirements.txt`).
   - **Model:** `xiaomi/mimo-v2.5` (literal `MIMO_MODEL`).
   - ⚠️ **MiMo v2.5 is a reasoning model** — it spends tokens in `reasoning_content`
     before emitting `content`. A low `max_tokens` returns `finish_reason=length` with
     **empty `content`** (news-feed hit this at 300). Set `max_tokens` ≥ 1500 and treat
     empty `content` as a failure (fall through to Thai-only), not a valid translation.
   - **Output shape:** system prompt asks for a single JSON object
     `{"my": "...", "en": "...", "lo": "...", "km": "..."}` of the Thai chore reminder;
     `json.loads` the `content`. Guard parse failure → Thai-only.
   - **Non-blocking:** LLM error / empty content / bad JSON → log, save reminder anyway
     with `message_i18n = NULL` → Thai-only at send. Reminder save must never fail
     because translation failed.
   - Cache all 4 languages regardless of current staff, so send-time filtering is
     always covered.

3. **Vault secret — `shared.llm.mimo_api_key` (DONE).** The MiMo token was promoted to
   `shared.llm.mimo_api_key` in `secrets/vault.sops.yaml` (additive `sops set`), and
   news-feed's manifest repointed to it; `make check` + `make secrets` verified both
   render. maid-tracker's `secrets.manifest.yaml` adds
   `env: MIMO_API_KEY: shared.llm.mimo_api_key`, plus literals
   `MIMO_BASE_URL: https://token-plan-sgp.xiaomimimo.com/v1` and
   `MIMO_MODEL: xiaomi/mimo-v2.5` (mirroring news-feed's literals). Translation disabled
   (Thai-only) when `MIMO_API_KEY` is absent — same optional-degradation as the LINE
   token.
   - Pre-existing, **out of scope**: `shared.mimo.anthropic_api_key` (same token,
     consumed by `scripts/` as `ANTHROPIC_API_KEY` → MiMo's anthropic-compat endpoint)
     and the orphaned `stacks.news_feed.mimo.api_key` left after the repoint. Don't
     delete either in this change.

4. **Vendor `shared/http_client.py`** into maid-tracker (flat layout →
   `maid-tracker/http_client.py`) via `make sync-shared`. It is the hash-guarded shared
   helper; do not hand-edit the vendored copy.

5. **`notify_reminder`** — reminders are **global** (sent to the LINE group, not tied
   to one employee). At send time, query active non-Thai employees
   (`SELECT DISTINCT notify_language FROM employees WHERE end_date IS NULL AND
   notify_language != 'th'`), and for each such language append the cached translation
   from `message_i18n`. Usually 1 maid → 1 appended block. Deterministic at send
   (cached), no per-send LLM call. `notify_reminder` gains the reminder row (or its
   `message_i18n`) as input — update the scheduler call site in `main.py`.

6. **Test** — reminder-translation cache round-trips (save → JSON parses → send picks
   the active language); LLM-failure / empty-content / bad-JSON path saves Thai-only.

---

## Out of scope / confirmed

- Maid reads the LINE group herself — **confirmed by owner** (feature is moot otherwise).
- `resign_note` and reminder free-text beyond the cached translation stay Thai —
  **confirmed OK by owner**.
- No translation for monthly report, cancel notifications, slip-image captions.

## Files touched

- `maid-tracker/main.py` — 2 migrations, `EmployeeIn` field, daily-pay `amount` param,
  reminder save-time translate, notify call-site threading.
- `maid-tracker/line_notify.py` — `language` param on 4 funcs; `notify_reminder` rework.
- `maid-tracker/i18n.py` — **new**, fragment dict + `translate_block`.
- `maid-tracker/reminder_translate.py` (or inline in main.py) — **new**, MiMo call
  copied from `news-feed/app/summarizer.py::_summarize_mimo`.
- `maid-tracker/http_client.py` — **vendored** from `shared/` via `make sync-shared`.
- `maid-tracker/static/app.js` — language dropdown, daily-pay amount field.
- `maid-tracker/requirements.txt` — **no change** (httpx already present; no `anthropic`).
- `maid-tracker/secrets.manifest.yaml` — add `MIMO_API_KEY` (→ `shared.llm.mimo_api_key`),
  `MIMO_BASE_URL`, `MIMO_MODEL` literals. Vault key already promoted (done).
- `maid-tracker/tests/` — i18n key-coverage test, reminder-cache test.
- `maid-tracker/.notes/daily_log.md` + `00_INDEX.md` — update per project rules.

## Risks

- **Burmese/Lao/Khmer correctness** (Feature A static strings) — frozen + unverified;
  needs native review. Highest-risk item; the plumbing around it is trivial.
- **LLM cost/latency** (Feature C) — bounded: one call per reminder edit (rare), cached.
- **MiMo reasoning-model empty-content trap** — must set `max_tokens` ≥ 1500 and treat
  empty `content` as failure, or reminders silently cache blank translations.
- **Duplicate MiMo tokens in vault** — same token also at `shared.mimo.anthropic_api_key`
  (used by `scripts/`); not consolidated here to avoid touching an out-of-scope consumer.
