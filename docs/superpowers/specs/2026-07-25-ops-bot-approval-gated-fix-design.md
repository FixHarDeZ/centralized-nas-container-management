# ops-bot Approval-Gated Fix Execution — Design Spec (Phase 2)

**Date:** 2026-07-25
**Stack:** `ops-bot/`
**Status:** Approved design, pending implementation plan
**Builds on:** Phase 1 agentic diagnosis (`2026-07-24-ops-bot-agentic-diagnosis-design.md`)

## Goal

Let the operator execute an incident's suggested fix from Telegram — running the
LLM's `fix_options[].commands` — but with a human confirming **every write
command** before it runs. Read-only verification commands auto-run; mutating
commands pause for explicit approval; catastrophic commands are refused outright.

Target UX (from user screenshots): the diagnosis report shows fix options
("ตัวเลือก 1 ⭐", "ตัวเลือก 2"); tapping one steps through its commands, running
reads automatically and asking `✅ รัน / ❌ ข้าม / ⛔ ยกเลิก` before each write
(e.g. edit compose `mem_limit 3g→5g`, then `docker compose up -d`).

## Decisions (from brainstorming)

1. **What can execute:** the LLM's `fix_options[].commands` directly (option C) —
   full flexibility, but **every write command requires per-command human
   confirmation**.
2. **Read vs write:** a command that passes the existing read-only whitelist
   (`SSHClient.is_allowed`) auto-runs; anything else is a write and must be
   confirmed. Reuses the Phase-1 hardened whitelist as the read/write classifier.
3. **Confirmation UX:** sequential, one Telegram prompt per write command, with
   the command shown and `✅ รัน / ❌ ข้าม / ⛔ ยกเลิกทั้งหมด` buttons. Each
   command's result is shown before the next is offered.
4. **Catastrophic deny-list:** irreversible commands are blocked outright — no
   confirm button offered — as defense-in-depth against LLM hallucination and
   fat-finger.
5. **Fix option selection:** one Telegram button per `fix_option`; the operator
   picks which option to run.

## Architecture

### Trigger (`telegram_bot.py`)

`send_incident_report` keyboard gains one button per `fix_option`:
- `🔧 ทำตัวเลือก {n}{" ⭐" if recommended}` → `callback_data = "fix:{incident_id}:{option_idx}"`
- The existing `📋 ดู Logs เพิ่มเติม` button (`logs:{incident_id}`) stays.

### Fix session (`fix_executor.py`, new module)

In-memory session state (mirrors the `_last_alert` debounce dict pattern):

```python
_fix_sessions: dict[str, dict] = {}   # sid -> {incident_id, container, commands, index}
```

- `sid` is a short unique id (e.g. `f"{incident_id}-{option_idx}-{short_uuid}"`),
  kept small enough that `frun:{sid}` fits Telegram's 64-byte callback_data.
- `start_fix_session(incident_id, option_idx) -> sid | None`: load the incident's
  `report_json` from `analyses`, take `fix_options[option_idx].commands`, create a
  session, then drive it to the first stopping point.
- `step_session(sid)`: advance from `index` through the command list:
  - **catastrophic** (`is_catastrophic(cmd)`) → send "❌ ปฏิเสธอัตโนมัติ", record an
    `actions` row (success=False), **abort the whole session**.
  - **read-only** (`ssh.is_allowed(cmd)`) → `execute_command`, show result, record
    action, continue.
  - **write** → send the per-command confirm prompt, store `index`, **pause**
    (return; wait for a callback).
  - end of list → send "✅ เสร็จสิ้น", clear session.
- `run_confirmed(sid)`: `execute_write` the current command, show result, record
  action, advance (`index += 1`), then `step_session`.
- `skip_current(sid)`: record a skipped action, advance, `step_session`.
- `cancel_session(sid)`: clear session, send "⛔ ยกเลิกแล้ว".

### Write-execution path (`ssh_client.py`)

New method `execute_write(command, timeout=30) -> SSHResult`, distinct from the
read-only `execute_command`:

1. `is_catastrophic(command)` → if True, return `SSHResult("", "blocked: catastrophic", -1)` without touching SSH.
2. sudo-rewrite `docker …` → `sudo -n /usr/local/bin/docker …` (the NOPASSWD
   sudoers entry already permits any docker subcommand, including `restart` /
   `compose up`). Non-docker writes (e.g. `sed -i`) run unprivileged as the SSH
   user `fixhardez`, who owns `/volume2/docker/*` but cannot touch root-owned
   files — a real privilege boundary.
3. exec via the existing `_exec_blocking` (executor thread + hard timeout).

`execute_write` does **not** call `is_allowed` — that gate is read-only. Its
guards are the deny-list plus the human confirmation upstream.

### Deny-list (`fix_executor.py` or `ssh_client.py`)

`is_catastrophic(command) -> bool` — matches irreversible/destructive patterns,
blocked regardless of confirmation:

- `rm -rf` targeting a volume root or `/` or `~` (`/`, `/volume1`, `/volume2`, `~`, `$HOME`)
- `dd `, `mkfs`, `fdisk`, `parted`, disk format
- fork bomb `:(){`, `shutdown`, `reboot`, `halt`, `poweroff`, `init 0`, `init 6`
- writes to devices: `> /dev/`, `of=/dev/`
- recursive perm/owner on root: `chmod -R 777 /`, `chown -R … /`
- `docker volume rm`, `docker system prune`, `docker rmi` (image/volume deletion)
- `truncate`, `mv … /dev/null`, `:> ` device/root clobber
- command substitution `$(`, backtick, `${` (block obfuscation on the write path too)

Fixes that are allowed (reversible) and only need confirmation: `docker restart`,
`docker compose up -d`, `docker start/stop`, `sed -i` value edits, `docker exec`.

### Callback routing (`commands.py`)

`_handle_callback` (currently handles only `logs:`) gains:
- `fix:{incident_id}:{option_idx}` → `start_fix_session(...)`
- `frun:{sid}` → `run_confirmed(sid)`
- `fskip:{sid}` → `skip_current(sid)`
- `fcxl:{sid}` → `cancel_session(sid)`

Authorization is unchanged — `_handle_update` already ignores callbacks from any
chat other than the whitelisted `telegram_chat_id`.

### Audit (`db.py` — no schema change)

Every executed command (auto-run read, confirmed write, skipped, or catastrophic
refusal) writes an `actions` row: `action_type` ("fix_read" | "fix_write" |
"fix_skipped" | "fix_denied"), `commands_executed`, `result_output`, `success`.

## Testing

`tests/test_fix_executor.py` (new) + additions to `tests/test_ssh_client.py`:

- `is_catastrophic`: True for `rm -rf /`, `rm -rf /volume2`, `dd if=…`, `mkfs…`,
  `shutdown`, `docker volume rm x`, `docker system prune`, `$(…)`; False for
  `docker restart x`, `docker compose up -d`, `sed -i 's/3g/5g/' x`.
- `execute_write`: catastrophic → `exit_code == -1`, SSH never called (mock);
  docker command → sudo-rewritten; non-docker command → run as-is.
- session stepper (mock `execute_command`/`execute_write`/telegram/db):
  - read-only command auto-runs and advances;
  - write command pauses and emits a confirm prompt;
  - catastrophic command mid-list aborts the session;
  - `run_confirmed` executes via `execute_write`, records an action, advances;
  - two consecutive writes each require their own confirm.
- callback routing: `fix:5:0` starts a session; `frun:<sid>` runs; `fcxl:<sid>` aborts.

## Out of scope (YAGNI / later)

- Automatic rollback on failure.
- Dry-run / diff preview before execution.
- Triggering fixes from the web dashboard (Telegram only).
- Persisting fix-session state across container restarts (in-memory; restart
  mid-fix → operator restarts the fix).
