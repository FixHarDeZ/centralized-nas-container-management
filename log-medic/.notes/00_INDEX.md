# log-medic — Index

## Gaps / TODOs
Code complete (all 13 plan tasks) and merged to `main` (commit `76e9c0d`), pushed to origin.
Not yet deployed to NAS — remaining gaps are manual one-time setup only:
- `nginx/.htpasswd` not generated yet — run `htpasswd -c log-medic/nginx/.htpasswd <user>` before first deploy (same manual step as `friendly-reminder`).
- Vault keys not added yet — run `make edit-vault`, add `stacks.log_medic.dashboard.{user,password}` and `stacks.log_medic.github_token`.
- `/volume2/docker/log-medic/workspaces/<repo>/` must be `git clone`d once manually on the NAS before first use — the app only ever runs `git fetch` there.
- On-NAS Definition-of-Done run still pending: `docker compose up -d --build`, `/health` 200, temp container emitting `ERROR: explosion` → SQLite event + Telegram notify. Flagged by final review as a hard pre-real-use gate since the one bug found (`since=0` crash, fixed) only ever surfaces against a real docker-py socket, never against mocks.

## Modules (final, post-merge)
- `app/watcher.py`: `DEFAULT_REGEX`/`normalize_message`/`fingerprint`/`RingBuffer` + `process_event()` (gate/notify/analyze/fix routing), `WatcherManager` (hot-reload: `.reload(conn)` diffs `db.list_monitored_containers` against running asyncio tasks, `.pause()`/`.resume()`/`.is_paused`), `_watch_once()` (blocking docker-py log stream via `container.logs(stream=True, follow=True, tail=0)`, run via `asyncio.to_thread`). Note: `tail=0`, not `since=0` — docker-py 7.1.0 rejects `since=0` (`InvalidArgument`), caught in final review.
- `app/analyzer.py`: `analyze()` (phase 1, read-only root-cause via headless `claude -p`) + `run_fix()` (phase 2, branch/edit/diff-check/PR via `gh pr create` — never `pr merge`).
- `app/scheduler.py`, `app/api/*`, `app/main.py`, `app/static/*`: scheduler jobs, REST API, FastAPI wiring + hot-reload loop, dashboard SPA — all implemented, reviewed, tested (45 tests passing).
- Requires `docker==7.1.0` (already in `requirements.txt`) — not preinstalled in the workstation's global Python env; had to `pip install --break-system-packages docker==7.1.0` locally to run tests.

## Schema
See `app/db.py` — `monitored_containers`, `events`, `daily_quota`, `circuit_breaker`, `audit_log`.

## API
`GET/POST /api/containers`, `PATCH/DELETE /api/containers/{name}`, `GET /api/events`,
`POST /api/watcher/{pause,resume}`, `GET /health`. All behind nginx Basic Auth except
health (also behind auth per spec — no public exception for log-medic, unlike
friendly-reminder's LINE webhook).
