# hermes-agent token tuning — Approach A (Config diet)

**Date:** 2026-06-02
**Stack:** `hermes-agent/`
**Pinned hermes ref:** `v2026.5.16`
**Provider/model lock:** mimo-v2.5-pro (no switching allowed in this scope)

## Problem

On 2026-06-02 a single hermes-agent session burned 35.6M tokens for a task that amounted to a small docker-compose edit + a daily-log update + git rebase conflict resolution. The mimo provider dashboard shows cache hit rate collapsed day-over-day:

| Date | Total tokens | Cache hit | Cache miss | Hit ratio |
|---|---|---|---|---|
| 2026-06-01 | 40.3M | 32.2M | 7.9M | **80%** |
| 2026-06-02 | 35.6M | 1.3M | 33.7M | **4%** |

The 80% → 4% drop means the request prefix that mimo had been caching is no longer stable between turns. Combined with runaway iteration loops (sessions hitting 60/60 iterations on small tasks) and long idle-but-not-reset sessions, hermes is paying for re-processing the same prefix on nearly every call.

## Goal

Reduce token consumption holistically — cache hit rate, total daily tokens, session bloat — by tuning `config.yaml` only. No source patches, no provider switch, no persona/prompt rewrite (those are reserved as escalation paths if Approach A is insufficient).

**Success criteria** (measured 3 days post-deploy):
- Cache hit rate ≥ 50% sustained on the mimo dashboard
- Total daily tokens ≤ 15M (down from 35.6M baseline)
- Session idle reset observed at ≤ 15 min
- Iteration runaway (≥ 60/60) events ≤ 1 per week

If targets not met after 3 days, escalate to Approach B (persona/prompt discipline) — out of scope here.

## Scope

**In scope:**
- Edit `/opt/data/config.yaml` on NAS (volume-persistent live config)
- Edit `hermes-agent/config.yaml.example` in the repo (template for future deploys)
- Update `hermes-agent/.notes/00_INDEX.md` change log + `daily_log.md` entry
- Backup live config before mutation
- Validate YAML before reload (prior incident in change log: malformed YAML silently used empty model)

**Out of scope:**
- Switching model or provider (locked to mimo-v2.5-pro)
- Patching Hermes source code (upstream-update risk)
- Persona / system prompt rewrite (Approach B)
- Splitting chat/task into separate session types (Approach C)
- Rebuilding the Docker image (config-only change does not need it)

## Architecture

Single-file change, no image rebuild:

```
hermes-agent/config.yaml.example   ← template in repo (committed)
                │ (manual mirror — not auto-mounted)
                ▼
NAS: /opt/data/config.yaml         ← live config inside hermes_agent_data volume
                │
                ▼
hermes-gateway container reload     ← docker compose restart hermes-gateway
```

The live config is **inside a named volume** (`hermes_agent_data`), not bind-mounted from the repo. The repo template and the live file must be mirrored by hand. The deploy procedure below covers this explicitly.

No impact on `hermes-dashboard` or `hermes-nginx` services. No secrets-vault changes.

## Pre-design verification gate

Before committing to specific config keys, the schema of `v2026.5.16` must be confirmed, because `config.yaml.example` in the repo only shows `model`, `telegram`, `discord`, and `session.reset_on_idle_minutes`. Tier 2 / Tier 3 keys below are speculative until verified.

Run on NAS before editing:

```bash
ssh nas
sudo docker exec hermes-gateway hermes config --help 2>&1 | head -100
sudo docker exec hermes-gateway find /opt/hermes -name "*.py" \
  -exec grep -l "reset_on_idle\|max_iterations\|max_turns\|max_tokens\|memory\b\|vision\b\|auto_compact" {} \;
sudo docker exec hermes-gateway cat /opt/hermes/hermes_cli/config*.py 2>&1 | head -300
```

Outcome decides Tier 2 / Tier 3 inclusion below.

## Config changes

### Tier 1 — confirmed exists (apply unconditionally)

| Key | Current | New | Rationale |
|---|---|---|---|
| `session.reset_on_idle_minutes` | 60 | **15** | Zombie sessions persisting across the day are the primary source of prefix shift. 15 min covers normal conversational continuation; longer gaps are usually a new task context anyway. |

### Tier 2 — apply if schema verifies (likely exists)

| Key (candidate) | Proposed value | Rationale |
|---|---|---|
| `session.max_iterations` (or `agent.max_iterations`) | **20** | Session logs surface `iteration N/60` — a 60-iteration cap exists somewhere. Most real tasks finish in < 10; > 20 is runaway and should hand control back to the user. |
| `model.max_tokens` (or `output.max_tokens`) | **2000** | Cap response length. mimo-v2.5-pro normally answers in 200–800 tokens; 2000 leaves headroom for structured replies and prevents rambling. |
| `memory.enabled` (if exists) | **false** for a one-week trial | If hermes injects long-term memory into the system prompt each turn, the prefix changes per request → guaranteed cache miss. Disable temporarily; re-enable if user notices loss of persona/preferences. |

### Tier 3 — speculative (apply only if grep finds them)

- `tools` whitelist → restrict to the tool set actually used. Smaller and more stable tool list = smaller, more cacheable system prompt.
- `vision.max_images_per_session: 1` (or equivalent) → vision tokens are not cached and are expensive. Keep one screenshot, drop subsequent re-sends.
- `auto_compact` / `compression` → if hermes triggers context compaction at long contexts, disable. Compaction generates a fresh prefix and destroys cache; better to hit the idle-reset boundary than to silently compact.

### Decision tree after verification

- Tier 2 keys missing → ship Tier 1 only; still expected to reduce session bloat 30–50%.
- Tier 2 keys present → expected reduction ~50%+.
- Tier 3 keys also present → expected reduction ~70%+.

### Value justifications

- **15 min idle reset:** human conversational gaps are typically < 10 min; > 15 min is overwhelmingly a topic change.
- **20 iteration cap:** observed runaway sessions in the 2026-06-02 log used 19–20 iterations on small tasks and still didn't finish — that's the boundary where escalation to the human is cheaper than continuing.
- **2000 max output tokens:** mimo response distribution in normal use is 200–800; 2000 keeps structured/long replies viable and clips the long tail.

## Deploy procedure

```bash
# 1. Update template in repo
$EDITOR hermes-agent/config.yaml.example
git add hermes-agent/config.yaml.example hermes-agent/.notes/
git commit -m "tune(hermes): tighten session reset and iteration caps to control mimo token bleed"
git push

# 2. Backup live config on NAS
ssh nas
sudo docker exec hermes-gateway cp /opt/data/config.yaml \
     /opt/data/config.yaml.bak-$(date +%Y%m%d)

# 3. Edit live config on NAS (volume-persistent, not bind-mounted)
sudo docker exec -it hermes-gateway vi /opt/data/config.yaml

# 4. Validate YAML before reload
sudo docker exec hermes-gateway python3 -c \
  "import yaml,sys; yaml.safe_load(open('/opt/data/config.yaml')); print('YAML OK')"

# 5. Restart gateway
cd /volume2/docker/centralized-nas-container-management
sudo docker compose -f hermes-agent/docker-compose.yml restart hermes-gateway

# 6. Confirm config loaded
sudo docker logs hermes-gateway --tail 50 | grep -iE "config|session|model"
```

## Verification window (3 days)

| Metric | Baseline (2026-06-02) | Target | Source |
|---|---|---|---|
| Cache hit rate | 4% | ≥ 50% sustained | mimo provider dashboard |
| Total daily tokens | 35.6M | ≤ 15M | mimo provider dashboard |
| Session idle reset (observed) | 60 min | 15 min | hermes-dashboard session list |
| Iteration runaway (≥ 60/60) | observed multiple times | ≤ 1 / week | hermes-dashboard log |

If after 3 days targets are not met, escalate to Approach B (persona/prompt discipline). Do not silently push further config tweaks beyond what is in this design — re-enter brainstorming.

## Rollback

```bash
# Live config rollback (~1 minute)
ssh nas
sudo docker exec hermes-gateway cp \
     /opt/data/config.yaml.bak-YYYYMMDD /opt/data/config.yaml
sudo docker compose -f /volume2/docker/centralized-nas-container-management/hermes-agent/docker-compose.yml \
     restart hermes-gateway

# Repo rollback
git revert <commit-hash>
git push
```

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Tier 2 / Tier 3 keys do not exist in v2026.5.16 — hermes silently ignores them | High (~50%) | Verification gate before deploy; restrict to verified keys. |
| `reset_on_idle_minutes: 15` is too aggressive and degrades UX | Medium | Roll back to 30 first; only return to 60 if 30 also degrades. |
| `memory.enabled: false` causes loss of persona / saved preferences | Medium | One-week trial; revert if user-visible regression. |
| Malformed YAML → container fails to start (prior incident in change log) | Low | Pre-reload YAML validate step in deploy procedure. |
| mimo provider changes cache policy independently (the 80→4% drop may be partly provider-side) | Medium | Outside our control; accept some hit-rate fluctuation; surface in verification window note if visible. |

## Notes follow-up

After deploy, update:
- `hermes-agent/.notes/00_INDEX.md` — Configuration section: new values + verification status of each Tier 2 / Tier 3 key (present / absent / TBD).
- `hermes-agent/.notes/daily_log.md` — entry describing the change, what was verified, and a 3-day reminder for the verification window.
