# hermes-agent token tuning (Approach A — config diet) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drive hermes-agent mimo cache hit rate from 4% back toward ≥50% and cut total daily tokens from 35.6M to ≤15M by tightening `config.yaml` only.

**Architecture:** Config-only change. Schema-verify hermes v2026.5.16 on NAS first, then mirror approved keys into both repo template (`hermes-agent/config.yaml.example`) and live config (`/opt/data/config.yaml` inside the `hermes_agent_data` volume). Restart `hermes-gateway` only — no image rebuild, no dashboard/nginx touch.

**Tech Stack:** Docker Compose, hermes-agent v2026.5.16, mimo-v2.5-pro via OpenRouter, YAML configuration. NAS access via `ssh nas` (key-based) + `sudo /usr/local/bin/docker` (sudo requires user-supplied password — never hardcode).

**Spec:** `docs/superpowers/specs/2026-06-02-hermes-token-tuning-design.md` — commit `f062480`.

---

## File map

| File | Change | Purpose |
|---|---|---|
| `hermes-agent/.notes/hermes-v2026.5.16-schema.md` | Create | Record which Tier 2/Tier 3 config keys exist in pinned hermes ref |
| `hermes-agent/config.yaml.example` | Modify | Repo-side template — mirror of approved live changes |
| `/opt/data/config.yaml` (on NAS, inside `hermes_agent_data` volume) | Modify | Live config consumed by hermes-gateway at startup |
| `hermes-agent/.notes/00_INDEX.md` | Modify | Update Configuration section + Change Log row |
| `hermes-agent/.notes/daily_log.md` | Modify | 2026-06-02 entry describing the tune + verification window |
| `docs/superpowers/specs/2026-06-02-hermes-token-tuning-verification.md` | Create | Baseline + 24h / 72h tracking, escalation trigger if targets missed |

---

### Task 1: Verify hermes config schema on NAS

**Files:**
- Create: `hermes-agent/.notes/hermes-v2026.5.16-schema.md`

The Tier 2 / Tier 3 keys in the spec are speculative. This task confirms which exist before any config mutation. **Do not skip** — applying unverified keys risks the regression from the 2026-05-24 incident (malformed YAML silently using empty model).

- [ ] **Step 1: Inspect hermes CLI config help**

Run:
```bash
ssh nas 'sudo /usr/local/bin/docker exec hermes-gateway hermes config --help 2>&1 | head -200'
```

Expected: either a help text listing config subcommands and known fields, or an error like "no such command". Capture the raw output for the notes file. Sudo will prompt for password — user supplies it interactively.

- [ ] **Step 2: Grep hermes source for candidate Tier 2/3 keys**

Run:
```bash
ssh nas 'sudo /usr/local/bin/docker exec hermes-gateway bash -lc "grep -rEn \"reset_on_idle|max_iterations|max_turns|max_tokens|memory\\.enabled|vision|auto_compact|tools:\" /opt/hermes --include=\"*.py\" --include=\"*.yaml\" --include=\"*.toml\" 2>/dev/null | head -80"'
```

Expected: a list of `file:line: matched_text` pairs. Each hit is evidence that the key is referenced somewhere in v2026.5.16. Absence is evidence the key is not honored.

- [ ] **Step 3: Locate the config schema source file**

Run:
```bash
ssh nas 'sudo /usr/local/bin/docker exec hermes-gateway bash -lc "find /opt/hermes -name \"config*.py\" -not -path \"*/node_modules/*\" 2>/dev/null | head -10"'
```

Expected: one or more candidate paths (e.g. `/opt/hermes/hermes_cli/config.py`).

- [ ] **Step 4: Read the schema source**

For each candidate path returned in Step 3, run:
```bash
ssh nas 'sudo /usr/local/bin/docker exec hermes-gateway cat <path>'
```

Read the dataclass / pydantic model / `@dataclass` / `BaseModel` definitions to enumerate the authoritative key list. Note the exact key path (e.g. `session.reset_on_idle_minutes` vs `session_reset_on_idle_minutes`).

- [ ] **Step 5: Record findings**

Create `hermes-agent/.notes/hermes-v2026.5.16-schema.md` with:

```markdown
# hermes v2026.5.16 — config schema verification

**Verified:** 2026-06-02
**Method:** `hermes config --help` + grep + read of `/opt/hermes` source on running container

## Tier 1 (already used in repo `config.yaml.example` — re-verified)

- `session.reset_on_idle_minutes` — **present** at `<file>:<line>`

## Tier 2 (verified live)

| Candidate key | Status | Source location | Notes |
|---|---|---|---|
| `session.max_iterations` | present \| absent | `<file>:<line>` or "no match" | |
| `agent.max_iterations` | present \| absent | | |
| `model.max_tokens` | present \| absent | | |
| `output.max_tokens` | present \| absent | | |
| `memory.enabled` | present \| absent | | |

## Tier 3 (verified live)

| Candidate key | Status | Source location | Notes |
|---|---|---|---|
| `tools` whitelist | present \| absent | | |
| `vision.max_images_per_session` | present \| absent | | |
| `auto_compact` / `compression` | present \| absent | | |

## Final decision — keys to apply

Tier 1 (always): `session.reset_on_idle_minutes: 15`.

Plus, for each Tier 2/3 key marked **present** above:
- [list each key with the value from the design spec]

Skip (mark **absent**): [list]
```

Fill in `<file>:<line>` from the grep / read output. Mark only the rows whose key was actually found in source.

- [ ] **Step 6: Commit schema findings**

Run:
```bash
git add hermes-agent/.notes/hermes-v2026.5.16-schema.md
git commit -m "docs(hermes): record v2026.5.16 config schema verification for token tuning"
```

Do not push yet — push happens once after Task 5 so the whole tune lands as a series.

---

### Task 2: Back up live config on NAS

**Files:**
- Created on NAS: `/opt/data/config.yaml.bak-20260602`
- Local snapshot for diff: `/tmp/hermes-config-before.yaml`

- [ ] **Step 1: Snapshot live config to a local file for later diff**

Run:
```bash
ssh nas 'sudo /usr/local/bin/docker exec hermes-gateway cat /opt/data/config.yaml' > /tmp/hermes-config-before.yaml
wc -l /tmp/hermes-config-before.yaml
```

Expected: non-zero line count. If line count is 0, **stop** — the live config is empty or unreadable and a tune would clobber unknown state.

- [ ] **Step 2: Create dated backup inside the data volume**

Run:
```bash
ssh nas 'sudo /usr/local/bin/docker exec hermes-gateway cp /opt/data/config.yaml /opt/data/config.yaml.bak-20260602'
```

Expected: no output, exit 0.

- [ ] **Step 3: Verify backup exists and matches source**

Run:
```bash
ssh nas 'sudo /usr/local/bin/docker exec hermes-gateway ls -la /opt/data/config.yaml /opt/data/config.yaml.bak-20260602'
ssh nas 'sudo /usr/local/bin/docker exec hermes-gateway sh -c "cmp /opt/data/config.yaml /opt/data/config.yaml.bak-20260602 && echo IDENTICAL"'
```

Expected: both files listed with the same byte size; second command prints `IDENTICAL`. If not identical, redo Step 2.

---

### Task 3: Update repo template `config.yaml.example`

**Files:**
- Modify: `hermes-agent/config.yaml.example`

Tier 1 unconditionally; Tier 2/3 only for keys marked **present** in `hermes-agent/.notes/hermes-v2026.5.16-schema.md`. **Preserve** existing `model.default`, `model.provider`, `model.base_url` — they reflect what is currently running on NAS (mimo-v2.5-pro per user) and are out of scope.

- [ ] **Step 1: Edit `hermes-agent/config.yaml.example`**

Open `hermes-agent/config.yaml.example`. Apply changes per the schema notes file. The fully-loaded form (all Tier 2 verified) looks like:

```yaml
# Hermes Agent configuration
# Copy this to the data volume: docker cp config.yaml.example hermes-gateway:/opt/data/config.yaml
# Or let hermes generate defaults on first run, then edit via:
#   docker exec -it hermes-gateway vi /opt/data/config.yaml

# ─── LLM ────────────────────────────────────────────────────────────────────
model:
  default: "mimo-v2.5-pro"
  provider: "openrouter"
  base_url: "https://openrouter.ai/api/v1"
  max_tokens: 2000          # cap response length; mimo normally answers 200–800

# ─── Telegram ───────────────────────────────────────────────────────────────
telegram:
  reply_to_mode: first
  disable_link_previews: true

# ─── Discord ────────────────────────────────────────────────────────────────
discord:
  require_mention: true
  auto_thread: true

# ─── Session ────────────────────────────────────────────────────────────────
session:
  reset_on_idle_minutes: 15   # was 60 — cut zombie sessions that destabilize mimo prefix caching
  max_iterations: 20          # was 60 — stop runaway tool loops on small tasks

# ─── Memory ─────────────────────────────────────────────────────────────────
memory:
  enabled: false              # one-week trial; long-term memory injects mutable content into the system prompt and kills prefix caching
```

**Rules:**
- Omit any block whose key was marked **absent** in the schema notes file. Do not invent keys.
- If `model.default` in the current `config.yaml.example` is `nous/hermes-3-405b` (the historical default), update it to match what runs in production per the schema verification output — but do **not** change provider/base_url unless your schema check showed they should be different.
- Indentation: 2 spaces, no tabs. Keep `model:` as a mapping (never as a scalar with indented children — that's the 2026-05-24 incident).

- [ ] **Step 2: Validate YAML locally**

Run:
```bash
python3 -c "import yaml; yaml.safe_load(open('hermes-agent/config.yaml.example')); print('OK')"
```

Expected: `OK`. If error, fix indentation before continuing — do not commit broken YAML.

- [ ] **Step 3: Commit template change**

Run:
```bash
git add hermes-agent/config.yaml.example
git commit -m "tune(hermes): tighten session reset, iteration cap, memory off — approach A config diet"
```

Do not push yet.

---

### Task 4: Apply config to live NAS and restart hermes-gateway

**Files:**
- Modify on NAS: `/opt/data/config.yaml`

- [ ] **Step 1: Push the repo template into the container's volume**

Run:
```bash
cat hermes-agent/config.yaml.example | ssh nas 'sudo /usr/local/bin/docker exec -i hermes-gateway tee /opt/data/config.yaml > /dev/null'
```

Expected: exit 0, no output. This replaces `/opt/data/config.yaml` wholesale with the new template.

- [ ] **Step 2: Diff against backup to confirm only intended changes**

Run:
```bash
ssh nas 'sudo /usr/local/bin/docker exec hermes-gateway diff /opt/data/config.yaml.bak-20260602 /opt/data/config.yaml'
```

Expected: only the deltas decided in Task 1 (Tier 1 + verified Tier 2/3). No deletion of `telegram:` / `discord:` / `model:` blocks. If the diff shows **unexpected removals** (e.g. a key the live config had that the template doesn't), **stop** and merge by hand instead:

```bash
# Restore and re-merge
ssh nas 'sudo /usr/local/bin/docker exec hermes-gateway cp /opt/data/config.yaml.bak-20260602 /opt/data/config.yaml'
ssh nas 'sudo /usr/local/bin/docker exec -it hermes-gateway vi /opt/data/config.yaml'
# Apply only the Tier 1 + verified Tier 2/3 deltas manually
```

- [ ] **Step 3: Validate YAML inside the container**

Run:
```bash
ssh nas 'sudo /usr/local/bin/docker exec hermes-gateway python3 -c "import yaml,sys; yaml.safe_load(open(\"/opt/data/config.yaml\")); print(\"YAML OK\")"'
```

Expected: `YAML OK`. If `yaml.YAMLError` or no output, **stop** and rollback (Task 6 rollback section) before doing anything else — do not restart with broken YAML.

- [ ] **Step 4: Restart hermes-gateway**

Run:
```bash
ssh nas 'cd /volume2/docker/centralized-nas-container-management && sudo /usr/local/bin/docker compose -f hermes-agent/docker-compose.yml restart hermes-gateway'
```

Expected: restart command exits 0 with output like `Container hermes-gateway  Restarted`.

- [ ] **Step 5: Confirm no crash, no "No models provided" regression**

Wait ~10 seconds for boot, then:

```bash
ssh nas 'sudo /usr/local/bin/docker ps --filter name=hermes-gateway --format "table {{.Names}}\t{{.Status}}"'
ssh nas 'sudo /usr/local/bin/docker logs hermes-gateway --tail 80 2>&1 | grep -iE "config|session|model|error|warn|no models"'
```

Expected:
- Status row shows `Up X seconds` (not `Restarting` or `Exited`).
- No `No models provided` / `YAML` / `parse error` / `traceback` in the log tail.
- A line indicating mimo (or whatever was the prior model) loaded.

If status is `Restarting` / `Exited`, immediately execute the rollback procedure in Task 6.

---

### Task 5: Update notes and push the series

**Files:**
- Modify: `hermes-agent/.notes/00_INDEX.md`
- Modify: `hermes-agent/.notes/daily_log.md`

- [ ] **Step 1: Update `hermes-agent/.notes/00_INDEX.md` Model Config section**

Replace the existing `### Model Config (config.yaml)` block with the post-tune mapping, using the keys that were actually applied (the union of Tier 1 and verified Tier 2/3). Note the one-week trial of `memory.enabled: false` inline, e.g.:

```markdown
### Model Config (config.yaml)

Post-2026-06-02 tune (Approach A — config diet):

```yaml
model:
  default: "mimo-v2.5-pro"
  provider: "openrouter"
  base_url: "https://openrouter.ai/api/v1"
  max_tokens: 2000          # applied if model.max_tokens verified present

session:
  reset_on_idle_minutes: 15
  max_iterations: 20        # applied if session.max_iterations verified present

memory:
  enabled: false            # 1-week trial through 2026-06-09; revisit at verification close
```

Verification window: 2026-06-02 → 2026-06-05. Backup at `/opt/data/config.yaml.bak-20260602`.
Schema verification: `hermes-agent/.notes/hermes-v2026.5.16-schema.md`.
```

Append a row to the Change Log table at the bottom of `00_INDEX.md`:

```markdown
| 2026-06-02 | Approach A token tune: session reset 60→15min, iterations 60→20, memory off (1-week trial). See `docs/superpowers/specs/2026-06-02-hermes-token-tuning-design.md` |
```

- [ ] **Step 2: Prepend a new entry to `hermes-agent/.notes/daily_log.md`**

Match the existing convention (newest first, `---` separators). Add a section like:

```markdown
## 2026-06-02 — Approach A token tune (config diet)

### Trigger

mimo provider dashboard for 2026-06-02 shows 35.6M total tokens with cache hit collapsed to 4% (vs 80% on 2026-06-01). 35.6M tokens spent on what amounted to a small docker-compose edit + daily log update + git rebase conflict resolution.

### Root-cause hypothesis

Session prefix instability — long-running sessions across days, plus possible dynamic-content injection (memory, screenshots) breaking mimo's prefix cache between turns.

### Change

Config-only tune via `config.yaml`. See spec: `docs/superpowers/specs/2026-06-02-hermes-token-tuning-design.md`.

Keys applied (verified in `hermes-v2026.5.16-schema.md`):
- `session.reset_on_idle_minutes`: 60 → 15
- [list other Tier 2/3 keys that were actually applied]

Live backup: `/opt/data/config.yaml.bak-20260602` (inside `hermes_agent_data` volume).

### Verification window

- Opens: 2026-06-02
- +24h check: 2026-06-03
- Closes: 2026-06-05

Tracker: `docs/superpowers/specs/2026-06-02-hermes-token-tuning-verification.md`.

### Escalation if targets missed

Re-enter brainstorming for Approach B (persona / prompt discipline). Do not silently tune config further beyond what is in the design spec.
```

- [ ] **Step 3: Commit notes**

Run:
```bash
git add hermes-agent/.notes/00_INDEX.md hermes-agent/.notes/daily_log.md
git commit -m "docs(hermes): record approach A token tune, open 3-day verification window"
```

- [ ] **Step 4: Push the series**

Run:
```bash
git push
```

Expected: 3 commits pushed (schema verification, config template, notes).

---

### Task 6: Verification tracker + rollback handle

**Files:**
- Create: `docs/superpowers/specs/2026-06-02-hermes-token-tuning-verification.md`

This task captures the 3-day verification window in a single tracker so the +24h and +72h checks don't have to be reconstructed from memory, and the rollback command is pre-staged for fast use.

- [ ] **Step 1: Create the verification tracker**

Write `docs/superpowers/specs/2026-06-02-hermes-token-tuning-verification.md`:

```markdown
# hermes token tuning — verification tracker

**Design spec:** `2026-06-02-hermes-token-tuning-design.md`
**Schema notes:** `hermes-agent/.notes/hermes-v2026.5.16-schema.md`
**Window opened:** 2026-06-02
**Window closes:** 2026-06-05
**Live config backup on NAS:** `/opt/data/config.yaml.bak-20260602`

## Baseline (2026-06-02, pre-tune)

| Metric | Value |
|---|---|
| Daily total tokens (mimo dashboard) | 35.6M |
| Cache hit | 1.3M (4%) |
| Cache miss | 33.7M |
| Iteration runaway events (≥ 60/60) | observed multiple |
| Idle reset (config) | 60 min |

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
- [ ] ≤ 1 target hit → execute rollback below and re-enter brainstorming for Approach B.

## Rollback procedure

```bash
# 1. Restore live config from backup
ssh nas 'sudo /usr/local/bin/docker exec hermes-gateway cp /opt/data/config.yaml.bak-20260602 /opt/data/config.yaml'

# 2. Validate YAML
ssh nas 'sudo /usr/local/bin/docker exec hermes-gateway python3 -c "import yaml; yaml.safe_load(open(\"/opt/data/config.yaml\")); print(\"OK\")"'

# 3. Restart gateway
ssh nas 'cd /volume2/docker/centralized-nas-container-management && sudo /usr/local/bin/docker compose -f hermes-agent/docker-compose.yml restart hermes-gateway'

# 4. Confirm
ssh nas 'sudo /usr/local/bin/docker ps --filter name=hermes-gateway --format "table {{.Names}}\t{{.Status}}"'

# 5. Repo rollback
git revert <commit-hash-of-config-tune> <commit-hash-of-notes>
git push
```
```

- [ ] **Step 2: Commit and push the tracker**

Run:
```bash
git add docs/superpowers/specs/2026-06-02-hermes-token-tuning-verification.md
git commit -m "docs(hermes): open 3-day verification tracker for token tune"
git push
```

---

## Out of scope for this plan

- Rebuilding the hermes-agent image (config-only change — image unchanged).
- Patching hermes source code (Approach C territory).
- Persona / system prompt rewrite (Approach B — held in reserve if verification fails).
- Switching model or provider (user-locked at mimo-v2.5-pro).
- Updating root `CLAUDE.md` / `README.md` — no port change, no env change, no new stack.
- Running `make secrets` or touching `secrets/vault.sops.yaml` — no env variables added or removed.
