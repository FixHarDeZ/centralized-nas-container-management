# log-medic

Monitors Docker container logs on the NAS, detects WARN/ERROR lines, fingerprints
and deduplicates them, and — depending on the target container's declared
maturity — either just records the event, sends a Telegram notification with
root-cause analysis (via headless Claude Code), or opens a GitHub PR with a
proposed fix (`stable` maturity + `ENABLE_FIX_RUNNER=true` only; never auto-merged).

## Maturity levels
- `dev` — log only, no Claude/Telegram call.
- `staging` — root-cause analysis + Telegram notify, no code edit.
- `stable` — analysis + notify, and (if `ENABLE_FIX_RUNNER=true`) opens a PR.

## Gate order (per matched log line)
1. Maturity (`dev` stops here) / `notify_only` (bypasses everything else)
2. Grace period — `GRACE_PERIOD_MINUTES` after container start/restart or image change
3. Circuit breaker — `STORM_THRESHOLD_PER_HOUR` new fingerprints/hour trips it; auto-resets after 6h quiet
4. Cooldown/quota — `COOLDOWN_HOURS` per fingerprint, `DAILY_QUOTA` analyses/day system-wide
5. Dirty repo — uncommitted changes, non-main branch, stale commits (`REPO_IDLE_HOURS`), or an existing `fix/<fp>` branch

## One-time setup before first deploy
1. `make edit-vault` — add `stacks.log_medic.dashboard.{user,password}` and `stacks.log_medic.github_token`.
2. `htpasswd -c log-medic/nginx/.htpasswd <user>` locally (gitignored, not committed).
3. On the NAS: `git clone <remote> /volume2/docker/log-medic/workspaces/centralized-nas-container-management` — the app only ever runs `git fetch` there, never `git clone`.

## Dashboard
`https://<nas>:15070/` — Containers tab (add/pause/remove monitored containers,
merged with running-but-undiscovered containers) and Events tab (last 50 events,
including a Verdict column). Protected by nginx Basic Auth.

## Close the loop
Status flow: `new → analyzed → pr_opened → merged → deployed | deploy_failed`
(plus `pr_closed`, and the existing `gated`, `notified`).

- **Verdict triage** — `prompts/analyze.md` requires the analysis to emit
  `VERDICT: code` or `VERDICT: infra` as its mandatory first line.
  `analyzer.parse_verdict()` extracts it (fail-safe: unparseable/missing text
  defaults to `infra` so a malformed response never triggers the fix runner),
  stored in `events.verdict`. Telegram root-cause message shows `🐛 code` /
  `🌐 infra`. The fix runner only fires when `maturity=="stable" AND
  ENABLE_FIX_RUNNER=true AND verdict=="code"` — infra issues get analysis +
  notify only, never a fix branch.
- **Merge poll** — scheduler job `poll_pr_merges` runs every 5 min: for each
  event at status `pr_opened`, `gh pr view --json state,mergedAt`. `MERGED` →
  status `merged` + auto-deploy. `CLOSED` → status `pr_closed`, best-effort
  delete the remote `fix/<fp>` branch, Telegram "🚮 PR closed without merge".
  `OPEN` → left as-is. Per-event errors are logged and retried next cycle —
  never crash the job.
- **Auto deploy** (`app/deployer.py`) — sync the workspace clone to
  `origin/main` → copy only git-tracked files from the stack subdir into
  `/stacks/<stack>/` (never deletes, so `.env`/`data/`/`.htpasswd` on the NAS
  are structurally safe) → `docker compose up -d --build` via the mounted
  socket → wait 60s, verify the container is `Running` and `RestartCount`
  hasn't increased → status `deployed` (🚀 Telegram) or `deploy_failed`
  (❌ Telegram).
- **`deploy_failed` is terminal** — no auto-retry. Recovery is manual:
  `git revert` the fix commit and merge the revert PR, which the same loop
  then deploys.
- **Self-deploy guard** — a PR merged for log-medic itself is not
  auto-deployed (self-restart mid-deploy would kill the deploy process).
  Notifies "deploy manually from the workstation" and leaves status `merged`.
