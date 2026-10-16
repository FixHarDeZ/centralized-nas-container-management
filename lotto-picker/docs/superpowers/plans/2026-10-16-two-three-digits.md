# Two/Three Digit Picker Implementation Plan

> **For agentic workers:** Use subagent-driven-development with explicit file ownership and independent final review.

**Goal:** Separate official two-digit and existing three-digit picking across UI, persistence, scoring and automation.

**Architecture:** Add digits=2|3 with legacy default3, per-mode kv settings and JSON mode tags. Reuse existing endpoints with optional mode query and preserve schema. Mobile mode switch keeps separate state and prevents cross-mode request races.

**Tech Stack:** FastAPI/Pydantic, SQLite JSON1, vanilla JavaScript, pytest/Playwright.

## Global constraints

- Preserve stored legacy settings/picks/results and current three-digit defaults.
- Two digits uses last2 only, pool00–99, exact scoring only; no reversed-number win.
- Three-digit prize scopes and scoring retain current behavior.
- New two-digit automation defaults off; three-digit auto guard key remains unchanged.
- No new production dependencies, secrets or ports. No destructive DB migration.
- Browser fixture tests do not reach GLO/Telegram. Touch targets at least44px; support320px and dark mode.

## Task 1 — Logic, storage and service (backend worker)

Files: app/lotto.py, app/db.py, app/service.py; tests/test_lotto.py, test_service.py and new test_digit_storage.py.

- [x] Add failing tests for two-digit pools/reverse exclusions/exact scoring and last2 completeness.
- [x] Implement appended digits=3 arguments and ALL_TWO without changing existing all scope.
- [x] Add per-mode settings and SQL history/stats filters before LIMIT, legacy fallback3, no schema rebuild.
- [x] Score mixed pending picks in correct mode; retain pending if earliest target lacks last2. Repair old incomplete draw payload only from fully complete fetched results.
- [x] Run backend-owned tests and report red/green evidence.

## Task 2 — API, automation and notification (root)

Files: app/main.py, app/messages.py; tests/test_auto_pick.py and new test_modes_api.py/test_messages.py.

- [x] Write failing API tests for digits validation, separate settings/history/stats and mixed-width saves.
- [x] Add mode query/default3, strict ASCII width validation and scope canonicalization.
- [x] Synchronize enough draws for both modes. Score both, announce enabled profiles only with separate stats.
- [x] Generate automatic picks independently with preserved3guard and new2guard. Lock repeated job execution to prevent duplicates.
- [x] Add tests for independent auto flags/guards and messages containing exact2/3labels.

## Task 3 — Mobile modes and browser tests (UI worker)

Files: app/static/index.html, style.css, app.js; tests/test_ui_browser.py.

- [x] Add failing browser cases for two modes, independent results/forms/settings, save width, filtered history/stats and rapid switching.
- [x] Add mode selector accessible from every destination and large2/3labels. Preserve dashboard design.
- [x] Cache draft/result/saved state per mode; fetch selected profile/history/stats safely, discard stale responses or block mode changes while mutating.
- [x] Adapt scope/reverse labels, note, result width and exact-only stats to mode2. Existing default3tests remain meaningful.
- [x] Run browser suite and inspect320/390/1440px light/dark screenshots.

## Task 4 — Integrate, review and release (root)

- [x] Run full stack, root tests, JS/shell syntax, Ruff and diff checks.
- [x] Independent spec/correctness review and resolve all actionable findings.
- [x] Update README/root Lotto summary and both stack memory files, commit source into main and push.
- [x] Back up NAS DB, deploy only lotto-picker, verify health/auth/assets/both modes/history.
- [x] Remove native worktree/local branch; update and verify closure memory, commit/push documentation.

## Release result

Source 1ca3560 merged into main, pushed and deployed. Stack85 + root64 tests passed; independent backend/UI review approved. Production health/auth/assets, both-mode generation/read APIs, existing settings/history and backup verified. Temporary worktree archived/removed and branch deleted. Closure documentation is committed and pushed after deployment; no runtime changes in that update.
