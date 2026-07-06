# log-medic — Close the Loop: Triage → Merge Poll → Auto Deploy

**Date:** 2026-07-05
**Status:** Approved (design), pending implementation plan
**Builds on:** `2026-07-04-log-medic-design.md` (v1, deployed pipeline: watch → gate → analyze → notify → PR)

## Problem

v1 pipeline ends at "PR opened". Three gaps versus the intended operator flow:

1. **No triage.** Every analyzed event on a `stable` container with `ENABLE_FIX_RUNNER=true` triggers the fix runner, even when the root cause is infrastructure (network blip, external API down) and no code change can help. Wastes a Claude phase-2 run and a quota slot.
2. **No merge detection.** After the PR notification, log-medic never learns the PR was merged. Event status parks at `pr_opened` forever.
3. **No deploy.** Even after a merge, the fixed code never reaches the running container — the NAS runtime dirs (`/volume2/docker/<stack>/`) are populated by `deploy.sh` tar uploads from the workstation, not by git.

## Decisions (made during brainstorming)

| Question | Decision |
|---|---|
| How does log-medic learn a PR was merged? | **Poll GitHub** via `gh pr view` on a scheduler interval. No Telegram inbound — the operator merges on GitHub (the PR link is already in the Telegram message). |
| How does merged code reach the runtime dir? | **Copy from the existing workspace clone** into `/volume2/docker/<stack>/`, then `docker compose up -d --build` through the already-mounted Docker socket. |
| What happens if a deploy fails? | **Verify + notify only.** No auto-rollback. Recovery is manual: fix forward or revert on the workstation, then redeploy manually (`./scripts/deploy.sh`). |

## Gap 1 — Triage verdict (`code` vs `infra`)

### Prompt change (`prompts/analyze.md`)

Add a mandatory first line to the response format:

```
VERDICT: code
```
or
```
VERDICT: infra
```

Definitions given to the model:
- `code` — root cause lives in the service's source in this repo; a code change can fix it.
- `infra` — network failure, external API outage/rate-limit, disk/permission problem, runtime config issue; a code change cannot fix it.

### Parsing (`app/analyzer.py`)

`analyze()` extracts the verdict from the first line of the model's response
(case-insensitive match on `^VERDICT:\s*(code|infra)`), strips that line from the
analysis text, and returns `{"text", "excerpt", "verdict"}`.

**Fail-safe:** unparseable or missing verdict → `"infra"`. A malformed response
must never trigger the fix runner.

### Routing (`app/watcher.py` `process_event`)

Fix-runner condition changes from:

```python
maturity == "stable" and ENABLE_FIX_RUNNER
```

to:

```python
maturity == "stable" and ENABLE_FIX_RUNNER and analysis["verdict"] == "code"
```

`infra` events on stable containers behave exactly like `staging` events today:
analysis + Telegram notification, no fix attempt.

### Storage & display

- `events` table gains a `verdict TEXT` column (nullable; backfill not needed —
  old rows stay NULL). Added via `ALTER TABLE` guard in `db.init_db` (same
  pattern as any additive migration; SQLite tolerates re-running with a
  `duplicate column` catch).
- Telegram root-cause message prefixes the verdict: `🐛 code` / `🌐 infra`.
- Dashboard Events tab shows the verdict column (plain text, no new filter UI).

## Gap 2 — Merge detection (GitHub polling)

### New scheduler job (`app/scheduler.py`)

`poll_pr_merges` — `IntervalTrigger(minutes=5)`, registered in `setup_scheduler`
alongside the existing jobs.

Per run:
1. Query events with `status='pr_opened'`.
2. For each, `gh pr view <pr_url> --json state,mergedAt` (runs in the event's
   workspace dir; `GITHUB_TOKEN` and `gh` binary already present from v1's
   `run_fix`).
3. Route on `state`:
   - `MERGED` → set status `merged` → call `deployer.deploy(...)` (Gap 3)
     synchronously in the job.
   - `CLOSED` → set status `pr_closed` → delete the remote fix branch
     (`git push origin --delete fix/<fp>`, best-effort) → notify
     `🚮 PR closed without merge for <container>, no deploy`.
   - `OPEN` → leave as-is.
4. `gh` failure for one event: log, skip, retry next cycle. Never crash the job.

At most a handful of PRs are ever open at once (daily quota is 5), so one
sequential pass is fine.

## Gap 3 — Auto deploy (`app/deployer.py`, new module)

`deploy(container_row, event) -> bool` — called only from `poll_pr_merges` after
a merge is detected.

### Guard: self-deploy

If the target stack is log-medic itself, restarting the container would kill the
deploy mid-flight. Detect (stack subdir == `log-medic`) → notify
`⚠️ PR merged for log-medic itself — deploy manually from the workstation` →
set status `merged` (terminal for this event) → return without deploying.

### Steps

1. **Sync workspace:**
   `git checkout -B main origin/main && git fetch origin && git reset --hard origin/main`
   in the workspace dir (same idiom `run_fix` already uses for cleanup).
2. **Copy tracked files only:** enumerate `git ls-files -z <subdir>` in the
   workspace, copy each file to `/stacks/<stack>/` preserving relative paths
   (create parent dirs as needed). Copying only git-tracked files guarantees the
   deploy can never touch `.env`, `data/` volumes, `nginx/.htpasswd`, or SQLite
   files living in the runtime dir. Deleted-in-git files are NOT removed from the
   runtime dir (acceptable: stale files are inert; `deploy.sh` full uploads
   reconcile eventually).
3. **Rebuild:**
   `docker compose --project-directory /stacks/<stack> -f /stacks/<stack>/docker-compose.yml up -d --build`
   via the mounted Docker socket. Timeout 10 minutes.
4. **Verify:** sleep 60 s → `docker inspect` the monitored container:
   - `State.Running == true` and `RestartCount` has not increased since
     immediately post-`up` → success.
5. **Report:**
   - Success → status `deployed`, notify `🚀 Deployed <container> (PR merged: <url>)`.
   - Any step fails → status `deploy_failed`, notify
     `❌ Deploy failed for <container> at step <step>: <error excerpt>` with the
     manual-recovery hint (fix forward or revert on the workstation, then redeploy
     manually). No rollback.

### Interaction with existing gates (free wins)

- Post-deploy restart puts the container in the 20-minute **grace period** —
  boot noise won't re-alert.
- If the fix was wrong and the same error recurs, the 6-hour **cooldown** on the
  fingerprint prevents an immediate re-fix storm; `check_dirty_repo`'s
  `fix/<fp>` branch check also blocks re-fix while the old branch lingers.

## Status flow (updated)

```
new → analyzed ──(stable + fix runner + verdict=code)──→ pr_opened ──→ merged → deployed
                                                              │            │        └(fail)→ deploy_failed
                                                              └→ pr_closed └(self)→ merged (terminal)
```

`gated` unchanged. `analyzed` remains terminal for `staging`, infra verdicts, and
rejected fixes.

## Infrastructure changes

| File | Change |
|---|---|
| `docker-compose.yml` | Add volume `/volume2/docker:/stacks` (rw). Socket mount unchanged. |
| `Dockerfile` | Add docker CLI + compose plugin (static binaries from download.docker.com, pinned version — same install style as the pinned `gh` tarball). |
| `secrets.manifest.yaml` | No change — `GITHUB_TOKEN` already provisioned. |

## Error handling summary

| Failure | Behavior |
|---|---|
| Verdict line missing/malformed | Treat as `infra`, no fix attempt |
| `gh pr view` fails | Log, retry next 5-min cycle |
| Workspace sync fails | `deploy_failed` + notify, PR stays merged (manual re-trigger = re-run job naturally does NOT retry; operator deploys manually) |
| Compose build/up fails or times out | `deploy_failed` + notify |
| Container not running / restart-looping after 60 s | `deploy_failed` + notify |
| Target is log-medic itself | Skip deploy, notify manual instruction |

Note: `deploy_failed` is terminal — the poll job only looks at `pr_opened`, so a
failed deploy is never retried automatically. Deliberate: repeated failed deploys
against a live service are worse than one Telegram ping asking a human.

## Testing

- **Unit:** verdict parsing (valid/missing/garbage), fix-runner routing on
  verdict, `poll_pr_merges` state routing (MERGED/CLOSED/OPEN/gh-error) with
  mocked `subprocess`, deployer step ordering + failure short-circuits with
  mocked `subprocess`/docker client, self-deploy guard, tracked-files copy
  (tmpdir git repo fixture: `.env` in dest survives, tracked file updated).
- **On-NAS DoD (manual, gates real use):** merge a trivial PR for a `staging`→
  temporarily-`stable` test container → observe poll → deploy → 🚀 notify →
  container restarted with new code.

## Out of scope

- Auto-rollback (decided against — manual revert-and-merge path).
- Telegram inbound of any kind.
- Deploying stacks whose repo ≠ this monorepo (workspace/subdir model already
  assumes this repo).
- Removing git-deleted files from runtime dirs during deploy.
