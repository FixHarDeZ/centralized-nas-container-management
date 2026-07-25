# ops-bot Fix-as-PR — Design Spec (Phase 2)

**Date:** 2026-07-25
**Stack:** `ops-bot/`
**Status:** Approved design, pending implementation plan
**Builds on:** Phase 1 agentic diagnosis (`2026-07-24-ops-bot-agentic-diagnosis-design.md`)

> **Supersedes** the earlier execute-on-NAS draft of this spec. The bot does NOT
> execute fix commands on the NAS. It proposes fixes as **GitHub pull requests**;
> a human reviews, merges, and deploys. The bot stays read-only on the NAS.

## Goal

Let the operator turn an incident's suggested fix into a reviewable **GitHub PR**
from Telegram. The bot reads the live config during diagnosis, produces a
repo-relative source change, opens a PR via the GitHub REST API, and replies with
the PR URL. The human reviews + merges on GitHub, then deploys with the normal
`make secrets` / `deploy.sh` flow.

## Why PR-based, not execute-on-NAS

`deploy.sh` tars the git repo over the NAS files, so a fix applied directly on the
NAS (e.g. `sed -i` on a live `docker-compose.yml`) is **ephemeral** — the next
deploy reverts it, and the live NAS drifts from git. Persistent config/source
fixes must go through git. Runtime-only actions (restart) are intentionally out of
scope — the operator does those manually; they are not a source change.

## Decisions (from brainstorming)

1. **Fix model:** git-PR only. No command execution on the NAS. Bot remains
   read-only there (Phase 1 whitelist unchanged).
2. **Delivery:** a real GitHub PR (not a Telegram patch) — branch + commit(s) +
   PR via GitHub REST API; human merges + deploys.
3. **Repo access:** pure GitHub REST API over httpx (existing dep). No local
   checkout, no `git` binary, no age key in the container.
4. **New capability:** opening a PR on one repo. Human merge is the gate. No
   push-to-main, no auto-merge, no auto-deploy.

## Architecture

### New secret (add via `adding-vault-secret` skill)

- `stacks.ops_bot.github.token` — fine-grained PAT scoped to this repo only:
  `contents:write` + `pull_requests:write`. Nothing else.
- `stacks.ops_bot.github.repo` — `owner/repo`.

Config (`config.py`): `github_token: str = ""`, `github_repo: str = ""`.
Manifest (`secrets.manifest.yaml`): `GITHUB_TOKEN`, `GITHUB_REPO`.

### Report schema change (`llm_client.py`)

`FixOption` gains a `file_changes` field:

```
file_changes: [{path: str, find: str, replace: str}]
```

- `path` — repo-relative (e.g. `homepage/docker-compose.yml`).
- `find` — the exact current substring in that file.
- `replace` — the new substring.

The existing `commands` field stays for display/context but is never executed. A
fix_option that carries `file_changes` is "PR-able"; one without is advisory only
(shown as text, no PR button — e.g. "restart the container yourself").

`submit_report`'s tool schema adds `file_changes` (array of {path, find, replace},
all optional) inside each fix_option. `parse_report` maps it onto `FixOption`.

### Diagnosis prompt update (`llm_client.py` SYSTEM_PROMPT)

Instruct the model: when a fix is a config/source change, `cat` the live file
first (read-only, already whitelisted), then express the fix as `file_changes`
with a **repo-relative** path and an exact find/replace — NOT as a `sed`/shell
command on the NAS. Give the mapping: NAS `/volume2/docker/<x>/…` ⇄ repo `<x>/…`.

### GitHub client (`github_client.py`, new)

`create_fix_pr(incident_id: int, title: str, file_changes: list) -> tuple[bool, str]`
returns `(success, pr_url_or_error_message)`. Pure REST via httpx, base
`https://api.github.com/repos/{owner}/{repo}`, auth `Authorization: Bearer <token>`:

1. GET `/git/ref/heads/{default_branch}` → base sha. (Default branch from GET
   `/repos/{owner}/{repo}` or config; use `main`.)
2. POST `/git/refs` → create branch `fix/incident-{id}-{shortslug}` at base sha.
3. For each change: GET `/contents/{path}?ref={branch}` → current content (base64)
   + blob sha. Decode, verify `find` is present (else abort with a clear error),
   apply `find`→`replace`, PUT `/contents/{path}` with the new content, the blob
   sha, and `branch` → one commit per file.
4. POST `/pulls` (head=branch, base=default) → PR. Return `html_url`.

Errors (find-not-found, file 404, API 401/403/rate-limit) return
`(False, <thai message>)` and open no PR (best-effort: a partially-created branch
is harmless — left for cleanup or reuse).

### Telegram flow (`telegram_bot.py`)

`send_incident_report` keyboard: one button per fix_option **that has
`file_changes`** — `🔧 เปิด PR: {title}` → `callback_data = "pr:{incident_id}:{idx}"`.
Options without `file_changes` get no button. The existing
`📋 ดู Logs เพิ่มเติม` button stays.

### Callback routing (`commands.py`)

`_handle_callback` gains `pr:{incident_id}:{idx}`: load the incident's
`report_json`, take `fix_options[idx]`, call
`create_fix_pr(incident_id, title=option.title, file_changes=option.file_changes)`,
reply `✅ เปิด PR แล้ว: {url}` or `❌ {error}`. Authorization is unchanged
(`_handle_update` already restricts to the whitelisted `telegram_chat_id`).

### Audit (`db.py` — no schema change)

Each PR attempt writes an `actions` row: `action_type="open_pr"`,
`commands_executed` = JSON of the file_changes, `result_output` = PR URL or error,
`success`.

## Testing

`tests/test_github_client.py` (new) + updates to `test_llm_client.py`,
`test_telegram_bot.py`, `test_commands.py` (or `test_webhook.py` if that's where
callback tests live):

- `create_fix_pr` with httpx mocked:
  - happy path: ref → create-branch → get-contents → put-contents → create-pr →
    returns `(True, html_url)`; assert the branch/PR calls carry the right sha/branch.
  - `find` not present in fetched content → `(False, msg)`, no PUT, no PR.
  - file 404 → `(False, msg)`.
  - multi-file change → one PUT per file, single PR.
  - API 401 → `(False, msg)`.
- `FixOption` parses `file_changes`; `submit_report` schema accepts it;
  `parse_report` tolerates fix_options with no `file_changes` (advisory).
- Telegram: a PR button appears only for options with `file_changes`; the callback
  data is `pr:{id}:{idx}`.
- callback routing: `pr:5:0` → `create_fix_pr` called with option 0's title +
  file_changes; an `actions` row is written.

## Out of scope (YAGNI / later)

- Executing anything on the NAS (dropped entirely).
- Auto-merge, auto-deploy after merge, rollback.
- Multi-repo, GitHub Actions/CI wiring.
- Branch cleanup of abandoned fix branches.
