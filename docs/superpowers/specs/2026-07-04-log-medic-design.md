# log-medic Stack Design

**Date:** 2026-07-04
**Status:** Approved
**Location:** `log-medic/` inside `centralized-nas-container-management` repo
**Port:** 5070 internal / 15070 host

---

## Overview

A Docker Compose stack that tails logs of monitored Docker containers on the NAS, detects WARN/ERROR lines, deduplicates by fingerprint, and hands qualifying events to headless Claude Code for analysis. Depending on the target container's declared maturity, it either just records the event, sends a Telegram notification with root-cause analysis, or opens a GitHub PR with a proposed fix (never auto-merged). A web dashboard manages which containers are monitored and shows event history.

---

## Architecture

Single Python 3.12 container running FastAPI + APScheduler + asyncio watch tasks. SQLite for all persistence. Same shape as `torrentwatch/` and `news-feed/`.

```
log-medic/
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── secrets.manifest.yaml
├── README.md
├── requirements.txt
├── config.yaml            # seed only, read once if monitored_containers table is empty
├── prompts/
│   └── analyze.md         # template for phase 1 analyzer prompt
├── .notes/
└── app/
    ├── main.py             # FastAPI app + lifespan: starts watcher manager + scheduler
    ├── watcher.py           # per-container asyncio task: docker-py log stream, regex match, fingerprint
    ├── gate.py              # period / circuit-breaker / cooldown+quota / dirty-repo checks, in order
    ├── analyzer.py          # phase 1 (read-only) and phase 2 (fix+PR) `claude -p` invocations
    ├── notify.py            # Telegram Bot API send (reuses news-feed bot/chat)
    ├── db.py                # sqlite3 init_db() + helpers (no ORM)
    ├── scheduler.py         # APScheduler: daily_quota reset, 18:00 circuit-breaker digest, breaker auto-reset check
    ├── api/
    │   ├── containers.py    # GET/POST/PATCH/DELETE /api/containers
    │   ├── events.py        # GET /api/events
    │   ├── watcher_control.py # POST /api/watcher/{pause,resume}
    │   └── health.py        # GET /health
    └── static/
        ├── index.html       # Containers tab + Events tab
        └── app.js
```

**Docker Compose:**
- 2 services: `log-medic` (app) + `log-medic-nginx` (reverse proxy + Basic Auth), following the `friendly-reminder` pattern
- `log-medic` volumes: `log_medic_data:/data` (bind to `/volume2/docker/log-medic/data/`), `/var/run/docker.sock:/var/run/docker.sock:ro`, `/volume2/docker/log-medic/workspaces:/workspaces` (persistent git clones, read-write)
- `log-medic-nginx` mounts `nginx/nginx.conf` + `nginx/.htpasswd` (generated via `htpasswd -c`, credentials from vault), proxies to `log-medic:5070`, enforces `auth_basic` on `/` and `/api/*`
- Port: `15070` exposed on the nginx service, `log-medic` itself not host-published
- `env_file: .env`
- `restart: unless-stopped`
- `TZ: Asia/Bangkok`

The `/workspaces/<repo>/` clone is separate from the tar-deployed runtime tree used by `deploy.sh`. It is a fresh `git clone` of the GitHub remote, set up once during log-medic's own deploy, never recreated by the app. Analyzer runs `git fetch` before every use; never `git clone` at runtime.

**Dockerfile:** base image needs `python3.12`, `git`, `gh` CLI, and Node.js + `@anthropic-ai/claude-code` (npm global install) so `claude -p` is invokable. `mem_limit: 2g` on the `log-medic` service.

**Watcher resilience:** each container's asyncio task auto-reconnects on container restart; an exception in one container's task never crashes the process or other containers' tasks.

**Log context capture:** on regex match, `watcher.py` keeps a per-container ring buffer and captures the triggering line plus 30 lines before and 10 lines after it — this excerpt is what gets fingerprinted for context and shown in notifications/analyzer prompts (fingerprint hash itself still uses only the normalized trigger line, see Data Model).

---

## Data Model (SQLite at `/data/log-medic.db`)

```sql
CREATE TABLE monitored_containers (
    name            TEXT PRIMARY KEY,
    repo            TEXT,             -- e.g. /workspaces/centralized-nas-container-management, NULL if notify_only
    subdir          TEXT,             -- e.g. torrentwatch
    maturity        TEXT NOT NULL DEFAULT 'dev', -- dev | staging | stable; ignored when notify_only=1
    notify_only     INTEGER NOT NULL DEFAULT 0,
    paused          INTEGER NOT NULL DEFAULT 0,
    regex_override  TEXT,             -- NULL = default WARN|ERROR regex
    added_at        TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE TABLE events (
    fingerprint   TEXT NOT NULL,      -- sha256(container + normalized_message)[:12]
    container     TEXT NOT NULL,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    count         INTEGER NOT NULL DEFAULT 1,
    status        TEXT NOT NULL,      -- new | analyzed | notified | pr_opened | gated
    gate_reason   TEXT,               -- dirty_repo | cooldown | quota | circuit_breaker | NULL
    analysis      TEXT,               -- phase 1 output (root cause + proposed diff text)
    pr_url        TEXT,
    PRIMARY KEY (fingerprint, container)
);

CREATE TABLE daily_quota (
    date            TEXT PRIMARY KEY,  -- YYYY-MM-DD
    analyzed_count  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE circuit_breaker (
    container       TEXT PRIMARY KEY,
    tripped_at      TEXT NOT NULL,
    last_new_fp_at  TEXT NOT NULL
);

CREATE TABLE audit_log (
    ts       TEXT NOT NULL,
    action   TEXT NOT NULL,
    payload  TEXT
);
```

`config.yaml` is consulted only on first boot when `monitored_containers` is empty; after seeding, all changes go through the dashboard/API and are never written back to the YAML file.

---

## Watch → Gate → Act Pipeline

One asyncio task per monitored, unpaused container: `container.logs(stream=True, follow=True)` via `docker-py`, matched against the container's regex (or default `WARN|ERROR`) line by line. On match, fingerprint = `sha256(container + normalized_message)[:12]` (normalize before hashing: strip timestamps, UUIDs, bare numbers, hex addresses, memory addresses, and machine-specific paths, replacing each with a fixed placeholder token so transient values don't fragment the fingerprint).

**Hot reload:** every 30s, poll `monitored_containers`; diff against the running task set; start tasks for newly added/unpaused containers, cancel tasks for removed/paused ones. No service restart.

**Global pause** (`POST /api/watcher/pause` / `/resume`) is not a per-event gate — it controls whether watcher tasks run at all. While paused, no asyncio tasks are streaming logs, so no events are generated in the first place.

**Gate order, checked in this sequence per matched event:**
1. **Maturity** — `dev`-maturity containers are logged to `events` and nothing else; never reach any later gate or Claude/Telegram.
2. **Grace period** — if the container started or its image ID changed less than `GRACE_PERIOD_MINUTES` (default 20) ago (checked via `docker inspect` `State.StartedAt` / image ID, not a stored table), record event with `gate_reason=grace_period`, skip analyze/notify. Avoids noise storms from expected restart-time logging.
3. **Circuit breaker** — is this container's breaker tripped? If so, record event with `gate_reason=circuit_breaker`, skip Claude/Telegram.
4. **Cooldown / quota** — if fingerprint seen within last `COOLDOWN_HOURS` (default 6h), bump `count`/`last_seen`, no re-analyze. Else if `daily_quota.analyzed_count >= DAILY_QUOTA` (default 5), record event with `gate_reason=quota`, send a short Telegram notice, skip analyze.
5. **Dirty repo** — (stable/staging only, skipped for notify_only) checked against `/workspaces/<repo>`, any of these trips it (`gate_reason=dirty_repo`, notify, skip analyze):
   - `git status --porcelain` is non-empty (uncommitted changes)
   - current branch is not `main`/`master`
   - last commit is newer than `REPO_IDLE_HOURS` (default 2h) — someone else is actively developing
   - a `fix/<fingerprint>` branch for this exact fingerprint already exists (local or `origin`) — don't duplicate an open fix

If none of the gates trip, proceed to analyzer phase 1 — except for `notify_only` containers (e.g. jellyfin, which have no `repo`/`subdir`), which skip phases 1 and 2 entirely and go straight to a Telegram notification containing the raw log excerpt. `maturity` is ignored when `notify_only=1` (skips gate 1 and gate 5 too, since there's no repo to check).

**Circuit breaker trigger:** >`STORM_THRESHOLD_PER_HOUR` (default 10) new fingerprints for one container within a rolling 1h window trips that container's breaker (per-container, not system-wide). While tripped: Claude/Telegram calls for that container are skipped; events still land in `events` table. A daily digest at 18:00 summarizes tripped containers' fingerprint counts via Telegram regardless of breaker state. Breaker auto-resets when 6h pass with no new fingerprint for that container (checked by APScheduler job).

---

## Analyzer Phase 1 — read-only analysis (staging + stable)

Invocation: `claude -p "<rendered prompt>" --output-format json --max-turns 15`, restricted to `allowedTools: Read, Grep, Glob, Bash(git log:*, git diff:*)` — no Edit/Write.

`prompts/analyze.md` is rendered with: container name, log excerpt, repo path, subdir, service context (maturity, recent git log). Output parsed for: root cause summary, proposed diff (as text, not applied), confidence.

Result stored in `events.analysis`, status set to `analyzed`.

`dev`-maturity containers never reach this phase — gated at the maturity check before gate.4 (log only, no Claude call at all).

---

## Analyzer Phase 2 — fix + PR (stable only)

Gated by two independent switches, both required: container `maturity=stable`, AND system-wide env flag `ENABLE_FIX_RUNNER=true` (default `false` — the code path exists but is off until an operator opts in, regardless of any container's maturity). In the persistent clone:
1. `git fetch origin && git checkout -b fix/<fingerprint> origin/main` (never touches `main` directly, always branches from a freshly-fetched `origin/main`)
2. Re-invoke `claude -p` with `allowedTools` including `Edit, Write` this phase only, using phase 1's analysis as context. Prompt explicitly forbids editing `.env*`, `docker-compose*.yml`, `*.db` files and forbids running any `docker`/`docker compose` commands. No Bash tool at all this phase beyond what `git`/`gh` steps below need directly (not via Claude).
3. **Safety check before commit:** inspect the working tree diff — if it touches any forbidden file (`.env*`, `docker-compose*.yml`, `*.db`) or exceeds 200 changed lines, abort: discard the branch, record `gate_reason=fix_rejected` on the event, send a Telegram notice explaining why, do not commit/push/PR.
4. `git add -A && git commit`
5. `git push origin fix/<fingerprint>`
6. `gh pr create` with label `auto-fix` — PR body includes: log excerpt, root cause, what changed, how to test
7. Store `pr_url` in `events`, status `pr_opened`, Telegram notification with the PR link

No auto-merge, ever — a human merges or closes the PR. This is the only phase where Edit/Write tools are allowed, and only for `stable` containers with `ENABLE_FIX_RUNNER=true`.

`staging`-maturity containers (or `stable` with `ENABLE_FIX_RUNNER=false`) stop after phase 1: Telegram gets the root cause, no branch/PR.

---

## Dashboard + API

**Containers tab:** merged list of monitored + discovered-but-unmonitored (running containers not yet in `monitored_containers`). Add via dropdown of discovered names (validates container exists on docker + repo/subdir path exists on disk before insert). Edit maturity/paused/notify_only/repo/subdir inline. Pausing an already-unpaused (i.e. actively running) container requires a second confirm click.

**Events tab:** last 50 events, columns: time, container, fingerprint, count, status, gate_reason; row expands to show full analysis/log excerpt. Global watcher pause/resume button.

**API:**
- `GET /api/containers` — merged monitored + discovered
- `POST /api/containers` — add to monitoring, validates container + path exist
- `PATCH /api/containers/{name}` — update maturity/paused/notify_only/repo/subdir
- `DELETE /api/containers/{name}` — remove from monitoring (events history retained)
- `GET /api/events?limit=50&container=...`
- `POST /api/watcher/pause`, `POST /api/watcher/resume`

Every mutating call writes a row to `audit_log` (ts, action, payload).

**Security:** enforced at the nginx layer (`auth_basic` + `.htpasswd`, credentials from vault `stacks.log_medic.dashboard.{user,password}`) in front of both the dashboard and `/api/*`. This container holds a read-only docker socket and a GitHub PAT with repo push access — credential leak means repo compromise, so auth is non-negotiable even on the internal network.

---

## Notifications

Telegram only, reusing the existing `news-feed` bot/chat — no new channel created. Vault keys reused: `stacks.news_feed.telegram.bot_token`, `stacks.news_feed.telegram.chat_id` (mapped into log-medic's own env var names in `secrets.manifest.yaml`, same pattern `wallpaper-scout` uses).

---

## LLM Configuration

`claude -p` headless calls route through MiMo's Anthropic-compatible proxy, not the official Anthropic API — same pattern as `wallpaper-scout`:
- `ANTHROPIC_BASE_URL=https://token-plan-sgp.xiaomimimo.com/anthropic` (literal)
- `ANTHROPIC_API_KEY` sourced from vault `shared.mimo.anthropic_api_key` (existing key, no new secret)

---

## New Secrets Required

Add to `secrets/vault.sops.yaml` under `stacks.log_medic`:
- `dashboard.user`, `dashboard.password` — HTTP Basic Auth credentials
- `github_token` — PAT, `repo` scope, used for `git push` + `gh pr create` against this same repo

`secrets.manifest.yaml` for log-medic maps these plus reused `shared.mimo.anthropic_api_key` and `stacks.news_feed.telegram.{bot_token,chat_id}`.

---

## Configuration (literals, `.env` defaults)

Non-secret tunables, set as `literals:` in `secrets.manifest.yaml` (overridable per-deploy in `.env`):
- `ENABLE_FIX_RUNNER=false` — master kill switch for analyzer phase 2, see above
- `DAILY_QUOTA=5` — max phase-1 analyses per day, system-wide
- `COOLDOWN_HOURS=6` — per-fingerprint re-analyze suppression window
- `GRACE_PERIOD_MINUTES=20` — mute analyze/notify this long after a container starts/restarts or its image changes
- `STORM_THRESHOLD_PER_HOUR=10` — new fingerprints/hour that trips a container's circuit breaker
- `REPO_IDLE_HOURS=2` — dirty-repo gate treats a repo as "someone's actively developing" if last commit is newer than this

---

## Seed Config Example (`config.yaml`)

```yaml
containers:
  torrentwatch:
    repo: /workspaces/centralized-nas-container-management
    subdir: torrentwatch
    maturity: stable
  news-feed:
    repo: /workspaces/centralized-nas-container-management
    subdir: news-feed
    maturity: stable
  secretary:
    repo: /workspaces/centralized-nas-container-management
    subdir: secretary
    maturity: staging
  jellyfin:
    notify_only: true
```

`maturity` meaning:
- `dev` — log only, no Claude/Telegram call
- `staging` — phase 1 analyze + Telegram notify, no code edit
- `stable` — phase 1 + phase 2 (fix + PR, human-merged) — phase 2 additionally requires `ENABLE_FIX_RUNNER=true`

---

## Testing / Definition of Done

- `docker compose up -d --build` → `GET /health` returns 200
- Add a temporary `log-medic-test` container (`alpine sh -c "echo 'ERROR: explosion'; sleep 2"`), confirm event lands in SQLite and Telegram fires
- `dev`-maturity container throwing errors → event logged, zero Claude/Telegram calls made (verify against DB / mocked call count, not just absence of visible output)
- Container within `GRACE_PERIOD_MINUTES` of a (simulated) restart → event logged with `gate_reason=grace_period`, no Claude/Telegram call
- Dirty workspace (uncommitted change, or non-main branch, or stale last-commit, or existing `fix/<fp>` branch) → event logged with `gate_reason=dirty_repo` per condition, notified, no analyze
- `staging`-maturity container with a fixable error → analyzer runs, `gate_reason` is NULL, Telegram message contains root cause, no PR created
- `stable`-maturity container with `ENABLE_FIX_RUNNER=true` → PR opened during the analyzer run, `events.pr_url` populated, branch is `fix/<fingerprint>` off `origin/main`, not `main` itself
- `stable`-maturity container with `ENABLE_FIX_RUNNER=false` (default) → stops after phase 1 like `staging`, no branch/PR
- Add a container via the dashboard dropdown → appears in `monitored_containers` and the watcher picks it up within 30s without a service restart
- `GET /api/containers` without Basic Auth → 401

**Implementation branch policy:** all log-medic implementation commits go on `feat/log-medic`, never pushed directly to `main`; merge to `main` only once the DoD above passes end-to-end on the NAS.
