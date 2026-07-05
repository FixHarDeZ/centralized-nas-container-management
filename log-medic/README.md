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
merged with running-but-undiscovered containers) and Events tab (last 50 events).
Protected by nginx Basic Auth.
