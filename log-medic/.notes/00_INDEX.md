# log-medic — Index

## Gaps / TODOs
v1 (13 plan tasks) merged to `main` (`76e9c0d`). Close-the-loop feature (verdict triage + merge poll + auto deploy) on branch `feat/log-medic-close-loop`, not yet merged/deployed.
Remaining gaps are manual one-time setup only:
- `nginx/.htpasswd` not generated yet — run `htpasswd -c log-medic/nginx/.htpasswd <user>` before first deploy (same manual step as `friendly-reminder`).
- Vault keys not added yet — run `make edit-vault`, add `stacks.log_medic.dashboard.{user,password}` and `stacks.log_medic.github_token`.
- `/volume2/docker/log-medic/workspaces/<repo>/` must be `git clone`d once manually on the NAS before first use — the app only ever runs `git fetch` there.
- On-NAS Definition-of-Done run still pending: `docker compose up -d --build`, `/health` 200, temp container emitting `ERROR: explosion` → SQLite event + Telegram notify. Flagged by final review as a hard pre-real-use gate since the one bug found (`since=0` crash, fixed) only ever surfaces against a real docker-py socket, never against mocks.
- On-NAS DoD for close-the-loop pending: needs `/volume2/docker:/stacks` mount live + image rebuild (docker cli/compose added); self-deploy of log-medic remains manual by design.

## Modules (final, post-merge)
- `app/watcher.py`: `DEFAULT_REGEX`/`normalize_message`/`fingerprint`/`RingBuffer` + `process_event()` (gate/notify/analyze/fix routing — now also routes on verdict, see below), `WatcherManager` (hot-reload: `.reload(conn)` diffs `db.list_monitored_containers` against running asyncio tasks, `.pause()`/`.resume()`/`.is_paused`), `_watch_once()` (blocking docker-py log stream via `container.logs(stream=True, follow=True, tail=0)`, run via `asyncio.to_thread`). Note: `tail=0`, not `since=0` — docker-py 7.1.0 rejects `since=0` (`InvalidArgument`), caught in final review.
- `app/analyzer.py`: `analyze()` (phase 1, read-only root-cause via headless `claude -p`) + `run_fix()` (phase 2, branch/edit/diff-check/PR via `gh pr create` — never `pr merge`). `parse_verdict(raw_text)` extracts the mandatory `VERDICT: code`/`VERDICT: infra` first line (regex `_VERDICT_RE`); fail-safe defaults to `infra` on anything unparseable so a malformed response never unlocks the fix runner. `process_event` gates `run_fix` on `maturity=="stable" AND ENABLE_FIX_RUNNER=true AND verdict=="code"`.
- `app/deployer.py` (close-the-loop, new): `deploy(conn, container_row, fingerprint, pr_url, docker_client=None, sleep=time.sleep)` — self-deploy guard (subdir `"log-medic"` → notify + skip), `git fetch`/`checkout -B main origin/main`/`reset --hard` the workspace clone, `copy_tracked_files(workspace_repo_root, subdir, dest_stack_dir)` (`git ls-files -z` scoped to subdir, `shutil.copy2` per file, additive-only — never deletes at destination), `docker compose --project-directory <stack_dir> up -d --build` (600s timeout), 60s sleep then verify `RestartCount` unchanged + `State.Running` via docker-py. Any exception at any step → `deploy_failed` (terminal) + ❌ Telegram with the failing step and recovery instructions; success → `deployed` + 🚀 Telegram.
- `app/scheduler.py`, `app/api/*`, `app/main.py`, `app/static/*`: scheduler jobs (including new `poll_pr_merges` — `IntervalTrigger(minutes=5)`, per `pr_opened` event runs `gh pr view --json state,mergedAt`; `MERGED` → status `merged` + calls `deployer.deploy`; `CLOSED` → status `pr_closed` + best-effort remote branch delete + Telegram; `OPEN` left as-is; per-event `except Exception` logs and retries next cycle, never crashes the job), REST API, FastAPI wiring + hot-reload loop, dashboard SPA (Events tab gained a Verdict column) — all implemented, reviewed, tested (66 tests passing).
- Requires `docker==7.1.0` (already in `requirements.txt`) — not preinstalled in the workstation's global Python env; had to `pip install --break-system-packages docker==7.1.0` locally to run tests.

## Schema
See `app/db.py` — `monitored_containers`, `events` (gained `verdict` column, additive `ALTER TABLE` in `init_db`, values `code`/`infra`), `daily_quota`, `circuit_breaker`, `audit_log`.

## API
`GET/POST /api/containers`, `PATCH/DELETE /api/containers/{name}`, `GET /api/events`,
`POST /api/watcher/{pause,resume}`, `GET /health`. All behind nginx Basic Auth except
health (also behind auth per spec — no public exception for log-medic, unlike
friendly-reminder's LINE webhook).
