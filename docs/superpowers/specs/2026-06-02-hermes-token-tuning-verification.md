# hermes token tuning — verification tracker

**Design spec:** `2026-06-02-hermes-token-tuning-design.md` (commit `f062480`)
**Implementation plan:** `docs/superpowers/plans/2026-06-02-hermes-token-tuning.md`
**Schema notes:** `hermes-agent/.notes/hermes-v2026.5.16-schema.md`
**Daily log entry:** `hermes-agent/.notes/daily_log.md` (2026-06-02 — Approach A token tune)
**Window opened:** 2026-06-02
**Window closes:** 2026-06-05
**Live config backup on NAS:** `/opt/data/config.yaml.bak-20260602` (inside `hermes_agent_data` volume)

## Applied changes (live + repo template)

| Key | Before | After |
|---|---|---|
| `session_reset.idle_minutes` | 1440 | 15 |
| `agent.max_turns` | 60 | 20 |
| `agent.api_max_retries` | 3 | 1 |
| `agent.image_input_mode` | auto | text |
| `memory.memory_enabled` | true | false |
| `memory.user_profile_enabled` | true | false |
| `compression.threshold` | 0.5 | 0.80 |

Repo template `hermes-agent/config.yaml.example` mirrors these (overrides only — live is a full hermes-generated dump).

## Baseline (2026-06-02, pre-tune)

| Metric | Value |
|---|---|
| Daily total tokens (mimo dashboard) | 35.6M |
| Cache hit | 1.3M (4%) |
| Cache miss | 33.7M |
| Iteration runaway events (≥ 60/60) | observed multiple |
| Idle reset (effective) | 1440 min (24h) — never honored |

Context from 2026-06-01 (last "good" day): 40.3M total, 32.2M cache hit (80%), 7.9M miss. The 80%→4% collapse is what triggered this tune.

## Targets (measured on mimo dashboard + hermes dashboard)

| Metric | Target |
|---|---|
| Daily total tokens | ≤ 15M |
| Cache hit ratio | ≥ 50% sustained |
| Idle reset (observed) | ≤ 15 min |
| Iteration runaway events | ≤ 1 / week |

## Check at +24h (2026-06-03)

| Metric | Observed | Pass? |
|---|---|---|
| Daily total tokens | _to fill_ | _to fill_ |
| Cache hit % | _to fill_ | _to fill_ |
| Idle reset (sample from hermes dashboard) | _to fill_ | _to fill_ |
| Runaway events | _to fill_ | _to fill_ |

Notes:

## Check at +72h (2026-06-05)

| Metric | Observed | Pass? |
|---|---|---|
| Daily total tokens | _to fill_ | _to fill_ |
| Cache hit % | _to fill_ | _to fill_ |
| Idle reset | _to fill_ | _to fill_ |
| Runaway events | _to fill_ | _to fill_ |

Notes:

## Decision at +72h

- [ ] All four targets hit → mark `memory.enabled` trial complete (decide keep-off vs restore); promote tune to permanent.
- [ ] 2–3 targets hit → keep config, extend window 7 days, re-check on 2026-06-12.
- [ ] ≤ 1 target hit → execute rollback below and re-enter brainstorming for Approach B (persona / prompt discipline).

## Rollback procedure

If the verification window concludes with insufficient improvement, restore the pre-tune live config and revert the repo commits:

```bash
# 1. Restore live config from backup
ssh nas 'sudo /usr/local/bin/docker exec hermes-gateway cp /opt/data/config.yaml.bak-20260602 /opt/data/config.yaml'

# 2. Validate YAML
ssh nas 'sudo /usr/local/bin/docker exec hermes-gateway python3 -c "import yaml; yaml.safe_load(open(\"/opt/data/config.yaml\")); print(\"OK\")"'

# 3. Full stack down/up (avoids the s6-log lock contention seen during the deploy)
ssh nas 'cd /volume2/docker/centralized-nas-container-management && sudo /usr/local/bin/docker compose -f hermes-agent/docker-compose.yml down && sudo /usr/local/bin/docker compose -f hermes-agent/docker-compose.yml up -d'

# 4. Confirm
ssh nas 'sudo /usr/local/bin/docker ps --filter name=hermes --format "table {{.Names}}\t{{.Status}}"'

# 5. Repo rollback (revert in reverse order of application)
git revert <commit-hash-of-notes>        # 5f0b74c (notes)
git revert <commit-hash-of-template>     # 157079b (config.yaml.example)
git revert <commit-hash-of-schema-notes> # 004c72e (schema notes)
git push
```

## Implementation summary (for future reference)

- Schema verified live on container (post-s6 migration, `HERMES_REF=v2026.5.29.2` — not v2026.5.16 as the original spec assumed). Most key names had been guessed wrong in the spec; reality is documented in the schema notes file.
- `sed -i` from a heredoc-written `/tmp/tune.sh` was the workable apply path (terminal-wrap issues in the user's mobile NAS shell broke direct multi-line paste of long `docker exec sed ...` commands).
- First restart hit `s6-log: Resource busy` on `/opt/data/logs/gateways/default/lock` — `docker compose restart` did not release the orphan lock. Full `down` + `up -d` cleared it. Worth pre-staging in the rollback command.
- The actual highest-impact key turned out to be `memory.memory_enabled` (not in the original spec at all) and `session_reset.idle_minutes` (in the spec but with the wrong key name). Cache hit improvement, if it materializes, will be driven by those two more than the iteration cap.
