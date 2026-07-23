# ops-bot Daily Log

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
