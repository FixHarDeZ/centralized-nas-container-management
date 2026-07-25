# ops-bot Daily Log

## 2026-07-25 (fix-as-PR feature)

### Completed fix-as-PR workflow (Tasks 1–5 committed)
- Agentic report now emits structured `FixOption` objects with optional `file_changes` field (dict of file paths → proposed content for config/source fixes)
- Telegram report keyboard includes `🔧 เปิด PR` buttons for fixes with file_changes
- `create_fix_pr(incident_id, title, file_changes)` REST API client (GitHub fine-grained PAT) creates feature branch from main, commits file changes atomically, opens PR, returns URL
- Callback handler routes `pr:{id}:{idx}` to create_fix_pr, sends result URL back to Telegram
- DB audit row: `actions(action_type='open_pr', result_output=url)` for each PR opened
- Read-only constraint unchanged: bot has no SSH execution capability for fixes, stays read-only on NAS
- Tasks 1–5: Config + DB schema (Task 1), agentic report FixOption (Task 2), create_fix_pr REST impl + tests (Task 3), Telegram buttons (Task 4), callback + audit (Task 5)

### Docs Phase (Task 6, this session)
- Updated README: added "Fix-as-PR" section explaining the flow, deployment, vault keys
- Updated `.notes/00_INDEX.md`: added github secrets (GITHUB_TOKEN, GITHUB_REPO) and fix-as-PR interfaces (create_fix_pr signature, FixOption.file_changes, build_report_keyboard, pr: callback, actions audit)
- Updated root CLAUDE.md ops-bot row: appended "Fix-as-PR: proposes config fixes as GitHub PRs (read-only on NAS)" note

## 2026-07-24 (agentic diagnosis)

### Replaced fixed-diagnostic path with agentic tool-use loop
- `app/llm_client.py`: `LLMClient.diagnose_agentic()` drives an agent loop against mimo (native OpenAI-style function-calling), replacing the old fixed `DIAGNOSTIC_STEPS` sequence + separate `analyze_diagnostic()` pass
- Three tools exposed to the model: `run_diagnostic(cmd)` (routes through existing `ssh.execute_command`, whitelist unchanged — still read-only), `note_finding(text)` (live Thai-language narration, streamed to Telegram as it happens), `submit_report(...)` (final structured report, called once)
- Loop capped at `MAX_ITERS = 10`; if the model never calls `submit_report`, returns a truncated/partial `AgenticReport` instead of hanging or erroring
- New `AgenticReport` / `FixOption` dataclasses hold the structured result: `summary`, `severity`, `evidence`, `machine_status`, `fix_options` — stored as `report_json` on `analyses` (plus back-compat columns `root_cause`/`suggested_fix`/`fix_commands` still populated for old dashboard/Telegram code paths)
- `app/orchestrator.py` calls `diagnose_agentic(execute=, narrate=)` — `narrate` callback pushes each `note_finding` straight to Telegram so the incident channel shows live progress, not just a final blob
- Telegram + dashboard render the new structured report (summary/severity/evidence/machine_status/fix_options) instead of the old single root_cause/suggested_fix text
- Deleted `app/diagnostics.py` (old `run_diagnostics`/`DIAGNOSTIC_STEPS`/`find_compose_file`) and `tests/test_diagnostics.py` — no remaining importers (verified via grep), full suite (31 tests) passes, `import app.main` clean
- Commits: `refactor(ops-bot): remove fixed-diagnostic module (replaced by agentic loop)`

## 2026-07-24 (afternoon — verify + fix session)

### Bugs found via incident pages #4/#5
- Dashboard incident detail: `SELECT *` returns 8 cols (kuma_event_id at idx 1) but template indexed as 7 → Service=None, Time=0, Watchtower read alert_message. Fixed: named row access (`incident['service_name']`)
- SSH diagnostics all failed `docker: command not found`: non-login SSH PATH lacks `/usr/local/bin`, and docker.sock is root:root. Fixed: ssh_client rewrites `docker ...` → `sudo -n /usr/local/bin/docker ...` (after whitelist check) + installed `/etc/sudoers.d/ops-bot-docker` NOPASSWD entry on NAS
- Diagnostics Go templates broken: `.format()` collapsed `{{.Names}}` → `{.Names}`. Fixed: `str.replace("{container}", ...)` instead
- Event loop freeze: `recv_exit_status`/`read` ran on loop thread — hung `docker inspect` froze whole app (dashboard dead). Fixed: full exec in executor + hard deadline poll on `exit_status_ready`
- Webhook: `{"invalid": "data"}` returned `test_ok` (both fields default None). Fixed: reject payloads with neither `heartbeat` nor `monitor` key. Also deleted 45 lines dead duplicated code after `return`
- Timezone still UTC despite `datetime('now','localtime')`: python:3.12-slim lacks tzdata → TZ ignored. Fixed: apt install tzdata in Dockerfile. Rows ≤ #13 remain UTC (cosmetic)
- Tests: added `tests/conftest.py` — isolate from rendered `.env` (real KUMA secret caused 401s, SSH_PORT=2222 broke defaults) + close global aiosqlite conn (non-daemon thread hung pytest exit). `Settings` got `extra: "ignore"` (HOST_SSH_KEY_PATH in .env tripped pydantic-settings forbid). 46 tests pass

### Real infra incident found + fixed during verify
- news-feed container wedged 3 weeks (unhealthy): containerd shim alive with zero children — `docker inspect news-feed` hung forever (this is what Kuma's "timeout of 48000ms" DOWN alerts were about, and what froze ops-bot). 12 hung `docker inspect` processes piled up (Kuma + ops-bot)
- Fix: pkill hung inspects, kill -9 shim → still wedged daemon-side → `synopkg restart ContainerManager` (all containers restarted cleanly) → `docker start news-feed` → healthy
- E2E verified on incident #13: correct header, real docker output in all diagnostic steps, sensible LLM analysis (7517 tokens), dashboard responsive throughout

## 2026-07-24

### SSH Port + README Update
- Added `SSH_PORT` to `secrets.manifest.yaml` → maps to `stacks.ops_bot.ssh.port` in vault
- Updated README to reflect actual architecture:
  - Key-based auth only (not password as previously documented)
  - Custom SSH port support (default 22, NAS uses 2222)
  - Added debounce, dashboard auth, webhook security sections
  - Added architecture diagram and security notes
- Vault key needed: `stacks.ops_bot.ssh.port` = `2222`
- Added `SSH_KEY_PATH` as literal in manifest → `/var/services/homes/fixhardez/.ssh/id_ed25519`
- Fixed: container start failed because SSH key wasn't mounted (default path `/root/.ssh/id_ed25519` didn't exist on NAS)
- Fixed: Uptime Kuma test notification 422 error — Kuma sends `{"heartbeat": null, "monitor": null}` for test, Pydantic model now accepts Optional fields
- Added test case for null heartbeat/monitor (test notification)
- Fixed: production DOWN alerts returning 422 — switched from Pydantic auto-validation to manual `Request` body parsing with error logging
- Now logs raw body for debugging when validation fails
- Fixed: SSH key mount — removed broken `~/.ssh` default fallback, requires `SSH_KEY_PATH` in `.env`
- Fixed: timezone — changed `CURRENT_TIMESTAMP` → `datetime('now', 'localtime')` in all DB schemas
- Known issue: `MIMO_BASE_URL` in vault is `/anthropic` (404), should be `/v1`
- Fixed: Kuma Docker Container monitor sends `hostname: null` and `port: null` — made fields Optional in KumaMonitor model
- Added test case for null hostname/port
- Fixed: LLM response markdown-wrapped JSON (````json ... ````) — added regex strip before json.loads
- Fixed: Telegram 400 error crashes app — now retries without Markdown parse_mode, logs error instead of raising
- Added SERVICE_CONTAINER_MAP for all known services (News Feed, Homepage, Ink Reader, etc.)
- Fixed: SSH key mount collision — `SSH_KEY_PATH` env var was overriding pydantic config `ssh_key_path` field, making it point to host path instead of container path (`/app/data/ssh/id_ed25519`)
- Renamed to `HOST_SSH_KEY_PATH` for docker-compose volume mount, pydantic config uses default `/app/data/ssh/id_ed25519`

## 2026-07-23

### Task 3: LLM Client (DONE)
- Created `app/llm_client.py` — LLMClient using mimo-v2.5-pro via OpenAI SDK
  - `LLMAnalysis` dataclass: root_cause, severity, suggested_fix, fix_commands, tokens_used
  - `analyze_diagnostic(service_name, diagnostic_results)` → calls mimo API, parses JSON response
  - System prompt in Thai for Docker diagnostics on Synology NAS
  - Fallback handling for JSON parse errors
  - `get_llm_client()` singleton accessor
- Created `tests/test_llm_client.py` — 2 tests passing
  - `test_llm_analysis_dataclass` — dataclass creation
  - `test_analyze_diagnostic_returns_analysis` — mocked AsyncOpenAI call with JSON response
- Commit: `6a0d477 feat(ops-bot): add LLM client for mimo diagnostic analysis`
- All 8 existing tests pass (config, db, ssh_client, llm_client)

### Task 2: SSH Client (DONE)
- Created `app/ssh_client.py` — SSHClient with Paramiko + command whitelist
  - `SSHResult` namedtuple: stdout, stderr, exit_code
  - `ALLOWED_PREFIXES`: docker ps/logs/inspect/restart, compose logs/restart, df, free, uptime, curl, etc.
  - `is_allowed(command)` — prefix-based whitelist check
  - `execute_command(command, timeout)` — async SSH execution with whitelist guard
  - Key-first auth with password fallback
  - `get_ssh_client()` singleton accessor
- Created `tests/test_ssh_client.py` — 3 tests passing
  - `test_ssh_result` — namedtuple creation
  - `test_allowed_commands` — whitelist allow/block checks
  - `test_execute_blocked_command` — blocked command returns exit_code=-1
- Commit: `bd20402 feat(ops-bot): add SSH client with command whitelist`
- Fixed Python 3.9 type annotation compat in config.py + db.py (X | None → Optional[X])

### Task 8: Webhook Handler + Telegram Commands (DONE)
- Created `app/webhook.py` — Uptime Kuma webhook endpoint
  - `KumaWebhook`, `KumaHeartbeat`, `KumaMonitor` Pydantic models
  - `POST /webhook/uptime-kuma` — accepts alerts, filters for DOWN (status=0), runs `handle_incident` in background
  - `SERVICE_CONTAINER_MAP` for service→container name resolution
  - `get_container_name()` with fallback to lowercase-hyphenated service name
- Created `app/commands.py` — Telegram polling + command handlers
  - `start_telegram_polling()` / `stop_telegram_polling()` — lifecycle hooks for FastAPI lifespan
  - `_poll_loop()` — long-poll Telegram getUpdates with 30s timeout
  - `_handle_update()` — routes messages and callback_queries
  - `_handle_status()` — `/status` shows all container statuses via `docker ps -a`
  - `_handle_diagnose()` — `/diagnose <service>` triggers manual `handle_incident`
  - `_handle_logs()` — `/logs <container> [lines]` shows recent logs (max 200)
  - `_handle_callback()` — InlineKeyboard callbacks for fix/restart/logs buttons
- Created `tests/test_webhook.py` — 2 tests passing
  - `test_webhook_endpoint` — POST with valid Kuma payload → 200, handle_incident called
  - `test_webhook_rejects_invalid` — POST with missing fields → 422
- Fixed: FastAPI returns 422 (not 400) for Pydantic validation errors
- Commit: `327dad8 feat(ops-bot): add webhook handler and Telegram commands`
- All 17 tests pass

### Task 9: Web Dashboard (DONE)
- Created `app/dashboard.py` — FastAPI router with Jinja2 templates
  - `GET /dashboard` — lists last 50 incidents (id, service, container, status, watchtower, time)
  - `GET /dashboard/incident/{id}` — detail view with diagnostics, analysis, actions
  - Uses positional tuple indexing for aiosqlite.Row access (inc[0], inc[1], etc.)
- Created `app/templates/dashboard.html` — dark theme table with severity badges
- Created `app/templates/incident_detail.html` — incident detail with diagnostic cards, analysis, action history
- Added `from __future__ import annotations` for Python 3.9 compat
- Commit: `38b7b20 feat(ops-bot): add web dashboard for incident history`

## 2026-07-26 — nginx basic-auth sidecar + DSM reverse proxy diagnosis

**Problem reported:** `https://<NAS_DOMAIN>:15070/dashboard` unreachable while
`http://192.168.50.200:5070/dashboard` worked.

**Root cause (two defects in one DSM RP entry):**
1. Hostname typo — entry said `fixhardez.sysnology.me`. DSM generates
   `if ( $host !~ "(^<hostname>$)" ) { return 404; }` at the top of every RP
   server block, so every path 404'd with a healthy backend. Proven by curling
   with the *misspelled* host via `--resolve` → 200.
2. Frontend port was `15071`, not `15070`. Nothing ever listened on 15070
   (`rp15070root=000`), so the "root works" observation was the app's own 404
   on `/` seen over LAN, not proof the proxy worked.

Inspect RP entries from the NAS shell (root-read; `/usr/syno/etc/www/ReverseProxy.json`
is empty on DSM 7.4):
`sudo grep -E 'listen |proxy_pass' /etc/nginx/sites-enabled/server.ReverseProxy.conf`
Fix in the GUI only — DSM regenerates that file. DSM firewall is off
(`firewall_settings.json` = `status:false`), so WAN reach depends only on the
router port-forward. LAN has no hairpin NAT, so `<NAS_DOMAIN>:<port>` from
inside always gives `Connection refused` — only mobile data tests it.

**Blocker found while answering:** the dashboard had *no auth at all* despite
the README claiming otherwise — compose published 5070 straight to the app, and
`POST /webhook/uptime-kuma` was world-writable. Exposing it to WAN would have
published SSH diagnostic output, container names, and LLM fix commands, and let
anyone forge incidents (SSH runs + LLM spend + Telegram spam).

**Fix shipped:**
- `nginx/nginx.conf` — nginx:alpine sidecar `ops-bot-nginx`, basic auth on `/`,
  `location = /webhook/uptime-kuma` exempt (Kuma's webhook notification can't
  send basic auth; app already verifies `?secret=` in constant time). Same split
  friendly-reminder uses for its LINE webhook.
- `nginx/.htpasswd` — apr1, generated from `.env` (`stacks.ops_bot.dashboard.*`,
  already in the vault/manifest but previously unused by anything).
- `docker-compose.yml` — app `ports: 5070:8000` → `expose: 8000`; nginx holds
  `5070:80`; watchtower disabled on the sidecar too.

**Verified on NAS after deploy:** `noauth_dash=401`, `auth_dash=200`,
`webhook_nosecret=401`, `webhook_secret=200`.

**Not broken by this:** every Uptime Kuma monitor is `type=docker`, none HTTP —
checked `monitor` table in `/volume2/docker/uptime-kuma/kuma.db`. No homepage
widget hits 5070 either.

**Left to the user (GUI/router, can't be done over SSH):** fix the RP entry
hostname + port to `<NAS_DOMAIN>` / `15070`, rebind a cert covering that
hostname (the existing `ReverseProxy_2979f8fa-…` cert was issued while the
hostname was misspelled), forward TCP 15070 on the router, then test from mobile
data. Also update the Kuma webhook URL to include `?secret=…` if it doesn't.
