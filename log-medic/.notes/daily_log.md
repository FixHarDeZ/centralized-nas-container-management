# log-medic — Daily Log

## 2026-07-05 — Final review, critical fix, merged to main
Final whole-branch review (base a99e2c7..0c3878d, 23 commits) found one Critical:
`watcher.py` called `container.logs(..., since=0)` — docker-py 7.1.0 requires
`since > 0`, so `since=0` raised `InvalidArgument` on every call. The broad
`except Exception` in `_watch` swallowed it and retried forever every 5s —
watcher never streamed a single log line, silently. No test caught it since
all watcher tests mock `docker_client`. Fixed: `since=0` → `tail=0` (commit
`76e9c0d`), also fixes historical-backlog replay on restart as a side effect.
Also added await+CancelledError guard on `reload_task.cancel()` in main.py's
lifespan teardown, and a comment documenting the broad-except tradeoff in
watcher.py. Re-review clean, 45/45 tests passing. Merged feat/log-medic →
main (fast-forward), pushed to origin. Branch + worktree deleted.
**Still pending before real deployment (manual, on NAS/workstation):**
vault secrets (`stacks.log_medic.dashboard.{user,password}`,
`stacks.log_medic.github_token`), `nginx/.htpasswd` generation, persistent
git clone at `/volume2/docker/log-medic/workspaces/`, and the on-NAS DoD
run (temp container emitting `ERROR: explosion` → SQLite event + Telegram).

## 2026-07-05 — Initial implementation complete (feat/log-medic)
Built the full stack per docs/superpowers/plans/2026-07-04-log-medic-implementation.md:
db schema, vendored notify.py, config.yaml seeding, fingerprint normalization +
ring buffer, 5-gate pipeline, docker-py watcher with hot reload, analyzer
phase 1 (read-only) + phase 2 (fix+PR with forbidden-file/diff-size safety
rails), scheduler (breaker auto-reset + 18:00 digest), API routes, dashboard.
Not yet deployed to NAS — vault keys and nginx/.htpasswd still need the
one-time manual setup in README.md.

## 2026-07-04
- Task 6: implemented `watcher.process_event` (notify_only / dev-maturity / gate chain / analyze / fix-runner routing) and `WatcherManager` (async hot-reload manager diffing `db.list_monitored_containers`, docker-py log streaming via `asyncio.to_thread`, pause/resume). TDD: 5 new tests RED (AttributeError on missing `process_event`/`gate`/`WatcherManager`) → GREEN after implementation. Full suite 26/26 passing.
- Added minimal `app/analyzer.py` stub (`analyze`/`run_fix` both `raise NotImplementedError`) so `from app import analyzer` resolves — real implementation lands in Tasks 7/8.
- Local env gap: `docker==7.1.0` (already pinned in `requirements.txt`) wasn't installed in the workstation's global Python; installed via `pip install --break-system-packages docker==7.1.0` to run tests. No repo file changes needed.
