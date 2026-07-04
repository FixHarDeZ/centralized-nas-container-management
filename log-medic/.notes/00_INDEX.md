# log-medic — Index

## Gaps / TODOs
- `nginx/.htpasswd` not generated yet — run `htpasswd -c log-medic/nginx/.htpasswd <user>` before first deploy (same manual step as `friendly-reminder`).
- Vault keys not added yet — run `make edit-vault`, add `stacks.log_medic.dashboard.{user,password}` and `stacks.log_medic.github_token`.
- `/volume2/docker/log-medic/workspaces/<repo>/` must be `git clone`d once manually on the NAS before first use — the app only ever runs `git fetch` there.
- `app/analyzer.py` is currently a stub (`analyze`/`run_fix` both `raise NotImplementedError`) added in Task 6 only so `from app import analyzer` resolves for `watcher.py`. Tasks 7/8 must implement it for real — `watcher.process_event` will crash on any non-`dev`-maturity, non-gated event until then.

## Modules (as of Task 6)
- `app/watcher.py`: `DEFAULT_REGEX`/`normalize_message`/`fingerprint`/`RingBuffer` (Task 4) + `process_event()` (gate/notify/analyze/fix routing), `WatcherManager` (hot-reload: `.reload(conn)` diffs `db.list_monitored_containers` against running asyncio tasks, `.pause()`/`.resume()`/`.is_paused`), `_watch_once()` (blocking docker-py log stream, run via `asyncio.to_thread`).
- Requires `docker==7.1.0` (already in `requirements.txt`) — not preinstalled in the workstation's global Python env; had to `pip install --break-system-packages docker==7.1.0` locally to run tests.
