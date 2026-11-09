# Presenter Shots (n8n state + clock for multi-shot Flow clips) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Multi-shot presenter clips (4–6 Flow shots) keep their per-shot state, submit pacing,
gate results and Fix's per-shot review decisions in n8n, so a run that spans several agent turns
cannot lose a shot, skip a gate, submit too fast, or spend credits on a regen Fix did not approve.

**Architecture:** n8n workflow `Presenter Shots` owns the state (workflow static data) and the
rules (pure JS state machine `n8n/presenter-shots/core.js`, embedded into the Code node by
`build_workflow.py`). Hermes talks to it through one CLI, `flow-shopee-clips/scripts/shotboard.py`,
which also runs the deterministic per-shot gates locally (the files live in the Hermes container)
and sends each finished shot to Telegram with a reply keyboard (✅ ผ่าน / 🔁 gen ใหม่). A 5-minute
schedule trigger in the same workflow reads the state (read-only) and alerts Fix on stalls through
the existing Secretary Bot credential.

**Tech Stack:** n8n 2.x (webhook 4.5, code 2, respondToWebhook 1.1, scheduleTrigger, telegram 1.2),
Node 26 `node:test` for the core, Python 3 stdlib for `shotboard.py` + `build_workflow.py`, pytest.

**Spec:** `n8n/docs/presenter-shots.md` (design + operations).

## Global Constraints

- Auth: header `X-Clip-Token` must equal env `CLIP_INTAKE_TOKEN` (constant-time). Empty env = reject all.
- Pacing: ≥300 s between any two Flow submits (account-wide, all jobs). Jobs named `test-*` use a separate clock.
- Credits: attempt ≥2 of a shot is allowed only after Fix's `regen` decision for that shot.
- Chaining: shot k>1 may be reserved only when shot k−1 is `in_review` or `approved`.
- The stall tick never writes static data (avoids clobbering a concurrent webhook execution).
- No secrets, IPs or domains in committed files.

---

### Task 1: core state machine (`n8n/presenter-shots/core.js`)

**Files:** Create `n8n/presenter-shots/core.js`, `n8n/presenter-shots/core.test.js`

**Interfaces — Produces:**
- `apply(state, event, nowMs) -> {state, code, body}` — `event.action` ∈ `create_job, reserve,
  submitted, submit_failed, ready, decide, status, assemble_check, close, cancel`.
- `stalls(state, nowMs, tickMs) -> [{job, shot, kind, text}]` — read-only.
- `emptyState() -> {jobs:{}, last_submit_at:null, test_last_submit_at:null}`.

- [ ] Write `core.test.js` covering: create/duplicate, reserve pacing (429 + `wait_s`), chaining
      rule, regen credit rule, submit_failed revert, ready→in_review, decide approve/regen,
      assemble_check, stalls fire once per window, bad action 400.
- [ ] `node --test n8n/presenter-shots/` → FAIL (module missing).
- [ ] Implement `core.js`.
- [ ] `node --test n8n/presenter-shots/` → PASS.

### Task 2: workflow generator + drift test

**Files:** Create `n8n/presenter-shots/build_workflow.py`, generated `n8n/workflows/Presenter_Shots.json`,
`tests/test_presenter_shots_workflow.py`

- [ ] Test: generated JSON's Code nodes contain core.js verbatim; webhook path `presenter-shots`;
      schedule node present; Telegram node uses credential name `Secretary Bot`; regenerating equals
      the committed file.
- [ ] Implement generator (wrapper: auth → apply → persist → respond; tick: stalls → telegram).
- [ ] `uv run --with pytest pytest tests/test_presenter_shots_workflow.py` → PASS.

### Task 3: deploy to live n8n + live verification

- [ ] Create via `POST /api/v1/workflows`, activate.
- [ ] Live: no token → 401; `test-*` job full lifecycle; pacing 429; regen rule 409.
- [ ] Record workflow id in the doc.

### Task 4: `shotboard.py` (Hermes skill script)

**Files:** Create `/opt/data/skills/flow-shopee-clips/scripts/shotboard.py`,
`/opt/data/skills/flow-shopee-clips/scripts/test_shotboard.py`

- [ ] Unit tests: `cta_hits()`, `verdict()`, `review_keyboard()`, `parse_decision_text()`.
- [ ] Implement CLI: `new, reserve [--wait], submitted, submit-failed, ready, decide, status,
      assemble-check, close, cancel`; `ready` runs probe + detect_repeats + CTA scan + frame verdict,
      posts to n8n, then (unless `--no-send`) send_clip.py + reply-keyboard message.
- [ ] Live test against n8n with a synthetic mp4 and `--no-send`, then one real send of the keyboard.

### Task 5: wire into the skill + docs + commit

- [ ] Patch `flow-shopee-clips/SKILL.md` (multi-scene review gate → shotboard).
- [ ] `n8n/docs/presenter-shots.md`, `n8n/README.md` row, `n8n/.notes/*`.
- [ ] Commit + push main.
