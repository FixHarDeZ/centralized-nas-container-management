# ops-bot Stack Index

## Purpose
AI-powered incident response bot: receives Uptime Kuma alerts, auto-diagnoses via SSH, analyzes with LLM (mimo-v2.5-pro), notifies Telegram with fix suggestions.

## Architecture
Single FastAPI container (port 5070→8000) with:
- Webhook endpoint for Uptime Kuma alerts
- SSH client (Paramiko) for NAS diagnostics
- LLM client (OpenAI SDK → mimo-v2.5-pro) for root cause analysis
- Telegram Bot for notifications + InlineKeyboard fix confirmation
- SQLite for incident/diagnostic/analysis/action history
- Web dashboard for viewing past incidents

## Tech Stack
Python 3.12, FastAPI, Paramiko, OpenAI SDK, python-telegram-bot, aiosqlite, Jinja2, uvicorn

## Key Interfaces
- `get_config() -> Settings` (pydantic-settings, env from .env)
- `init_db() -> None`, `get_db() -> aiosqlite.Connection`
- `SSHClient.execute_command(command) -> SSHResult` (with command whitelist)
- `LLMClient.analyze_diagnostic(service_name, diagnostic_results) -> LLMAnalysis`
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
- [ ] Task 10: README + Deploy Prep

## Secrets
Via `secrets.manifest.yaml`:
- `MIMO_API_KEY`, `MIMO_BASE_URL`
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- `SSH_HOST`, `SSH_USER`, `SSH_PASSWORD`
- `DASHBOARD_BASIC_AUTH_USER`, `DASHBOARD_BASIC_AUTH_PASSWORD`
