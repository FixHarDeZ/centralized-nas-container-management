# Shopee clip skills — hardening pass (review items 1–5)

Status: **decisions D1–D4 answered 2026-11-11, waiting for Fix's go signal.** Nothing below has been run.
Source: the 2026-11-11 review (hermes-agent session). Stack memory: `hermes-agent/.notes/`.

## Decisions (filled before the run)
| # | Question | Answer |
|---|---|---|
| D1 | Drift policy: port live in-place edits by hand as a routine, or have sync pull them back into the repo? | **Pull back.** `sync.sh --pull` copies live drift into the clone for review/commit; plain sync still captures + overwrites as today |
| D2 | `reserve` strictness for shot K | **K-1's gates all pass** (`in_review` with every gate ok, or `approved`). Overlap kept |
| D3 | Delivery format: hashtags + link in one message (router) or two fenced blocks + copy buttons (gameplay) | **Copy buttons only** (`send_copy_buttons.py`, as `clipjob deliver` does now). No fenced blocks, every mode |
| D4 | 🔁 on shot K when K+1 is already rendered/approved | **Flag, Fix decides.** K+1 keeps its state; a message warns that continuity may break and offers ✅ keep / 🔁 K+1. `submitting`/`submitted` K+1 → same warning once it lands |

Taken without asking (state in the commit + notes):
- The `D-N` pill in LOOK v5 is removed. The dated 2026-11-07 "no countdown" rule wins.
- `gameplay-clips/SKILL.md` budget = 30 KB, enforced by `tests/test_hermes_skills.py`. `house-rules.md` budget = 20 KB.
- Item 5 only adds a warning to the Q1 text. Fix still picks the mode.
- `fallback` keeps skipping `failed` shots (flow-driver rule: spent shots are re-packed only after 🔁).
  The fix is that a `failed` shot gets a message with the 🔁 button.

## Preconditions — check, stop if any fails
1. Hermes is idle: `clipjob.py status` shows no open jobs, `curl -s http://127.0.0.1:9222/json/version` is empty,
   and `agent.log` has no turn in the last 15 min. Ask Fix not to order clips until the run ends.
2. Snapshot every live file that differs from the clone into
   `/opt/data/clips/skill-drift/pre-hardening-<ts>/` (read-only copy, plus diffs).
3. Save Hermes' uncommitted clone diffs (`build_v5.py`, `sync.sh`, the new `test_build_v5_substyle.py`)
   to the workstation.

## Phase 1 — bring the repo up to live (item 1)
- Port the 9 in-place edits (router SKILL.md, frame-check, presenter-graphics, presenter-post, clip-prompt,
  storyboard, flow-driver SKILL.md, flow-browser-env, flow-picker-dom) and Hermes' clone diffs into the repo.
  Check the 2026-11-10 drift dir (6 files) was fully ported; port what is missing.
- Merge the edits into the existing structure rather than appending. The router must stay ≤15 KB.
  Move detail to references/.
- Implement D1:
  - (port by hand) `sync.sh` refuses when the drift dir has unreviewed captures, unless `ACK_DRIFT=1` is set.
  - (pull back) `sync.sh --pull` copies live drift into the clone working tree for review/commit instead
    of overwriting it.
- `sync.sh`: stamp the manifest with the commit only when the tracked skill files are clean. If they are
  dirty, refuse.
- Hermes' clone: `.venv/bin/python` and `uv.lock` get dirtied by every run. Set `git update-index
  --skip-worktree` on both. **Confirm step:** reset Hermes' clone edits to the pushed versions after the port.

## Phase 2 — clipjob.py state machine (item 2), tests first
- `reserve K`: implement D2. At minimum, refuse when shot K-1 is `in_review` with a failed gate, or when it
  is `regen_approved`.
- 🔁 on K: implement D4 for K+1 (`submitting` → `pending`; rendered → per D4).
- `submitted --edit-id` becomes optional. Add `clipjob.py edit-id JOB K ID` to record the real id later, and
  refuse `deliver` while an auto job has placeholder ids (or log them as `null`).
- A `failed` shot: `submit-failed --credits-spent` sends a short message with the 🔁 keyboard
  (`decide` already accepts regen from `failed`).
- `ready`: if the Telegram send fails, save state first, then refuse. Add `ready --resend` (no whisper rerun).
- `reserve --wait`: check the Hermes terminal-tool timeout. If it is <330 s, cap the sleep below the timeout
  and return exit 4 with `wait_s`.
- Back-compat test: load the current `yugioh-gx.json` / `bao-jin-rack.json` schema and run every command on it.

## Phase 3 — 🎬 through clipjob (item 3)
- `clipjob.py new --mode gameplay` (no shots, no refs) is already allowed. Wire the router step 4 and
  gameplay step 10 to `new` at the start and `deliver` at the end.
- `build_v5.py` writes no `report.json`. Add `report.json` to it (`v_dur`, `a_dur` from ffprobe, `flags`
  from `--check` warnings), or let `deliver` build the report itself from ffprobe for gameplay.
- `deliver` for gameplay: log `credits: 0`, `style: "gameplay"`, `category` from the arg. Use the delivery
  format from D3. Tests for both.
- Fix the text conflicts in gameplay-clips: step 0 workdir → `/opt/data/clips/work/<job>`, the cleanup
  pointer (router step 12, not 13), the duplicate intake step, D-N, and the delivery format per D3.
- Session resume: router step 0 already lists open jobs. That now covers 🎬 too.

## Phase 4 — slim the big docs (item 4)
- `gameplay-clips/SKILL.md` 76 KB → ≤30 KB. Steps stay in SKILL.md. Pitfalls go to
  `references/gameplay-pitfalls.md`, deduped and grouped by step. Anything that is a gate becomes a check in
  `build_v5.py --check` or clipjob, with a test.
- `house-rules.md` 36 KB → ≤20 KB. Drop what the router replaced (trigger phrases, execution mode, manual
  mode, "step 8" pointers). Keep the reasons behind the hard rules.
- 🤖 reading load: `flow-browser-env.md` stays mandatory but gets a 1-page "read first" head. Dedupe
  `flow-steps.md` and `pitfalls.md` where they repeat each other.
- Remove the n8n / Presenter Shots mentions from the 5 files (n8n Presenter Shots still runs; deactivating it
  stays a separate open item).
- Add size-budget tests and keep the unique-names and referenced-file tests passing.

## Phase 5 — 🧑 product drift (item 5)
- Q1 text: one line saying rigid products (racks, shelves, devices) drifted in 2/2 🧑 jobs, and pointing to
  📦/🎬 as the safer choice. Fix still picks.
- 🧑/📦 with N≥2 in 🤖: shot 2 is not reserved until shot 1 is ✅ (D2 may already cover this).
- Storyboard template: a "product-identity checklist" line (counts, proportions, parts) that the frame
  verdict must answer per shot.

## Ship
1. `uv run --with pytest pytest -q hermes-agent/skills/shopee-clip/scripts hermes-agent/skills/gameplay-clips/scripts tests/test_hermes_skills.py`
   must be green.
2. Commit per phase on `main`. No Co-Authored-By trailer (global CLAUDE.md). `git pull --ff-only`, push.
3. Re-check that Hermes is idle. Re-diff live against the Phase-1 snapshot. Port anything new, then
   `make hermes-skills ARGS=-n`, then `make hermes-skills`.
4. Verify:
   - In the container: the test gate passes, and `clipjob.py status` works on the existing jobs.
   - The live files equal the repo.
   - `check_delivery.py` exits 0.
5. Update `hermes-agent/.notes/daily_log.md` + `00_INDEX.md`, and the CLAUDE.md hermes row if the rules
   change.

## Not in scope
- Why `bao-jin-rack` post took 1.5 h (needs timing data first).
- Deactivating n8n Presenter Shots, the rollback image cleanup, the Chat tab.
