# ops-bot Stack Index

## Purpose
AI-powered incident response bot: receives Uptime Kuma alerts, auto-diagnoses via SSH, analyzes with LLM (mimo-v2.5-pro), notifies Telegram with fix suggestions.

## Architecture
Two containers: `ops-bot-nginx` (nginx:alpine) publishes host port 5070→80 and
reverse-proxies to `ops-bot`, which only `expose`s 8000 and is never published.
Basic auth (`nginx/.htpasswd`, apr1, from vault `stacks.ops_bot.dashboard.*`) on
every path **except** `location = /webhook/uptime-kuma` — Uptime Kuma's webhook
notification cannot send basic auth, so that path is guarded by
`KUMA_WEBHOOK_SECRET` (`?secret=`, constant-time compare) instead. Keep that
vault key non-empty: `_verify_secret()` allows everyone when it is blank.

The FastAPI app itself has:
- Webhook endpoint for Uptime Kuma alerts
- SSH client (Paramiko) for NAS diagnostics
- LLM client (OpenAI SDK → mimo-v2.5-pro) driving an **agentic diagnosis loop** (native mimo function-calling) — replaced the old fixed `DIAGNOSTIC_STEPS` path (`app/diagnostics.py` removed 2026-07-24)
- Telegram Bot for notifications + live findings narration + InlineKeyboard fix confirmation
- SQLite for incident/diagnostic/analysis/action history
- Web dashboard for viewing past incidents (structured report render)

## Tech Stack
Python 3.12, FastAPI, Paramiko, OpenAI SDK, python-telegram-bot, aiosqlite, Jinja2, uvicorn

## Key Interfaces
- `get_config() -> Settings` (pydantic-settings, env from .env)
- `init_db() -> None`, `get_db() -> aiosqlite.Connection`
- `SSHClient.execute_command(command) -> SSHResult` (with command whitelist)
- `LLMClient.diagnose_agentic(service_name, execute, narrate) -> AgenticReport` — agent tool-use loop (mimo native function-calling), `MAX_ITERS = 10` cap, replaces old `analyze_diagnostic`/`LLMAnalysis`
  - Tools: `run_diagnostic(cmd)` (via `execute` → `ssh.execute_command`, whitelist enforced, read-only), `note_finding(text)` (→ `narrate` callback, live Telegram narration), `submit_report(...)` (final structured report, called once)
  - `AgenticReport` / `FixOption` dataclasses: `summary`, `severity`, `evidence`, `machine_status`, `fix_options` — stored as `analyses.report_json` (JSON), back-compat `root_cause`/`suggested_fix`/`fix_commands` columns still populated
  - If cap reached without `submit_report`: returns truncated/partial report instead of hanging
- `is_watchtower_update(container_name) -> bool`
- `handle_incident(service_name, container_name, status, alert_message) -> int`
- `execute_fix(incident_id, action_type) -> tuple[bool, str]`
- `POST /webhook/uptime-kuma` — Uptime Kuma webhook endpoint
- `start_telegram_polling()` / `stop_telegram_polling()` — Telegram command polling lifecycle
- `GET /dashboard` — incident list (last 50)
- `GET /dashboard/incident/{id}` — incident detail with diagnostics, analysis, actions

## Implementation Status
- [x] Task 1: Project Scaffolding + Config + DB (commit: a480f4d)
- [x] Task 2: SSH Client (commit: bd20402)
- [x] Task 3: LLM Client (commit: 6a0d477)
- [x] Task 4: Diagnostics Engine (commit: f46aebd)
- [x] Task 5: Watchtower Grace Period (commit: e6d3cd4)
- [x] Task 6: Telegram Bot (commit: 3e8f73e)
- [x] Task 7: Orchestrator (commit: 517c4cf)
- [x] Task 8: Webhook + Commands (commit: 327dad8)
- [x] Task 9: Dashboard (commit: 38b7b20)
- [x] Task 10: README + Deploy Prep (2026-07-24)
- [x] Agentic diagnosis: replaced fixed `DIAGNOSTIC_STEPS` with tool-use loop; `app/diagnostics.py` deleted (2026-07-24, commit: ef5da19)

## Deployment Fixes (2026-07-24)
- SSH key mount: `HOST_SSH_KEY_PATH` env var for volume mount, pydantic uses default `/app/data/ssh/id_ed25519`
- Uptime Kuma webhook: Optional models for null fields (test + Docker Container monitor)
- LLM: strip markdown code block wrapping before JSON parse
- Telegram: retry without Markdown on 400, no crash
- Timezone: `datetime('now', 'localtime')` in SQLite schema
- Container mapping: expanded `SERVICE_CONTAINER_MAP` for all services

## NAS Prerequisite (installed 2026-07-24)
- `/etc/sudoers.d/ops-bot-docker` (mode 440): `fixhardez ALL=(root) NOPASSWD: /usr/local/bin/docker`
- Reason: non-login SSH PATH lacks `/usr/local/bin`; `docker.sock` is root:root
- ssh_client rewrites `docker ...` → `sudo -n /usr/local/bin/docker ...` after whitelist check

## Verified Working (2026-07-24)
- End-to-end: Kuma webhook → SSH diagnostics (real docker output) → LLM analysis → dashboard (incident #13)
- `MIMO_BASE_URL` fixed to `/v1` in vault
- Timezone: tzdata added to Dockerfile — SQLite `localtime` now GMT+7 (incidents ≤13 stored in UTC, cosmetic)

## External Access (2026-07-26)
DSM Control Panel → Login Portal → Advanced → Reverse Proxy: `<NAS_DOMAIN>:15070`
(HTTPS) → `localhost:5070` (HTTP). DSM firewall is off, so WAN reach needs only
the router forward for TCP 15070. Gotchas: DSM prepends
`if ( $host !~ "(^<hostname>$)" ) { return 404; }` to each generated block, so a
hostname typo 404s every path and `curl https://localhost:15070/...` proves
nothing — test with `--resolve <NAS_DOMAIN>:15070:127.0.0.1`. LAN has no hairpin
NAT, so from inside the house the domain always gives `Connection refused`.
Status: **live and verified from WAN** (2026-07-26) — the entry originally had
two defects, a `sysnology` hostname typo and frontend port 15071 instead of
15070; both fixed in the GUI by the user. Cert is shared with the 15066
(friendly-reminder) entry. A tile now exists in `homepage/config/services.yaml`
(no `ping` key — basic auth returns 401, which homepage would render as down).
Inventory of live RP entries:
`sudo grep -E 'listen |proxy_pass' /etc/nginx/sites-enabled/server.ReverseProxy.conf`
(never hand-edit — DSM regenerates it).

## Known Gotchas
- nginx `location = /webhook/uptime-kuma` is an **exact** match. Kuma's stored `webhookURL` (in `kuma.db`, `notification.config` JSON) has no trailing slash, so it hits. A trailing slash or any path drift falls through to `location /`, gets basic auth, and 401s **silently** — Kuma just logs a failed notification and incidents stop arriving. Relax to a prefix match if that URL ever changes.
- `KUMA_WEBHOOK_SECRET` rides in a query param, so it lands in DSM's reverse-proxy access log in cleartext. Rotate it (`sops set` on `stacks.ops_bot.kuma_webhook_secret`, `make secrets`, redeploy) **and** update Kuma's notification config in the same pass, or the webhook 401s. Kuma has no API for this: stop the container, `sqlite3 ... UPDATE notification SET config = replace(...)`, start it.
- SSH exec has hard timeout (poll `exit_status_ready`, default 30s) — a wedged container's `docker inspect` can hang forever daemon-side; without the timeout it froze the whole event loop (recv_exit_status used to run on loop thread)
- Diagnostics templates use `str.replace("{container}", ...)`, NOT `.format()` — `.format()` collapsed docker Go templates `{{.Names}}` → `{.Names}`
- `Settings` needs `extra: "ignore"` — pydantic-settings forbids unknown keys in `.env` (`HOST_SSH_KEY_PATH`) otherwise
- Dashboard incident detail template uses named row access (`incident['service_name']`) — `SELECT *` positional indexing was off-by-one (kuma_event_id at index 1)
- tests/conftest.py isolates tests from rendered `.env` + closes global aiosqlite connection (non-daemon thread otherwise hangs pytest exit)

## Secrets
Via `secrets.manifest.yaml`:
- `MIMO_API_KEY`, `MIMO_BASE_URL`
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- `SSH_HOST`, `SSH_USER`, `SSH_PORT` (default 22, NAS uses 2222)
- `KUMA_WEBHOOK_SECRET`
- `DASHBOARD_BASIC_AUTH_USER`, `DASHBOARD_BASIC_AUTH_PASSWORD`
- `GITHUB_TOKEN` (fine-grained PAT, `contents:write` + `pull_requests:write`, this repo only)
- `GITHUB_REPO` (e.g., `FixHarDeZ/centralized-nas-container-management`)

## Fix-as-PR Interfaces
- `create_fix_pr(incident_id, title, file_changes) -> (ok: bool, url_or_err: str)` — GitHub REST API client, creates branch from main, commits file changes, opens PR, returns PR URL or error message
- `FixOption` dataclass: now includes `file_changes` field — a **list** of `{path, find, replace}` dicts (repo-relative path, exact string to find, replacement) for config/source fixes; empty for advisory/runtime-only options
- `build_report_keyboard(report, incident_id)` — builds Telegram InlineKeyboard with:
  - `🔍 Logs` button → `/logs` command (callback: `logs:{incident_id}`)
  - `🔧 เปิด PR` buttons for each FixOption with `file_changes` → (callback: `pr:{incident_id}:{fix_idx}`)
- Callback routing in `app/commands.py`:
  - `logs:{id}` → `/logs` handler
  - `pr:{id}:{idx}` → calls `create_fix_pr(incident_id, title, file_changes)` and sends result URL to Telegram
- DB schema: `actions` table tracks `action_type='open_pr'` with `result_output` = PR URL or error
