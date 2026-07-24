# ops-bot Agentic Diagnosis — Design Spec (Phase 1)

**Date:** 2026-07-24
**Stack:** `ops-bot/`
**Status:** Approved design, pending implementation plan

## Goal

Replace ops-bot's fixed-script diagnosis with an **agentic tool-use loop**: mimo
decides diagnostic commands iteratively, narrates key findings live to Telegram,
and produces a structured multi-section report. **Read-only throughout — no fix
execution** (that is Phase 2).

Target UX (from user screenshots): Uptime Kuma DOWN alert → bot investigates
step-by-step, posting short Thai findings as it discovers them ("เจอแล้ว —
restart-loop exit 137", "ชัดเจน — OOMKilled: true"), then a final report with an
evidence table, machine-status note, and recommended fix options presented as
text (no buttons in Phase 1).

## Background: current architecture (being replaced)

- `diagnostics.py` runs a **fixed** `DIAGNOSTIC_STEPS` list (docker ps/inspect/
  logs, df, free, uptime, compose logs) all at once.
- `llm_client.analyze_diagnostic()` makes **one** mimo call over the whole batch,
  returns a single JSON `LLMAnalysis`, parsed by stripping markdown code fences
  (regex, brittle).
- `telegram_bot.send_incident_report()` sends **one** message at the end.
- The LLM never chooses commands, never iterates, never narrates.

Decision: **fully replace** this path (no fallback, no toggle). If mimo fails,
the incident is still recorded and Telegram gets a "วิเคราะห์ไม่ได้" error — the
existing error-handling pattern in `orchestrator.py`.

## Verified constraint

mimo (`mimo-v2.5-pro` via `xiaomimimo.com/v1`, OpenAI-compatible) **supports
native OpenAI function-calling**. Probe on 2026-07-24 returned a proper
`tool_calls` entry (`run_cmd({"cmd":"docker ps"})`). So the agent loop uses
native tool-calling — no ReAct text protocol needed.

Note: when mimo emits a `tool_call`, the assistant `content` is **empty**. This
is why narration must be an explicit tool (`note_finding`), not scraped from
message content.

## Architecture

### Component 1 — `LLMClient.diagnose_agentic()`

New method, replaces `analyze_diagnostic()`. Runs the agent loop with three tools
exposed to mimo:

| Tool | Signature | Effect |
| :--- | :--- | :--- |
| `run_diagnostic` | `(cmd: str)` | Route through existing `ssh_client.execute_command` (read-only whitelist enforced). Return stdout/stderr/exit_code as the tool result. |
| `note_finding` | `(text: str)` | Forward `text` to Telegram immediately (live narration). Tool result = ack. |
| `submit_report` | structured (see Report schema) | Terminal tool. mimo calls it once with the final structured report; loop ends. |

Loop:
1. Seed messages: system prompt (agentic, Thai, read-only) + user message
   (service name, container name, alert message).
2. Call mimo with `tools=[...]`, `tool_choice="auto"`.
3. For each `tool_call` returned:
   - `run_diagnostic` → execute via SSH, append result as `role:"tool"` message,
     persist a `diagnostics` row (`step_name` = the command).
   - `note_finding` → send Telegram, append ack as tool message.
   - `submit_report` → parse into report object, **exit loop**.
4. Repeat until `submit_report` OR iteration cap (**10**) reached.

**Security:** even though mimo picks the commands, every `run_diagnostic` is gated
by the existing `ALLOWED_PREFIXES` whitelist in `ssh_client.py`. A blocked command
(e.g. `docker restart`) returns "not allowed", which is fed back as the tool
result; mimo adapts. Read-only cannot be escaped via the loop.

### Component 2 — Narration mechanism

Option B (findings-only). The `note_finding` tool is the sole narration channel.
System prompt instructs mimo: *"เมื่อเจอเบาะแสสำคัญ ให้เรียก note_finding ด้วย
ข้อความไทยสั้นๆ ก่อนตรวจต่อ"*. Routine commands stay silent. Deterministic —
does not depend on assistant `content` (which is empty during tool calls).

### Component 3 — `orchestrator.handle_incident()`

Replace the `run_diagnostics()` + `analyze_diagnostic()` sequence with a single
`diagnose_agentic()` call. The loop internally persists `diagnostics` rows and
sends `note_finding` narrations. On completion:
- persist the structured report to `analyses` (see storage),
- send the final report to Telegram.

Watchtower grace-period skip and the incident record creation stay unchanged.

### Component 4 — Report structure (option C)

`submit_report` tool schema (mimo fills it — structured output, no markdown
parsing):

```
summary        : str                 # สรุปสาเหตุ (prose)
severity       : "critical" | "warning" | "info"
evidence       : [{factor: str, value: str}]     # ตาราง "ปัจจัย / ค่า"
machine_status : str                 # e.g. "เครื่องไม่มีปัญหา — disk 53%, load 1.37"
fix_options    : [{title: str, recommended: bool, detail: str, commands: [str]}]
```

`evidence` rows are factor/value only (no icon/color).

### Component 5 — Storage (`analyses` table)

- Add column `report_json TEXT` — stores the whole structured report.
- Keep existing columns for the incident-list view (no change to `dashboard.py`
  list query): `severity` = report.severity, `root_cause` = report.summary,
  `suggested_fix` = recommended fix option's `detail`.
- `fix_commands` / `safety_note` columns: retained but unused (no migration/drop).
- `llm_tokens_used` = sum of tokens across all loop iterations.

### Component 6 — Telegram final report rendering

Sections in order: summary → evidence (monospace aligned table in a ``` block) →
machine_status → fix options (⭐ marks `recommended`, commands in code block).
Text only — **no inline buttons** in Phase 1. Uses existing `send_message`
(Markdown with plaintext-retry fallback).

### Component 7 — Dashboard `incident_detail.html`

Render from `report_json`: summary, an evidence `<table>`, machine_status, and
fix-option cards. Incidents without `report_json` (pre-migration) fall back to
the existing field rendering.

### Component 8 — SSH client

Unchanged. Read-only whitelist already present; the agent's `run_diagnostic` tool
routes through `execute_command`, so the whitelist is the last line of defense.

## Error handling

| Case | Behavior |
| :--- | :--- |
| mimo picks non-whitelisted command | `execute_command` returns "not allowed" → fed back as tool result → mimo adapts. No crash, read-only intact. |
| Iteration cap (10) hit without `submit_report` | Send Telegram note "⚠️ ถึงเพดานรอบ วิเคราะห์ไม่ครบ" + report from findings gathered so far (minimal report if none). |
| mimo error / timeout | Persist incident, send Telegram "❌ วิเคราะห์ไม่ได้" (existing orchestrator pattern). |
| SSH command hangs | Existing hard timeout (poll `exit_status_ready`); timeout error fed back to mimo. |
| `submit_report` schema incomplete | Fallback minimal report (severity=warning, summary=raw). |

## Testing

`tests/test_llm_client.py` / `tests/test_orchestrator.py`, mimo mocked:
- Happy path: mock tool-call sequence `run_diagnostic` → `note_finding` →
  `submit_report`. Assert command routed through whitelist, finding sent to
  Telegram, report parsed and stored.
- Blocked command: mimo requests `docker restart` → assert whitelist rejects,
  error fed back, loop continues.
- Cap hit: 10 iterations without `submit_report` → assert partial report + note.
- mimo raises → assert fallback report + Telegram error.
- Reuse existing `conftest.py` isolation (env + aiosqlite cleanup).

## Out of scope (Phase 2 / YAGNI)

- Approval buttons and fix execution (compose edit, `docker compose up -d`).
- Any write path / whitelist expansion beyond read-only.
- Mode toggle or fallback to the old fixed-diagnostic path.
- Token-by-token streaming.

## Cost / latency

Agentic = multiple mimo calls per incident (~4–5 typical, cap 10). ~15–20k tokens
worst case, latency ~15–25s. Accepted tradeoff for the richer real-time UX.
