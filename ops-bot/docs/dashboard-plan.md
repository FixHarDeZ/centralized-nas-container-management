# Ops-bot dashboard implementation plan

Approved direction: responsive charcoal/teal dashboard, searchable incident history,
report detail, persistent MiMo model selection and bounded diagnosis requests.

Architecture: retain FastAPI/Jinja/SQLite. Shared template and local static assets;
a settings module owns model persistence. Snapshot the effective model once per
agent run and persist provenance in report_json. Keep nginx basic auth and
read-only diagnostics. Historical DOWN events are not live outage indicators.

## Tasks
- [x] Settings: add SQLite settings table, validated model override and reset to
  environment default. POST JSON requires same-origin Origin and custom header.
  Model discovery is optional, explicit, bounded and fails without exposing secrets.
- [x] LLM: read settings at each run; remove max_tokens; reasoning_effort=low;
  asyncio.wait_for bounds the entire run to 600 seconds; disable SDK retries;
  include model_used in all completed/partial reports and stored report_json.
- [x] Dashboard: shared responsive navigation, summary of historical events,
  search + severity filter + pagination; report summary/evidence/fix options,
  collapsible logs and actions; settings form with save/reset/error feedback.
- [x] Verify: settings persistence/reset/invalid writes/CSRF, filtering/pagination,
  missing incident, old report rendering, model snapshot across setting changes,
  timeout cancellation and request parameters. Run full stack suite, inspect
  desktop/mobile rendered pages, review diff, update README and stack memory.

Tests run with `.venv/bin/python -m pytest tests -q` from ops-bot.
Use temporary SQLite databases and mocked provider/SSH/Telegram only; no live
alerts, model spending or deployment during verification. Production rollout
remains separate; this work produces a reviewable local implementation.

Result: 60 stack tests pass; desktop/mobile browser interactions checked; independent
review completed (HTML pattern escaping corrected). No commit, push or deployment.
