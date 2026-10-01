# Local bundle sync — implementation plan

Spec: `docs/superpowers/specs/2026-10-01-local-bundle-sync-design.md`.
Work TDD: each task = failing test → implement → `pytest ai-deck/tests -q` green.
Paths relative to `ai-deck/`. Do not commit/deploy without user approval.

## Task 1 — Store: import bundle (`workspaces.py`)

Tests (`tests/test_workspaces.py`, helper builds a real repo + `git bundle create --all` in `tmp_path`):
- full bundle → record `source=bundle`, `url=local:<slug>`, `base_sha` = base branch tip, worktree on `desk/<id>`.
- explicit `branch` honoured; missing branch → 400, no cache/worktree left.
- corrupt file → 400, no cache dir left; bundle file deleted in both cases.
- ref outside `refs/heads/*`/`HEAD` (e.g. `refs/tags/x` only) → 400.
- invalid slug (`../x`, upper case, >64) → 400.
- optional `name`/`email` → `git -C <worktree> config user.email` returns it (use `extensions.worktreeConfig` + `config --worktree` so tasks sharing a cache keep separate identity).
- secret scan: repo with `.env`, `deploy/key.pem` → `record["warnings"]` lists both; not persisted as error.

Implement:
- `_SLUG = re.compile(r"[a-z0-9._-]{1,64}")`, reject `.`/`..`.
- `import_bundle(owner, slug, bundle_path, branch="", name="", email="")`:
  `git bundle verify` (needs no repo when bundle has no prerequisites; for existing cache run with `-C cache`), `git bundle list-heads` → validate refs, then `init --bare` if new, `fetch <bundle> +refs/heads/*:refs/remotes/origin/*` (no `--prune`), base branch: given → else bundle `HEAD` target → else `main`/`master`. Reuse existing worktree-add + `_cleanup_failed_create` + `_write`. `finally: os.unlink(bundle_path)`.
- Factor shared tail of `create()` (worktree add + record write) into `_start_task(owner, cache, url, base_ref, extra)`; `create()` must stay behaviour-identical (existing tests guard).

## Task 2 — Store: update + export

Tests:
- update: commit on Mac repo, `git bundle create upd.bundle <old>..main` → `update_bundle` succeeds, `refs/remotes/origin/main` advances, worktree untouched.
- update with prerequisite missing → 409 message contains "full bundle".
- update on a GitHub-source workspace → 400.
- export: agent-style commit in worktree → `export_bundle` path; fresh clone of Mac repo can `git fetch <file> desk/<id>:x` and `x` == worktree HEAD; bundle prerequisites == `base_sha`.
- no new commits → 409 "nothing to export". dirty worktree → 409; `force=True` → exports.
- other owner → 404 (existing `get()` behaviour).

Implement `update_bundle(owner, workspace_id, bundle_path)` and
`export_bundle(owner, workspace_id, force=False)` → writes
`/workspaces/exports/<owner>/desk-<slug>-<id8>.bundle` (overwrite), returns path.
Export uses `git bundle create <out> <base_sha>..desk/<id>`.

## Task 3 — HTTP adapter (`workspace_api.py`)

Tests (`tests/test_workspace_api` style used by existing adapter tests; find them via `grep -l workspace_api tests`):
- `PUT /projects/bundle?slug=a` streams body to `/workspaces/incoming/<owner>/<uuid>.part`, `os.replace` → `.bundle`, calls import, returns JSON record (201).
- `PUT /projects/bundle?workspace=<id>` → update (200).
- missing/oversize `Content-Length` (>300 MiB) → 413/411, no part file left.
- `GET /projects/export?workspace=<id>[&force=1]` → `application/octet-stream`, `Content-Disposition: attachment; filename=...`, streamed in chunks.
- no `X-Desk-User` → 401.
- `GET /projects` items include `source` (default `github` for old records).

## Task 4 — nginx

In `nginx/*.conf` coding section, before `location /code/projects`:
```
location ^~ /code/projects/bundle {
    client_max_body_size 300m;
    proxy_request_buffering off;
    # same proxy_pass / rewrite / X-Desk-User headers as /code/projects
}
location ^~ /code/projects/export { proxy_buffering off; ... same }
```
Test: extend existing nginx config test (grep `client_max_body_size` in tests) — assert both locations, owner header overwrite, body size.

## Task 5 — UI

Tests: extend `tests/workspace_harness.html` / `test_workspace_ui.py`:
- Projects dialog tab switch GitHub ↔ Local bundle; local form fields slug (datalist of existing `local:*`), branch, name, email, file.
- upload uses `fetch(PUT)` with progress text; on success opens task; warnings rendered as list.
- bundle task: **Download changes** (link to export) and **Upload update** visible; Commit & push + Deploy hidden. GitHub task unchanged.
- 409 dirty → confirm "export commits only?" → retries with `force=1` (inline confirm, not `window.confirm`).

## Task 6 — `scripts/desk-sync` (repo root `scripts/`)

Bash, `set -euo pipefail`. Config `~/.config/desk-sync/config` (`DESK_URL`, `DESK_USER`); password `security find-generic-password -s desk-sync -a "$DESK_USER" -w` → temp netrc `0600`, `trap` removes it. State `$(git rev-parse --git-dir)/desk-sync` (key=value).
- `up [--slug S] [--branch B] [--name N --email E]`: no state → `git bundle create --all` → PUT `?slug=`; store `slug`, `workspace`, `last_sent=$(git rev-parse HEAD)`. State present → `last_sent..HEAD` (+ any other changed branches via `--branches --not $last_sent`); nothing new → exit 0 with message; server 409 → print "run `desk-sync up --full`"; `--full` forces full bundle update.
- `down`: GET export to temp → `git bundle verify` → `git fetch <file> "desk/<id>:refs/heads/desk/<id>"` (`+` force) → print `git log --oneline HEAD..desk/<id>` and `git diff --stat HEAD...desk/<id>`.
- `status`: print state + ahead/behind.
- warn on dirty tree, never block.

Test `tests/test_desk_sync.py` (or root `tests/`): run script against a stdlib Python stub server implementing the 3 endpoints, `security` replaced by a stub on `PATH`; cover full up, incremental up, nothing-new, down fetch.

## Task 7 — Docs + memory

- README "Coding projects": Local bundle subsection + `desk-sync` setup (Keychain item creation command with `<password>` placeholder).
- `docs/CODING_WALKTHROUGH.md`: round-trip example.
- Root `CLAUDE.md` ai-deck row: one sentence (bundle import/export, no push for local projects).
- `.notes/daily_log.md`, `.notes/00_INDEX.md` updated.

## Verification before done

- full `pytest ai-deck/tests -q` + desk-sync tests green; `bash -n scripts/desk-sync`; `git diff --check`.
- Manual on NAS after user-approved deploy: real VPN repo `desk-sync up` → agent commit in chat → `desk-sync down` → `git log` shows commit on Mac.
