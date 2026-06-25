# Maid-Tracker Reminder Static-Dict i18n Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the MiMo-LLM reminder translator with a static hand-maintained dict, since the input space is ~2-10 fixed Thai reminder texts that almost never change.

**Architecture:** New `reminder_i18n.py` exports `lookup(text: str) -> dict | None`, same return shape as the old `reminder_translate.translate_reminder()`. Swap the import and the 4 call sites in `main.py`; `message_i18n` DB column, its cache-write logic, and `line_notify._reminder_body` stay untouched. Seed the dict from the **live** `message_i18n` values already cached on the NAS — do not re-translate.

**Tech Stack:** Python, FastAPI, sqlite3, pytest. No new dependencies; removes `httpx`-based `http_client.py` usage (if nothing else in the stack needs it) and the `MIMO_*` env vars.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-06-25-maid-tracker-reminder-static-i18n-design.md` (supersedes Feature C of the 2026-06-24 design).
- `reminder_i18n.lookup(text)` must return the exact same shape as today's cached value: `{"my": str, "en": str, "lo": str, "km": str}` or `None`. Downstream code does `json.dumps(tr, ensure_ascii=False)` on a truthy return — do not change that contract.
- Do not touch `i18n.py` (Feature A, unrelated) or daily-pay override (Feature B, unrelated).
- Seed dict values come from NAS production data, not freshly generated text.
- Vault secret `shared.llm.mimo_api_key` is NOT deleted (news-feed still uses it). Only maid-tracker's `secrets.manifest.yaml` entries for it are removed.

---

### Task 1: Pull live reminder translations off the NAS

**Files:** none (read-only data pull, output captured for Task 2)

**Interfaces:**
- Produces: a list of `(message: str, my: str, en: str, lo: str, km: str)` rows to hard-code into `reminder_i18n.py` in Task 2.

- [ ] **Step 1: SSH to NAS and dump the reminders table**

```bash
ssh -p 2222 -i ~/.ssh/id_ed25519 fixhardez@fixhardez.synology.me \
  "echo '<NAS_SUDO_PASSWORD>' | sudo -S /usr/local/bin/docker exec maid-tracker \
   python3 -c \"
import sqlite3, json
conn = sqlite3.connect('/data/maid_tracker.db')
conn.row_factory = sqlite3.Row
for r in conn.execute('SELECT id, message, message_i18n FROM reminders'):
    print(r['id'], '|', r['message'], '|', r['message_i18n'])
\""
```

Use the actual NAS sudo password from your local credential store
(Bitwarden/1Password) — never write the real password into a committed
file, per root `CLAUDE.md` security guardrail.

Adjust the container name / DB path if they differ from `maid-tracker` /
`/data/maid_tracker.db` — check `docker ps` and the stack's
`docker-compose.yml` `volumes:` line first if the exec fails.

- [ ] **Step 2: Record the output**

For every row where `message_i18n` is not empty/null, note the exact
`message` text and the parsed `{"my":..,"en":..,"lo":..,"km":..}` JSON. Skip
rows where `message_i18n` is `None` — there is nothing to seed for those
(they'll fall back to Thai-only same as today, until someone fills in an
entry by hand later).

This data feeds directly into Task 2's `REMINDERS` dict literal — do not
proceed to Task 2 without it.

---

### Task 2: Create `reminder_i18n.py` with seeded static dict

**Files:**
- Create: `maid-tracker/reminder_i18n.py`
- Test: `maid-tracker/tests/test_reminder_i18n.py`

**Interfaces:**
- Produces: `lookup(text: str) -> dict | None` — `REMINDERS.get(text)`.

- [ ] **Step 1: Write the failing test**

```python
# maid-tracker/tests/test_reminder_i18n.py
import reminder_i18n as ri


def test_known_text_returns_all_four_langs():
    out = ri.lookup("🛏️ วันนี้เปลี่ยนผ้าปูที่นอนด้วยนะคะ")
    assert out is not None
    assert set(out.keys()) == {"my", "en", "lo", "km"}
    assert all(isinstance(v, str) and v for v in out.values())


def test_unknown_text_returns_none():
    assert ri.lookup("ไม่มีในดิก ข้อความสุ่มที่ไม่ตรงกับอะไรเลย") is None
```

(If the exact text `"🛏️ วันนี้เปลี่ยนผ้าปูที่นอนด้วยนะคะ"` was not one of the
rows seeded in Task 1, replace it in this test with any `message` text that
*was* seeded with a non-null `message_i18n`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd maid-tracker && python -m pytest tests/test_reminder_i18n.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'reminder_i18n'`

- [ ] **Step 3: Write `reminder_i18n.py` using the Task 1 data**

```python
"""Static reminder translations — replaces the MiMo-LLM translator.

Reminder texts are a small, nearly-fixed set (owner confirmed ~2-10 distinct
texts, rarely changes) so a hand-maintained dict beats an LLM call: no API
dependency, no failure modes, deterministic.

machine-generated (seeded from MiMo output already in production),
needs native-speaker review — same caveat as i18n.py.
"""

REMINDERS: dict[str, dict[str, str]] = {
    # Fill in every (message -> {my, en, lo, km}) row recorded in Task 1.
    # Example shape (replace with real seeded values):
    # "🛏️ วันนี้เปลี่ยนผ้าปูที่นอนด้วยนะคะ": {
    #     "my": "...", "en": "...", "lo": "...", "km": "...",
    # },
}


def lookup(text: str) -> dict | None:
    return REMINDERS.get(text)
```

Replace every commented placeholder row with the real `message` text and
real `{"my":..,"en":..,"lo":..,"km":..}` values pulled in Task 1. Do not
leave the example placeholder row in the final file — it must contain only
real seeded entries (or be empty if Task 1 found no non-null
`message_i18n` rows, in which case leave `REMINDERS = {}` and skip ahead;
`lookup()` then always returns `None`, matching today's Thai-only fallback
for unseeded text).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd maid-tracker && python -m pytest tests/test_reminder_i18n.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add maid-tracker/reminder_i18n.py maid-tracker/tests/test_reminder_i18n.py
git commit -m "feat(maid-tracker): add static reminder_i18n dict, seeded from prod cache"
```

---

### Task 3: Swap `main.py` call sites from `reminder_translate` to `reminder_i18n`

**Files:**
- Modify: `maid-tracker/main.py:19` (import), `:471`, `:1947`, `:1975`, `:2032`

**Interfaces:**
- Consumes: `reminder_i18n.lookup(text: str) -> dict | None` from Task 2.

- [ ] **Step 1: Swap the import**

In `maid-tracker/main.py`, change:

```python
import reminder_translate
```

to:

```python
import reminder_i18n
```

- [ ] **Step 2: Swap all 4 call sites**

Each of these four call sites currently reads
`reminder_translate.translate_reminder(<text>)`. Replace each with
`reminder_i18n.lookup(<text>)` — keep the surrounding `tr = ...` / `if tr:`
logic exactly as-is, only the right-hand side changes.

Site 1 (`_check_reminders`, around line 471):
```python
        mi18n = r.get("message_i18n")
        if not mi18n:
            tr = reminder_i18n.lookup(r["message"])
            if tr:
                mi18n = json.dumps(tr, ensure_ascii=False)
```

Site 2 (`create_reminder`, around line 1947):
```python
    tr = reminder_i18n.lookup(rem.message)
    i18n_json = json.dumps(tr, ensure_ascii=False) if tr else None
```

Site 3 (`update_reminder`, around line 1975):
```python
    tr = reminder_i18n.lookup(rem.message)
    i18n_json = json.dumps(tr, ensure_ascii=False) if tr else None
```

Site 4 (`test_reminder`, around line 2032):
```python
        tr = reminder_i18n.lookup(r["message"])
        if tr:
            mi18n = json.dumps(tr, ensure_ascii=False)
```

- [ ] **Step 3: Verify no remaining references**

Run: `cd maid-tracker && grep -n "reminder_translate" main.py`
Expected: no output (empty)

- [ ] **Step 4: Run the full test suite**

Run: `cd maid-tracker && python -m pytest tests/ -v`
Expected: all tests pass except `tests/test_reminder_translate.py` (deleted
in Task 4 — if Task 4 hasn't run yet, those tests still pass unchanged since
that file doesn't import `main.py`).

- [ ] **Step 5: Commit**

```bash
git add maid-tracker/main.py
git commit -m "feat(maid-tracker): swap reminder translation from MiMo LLM to static dict"
```

---

### Task 4: Delete `reminder_translate.py` and its test, remove unused vendored `http_client.py`

**Files:**
- Delete: `maid-tracker/reminder_translate.py`
- Delete: `maid-tracker/tests/test_reminder_translate.py`
- Delete (conditional): `maid-tracker/http_client.py`

**Interfaces:** none (pure removal)

- [ ] **Step 1: Confirm nothing else imports `http_client`**

Run: `cd maid-tracker && grep -rln "http_client" --include="*.py" .`
Expected output: only `./reminder_translate.py` and `./http_client.py`
itself. If anything else shows up, do NOT delete `http_client.py` — skip
Step 3 below and leave it in place.

- [ ] **Step 2: Delete the old translator and its test**

```bash
cd maid-tracker
git rm reminder_translate.py tests/test_reminder_translate.py
```

- [ ] **Step 3: Delete `http_client.py` if Step 1 confirmed it's unused elsewhere**

```bash
cd maid-tracker
git rm http_client.py
```

- [ ] **Step 4: Run the full test suite**

Run: `cd maid-tracker && python -m pytest tests/ -v`
Expected: all tests pass, no `ModuleNotFoundError` for `reminder_translate`
or `http_client`.

- [ ] **Step 5: Commit**

```bash
git commit -m "chore(maid-tracker): remove MiMo reminder translator and vendored http_client"
```

---

### Task 5: Remove MiMo entries from `secrets.manifest.yaml`

**Files:**
- Modify: `maid-tracker/secrets.manifest.yaml`

**Interfaces:** none

- [ ] **Step 1: Edit the manifest**

Current `maid-tracker/secrets.manifest.yaml`:

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

Change to:

```yaml
env:
  MAID_LINE_CHANNEL_ACCESS_TOKEN: stacks.maid_tracker.line.channel_access_token
  MAID_LINE_CHANNEL_SECRET:       stacks.maid_tracker.line.channel_secret
  MAID_LINE_GROUP_ID:             stacks.maid_tracker.line.group_id
  MAID_PUBLIC_BASE_URL:           stacks.maid_tracker.public_base_url

literals:
  MONTHLY_REPORT_TIME: "20:00"
```

Do NOT touch `shared.llm.mimo_api_key` in `secrets/vault.sops.yaml` — only
this manifest's reference to it is removed. `news-feed/secrets.manifest.yaml`
still points at the same vault path and must be left alone.

- [ ] **Step 2: Regenerate `.env` and verify**

Run: `make secrets`
Expected: no errors; `maid-tracker/.env` regenerated without
`MIMO_API_KEY` / `MIMO_BASE_URL` / `MIMO_MODEL`.

Run: `grep -c MIMO maid-tracker/.env`
Expected: `0`

- [ ] **Step 3: Commit**

```bash
git add maid-tracker/secrets.manifest.yaml
git commit -m "chore(maid-tracker): drop MiMo secrets, no longer used by reminder translation"
```

---

### Task 6: Update stack docs

**Files:**
- Modify: `maid-tracker/.notes/daily_log.md`
- Modify: `maid-tracker/.notes/00_INDEX.md`

**Interfaces:** none

- [ ] **Step 1: Read both files first**

Run: `cat maid-tracker/.notes/daily_log.md maid-tracker/.notes/00_INDEX.md`

Note their existing format/sections before editing, per project rules in
the root `CLAUDE.md` ("ก่อนเริ่มงานเสมอ" / "After Task" rules).

- [ ] **Step 2: Append a daily_log.md entry**

Add an entry (matching the file's existing date-stamped entry format)
describing: reminder translation switched from MiMo LLM (cached per-text)
to a static hand-maintained dict in `reminder_i18n.py`, since the input
space is ~2-10 fixed texts; `reminder_translate.py` and `http_client.py`
removed; `MIMO_*` secrets dropped from the manifest.

- [ ] **Step 3: Update 00_INDEX.md**

Update whatever section currently documents the reminder-translation
mechanism (likely added when Feature C of the 2026-06-24 design shipped) to
describe `reminder_i18n.lookup()` / the static dict instead of the MiMo
call, and note that new reminder texts need a manual dict entry added (or
fall back to Thai-only).

- [ ] **Step 4: Commit**

```bash
git add maid-tracker/.notes/daily_log.md maid-tracker/.notes/00_INDEX.md
git commit -m "docs(maid-tracker): document reminder_i18n static-dict switch"
```

---

## Self-Review Notes (for the plan author, not a task)

- Spec coverage: Task 1+2 = seed data ("Seed data" spec section); Task 3 =
  drop-in swap ("New module" spec section); Task 4+5 = cleanup (spec
  "Cleanup" section); Task 6 = project doc rules (root `CLAUDE.md`). All
  spec sections have a task.
- No placeholders left except the explicitly-flagged "fill in from Task 1"
  spots in Task 2, which cannot be resolved until Task 1's live SSH pull
  runs — by design, since the spec requires real production data, not
  invented strings.
- Type consistency: `lookup(text: str) -> dict | None` used identically in
  Task 2 (definition) and Task 3 (all 4 call sites).
