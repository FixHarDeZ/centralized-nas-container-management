# Env / Secrets Management Redesign

**Date:** 2026-05-30
**Status:** Design — awaiting user approval
**Scope:** Replace the current scattered `.env` + aspirational `sync_env.py` workflow with an encrypted vault + per-stack manifest + generator pipeline.

---

## 1. Goals

From the current pain inventory (all selected by user):

| # | Pain | Concrete example |
|---|------|------------------|
| 1 | Rotating a shared secret is laborious | `OPENROUTER_API_KEY` lives in 3 stacks (`news-feed`, `secretary/query`, `hermes-agent`); rotation requires editing 3 files and remembering which |
| 2 | No single source of truth | "What secrets does the whole system use?" requires walking 11+ files |
| 3 | No encryption at rest | `NAS_SUDO_PASSWORD` and `SYNC_NOTION_TOKEN` sit plaintext in root `.env`; backups expose them |
| 4 | Inconsistent naming | `TELEGRAM_BOT_TOKEN` vs `NEWS_FEED_TELEGRAM_BOT_TOKEN` vs `HERMES_TELEGRAM_BOT_TOKEN` vs `WATCHTOWER_TELEGRAM_BOT_TOKEN` — sync script needs a hard-coded OVERRIDES dict |
| 5 | Hard to work from another machine | New laptop / sandbox / hermes-agent has no `.env` and no way to bootstrap |

Constraints set by user:

- **Not** one mega `.env` distributed wholesale to every stack (avoids parameter pollution).
- Must remain compatible with the existing `deploy.sh` (tar+ssh) flow.
- NAS environment must not need new tooling installed.

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│ SOURCE OF TRUTH (in git)                                        │
│   secrets/vault.sops.yaml      ← encrypted, hierarchical        │
│   secrets/.sops.yaml           ← sops config (age recipients)   │
│   secrets/test-vault.sops.yaml ← dummy vault for CI             │
│   <stack>/secrets.manifest.yaml ← per-stack key mapping         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼   scripts/render_env.py
                              │   (decrypt + filter + quote)
┌─────────────────────────────────────────────────────────────────┐
│ BUILD ARTIFACTS (gitignored, regenerated)                       │
│   <stack>/.env       ← only the keys this stack's manifest    │
│   ./.env.deploy      ← NAS_* for deploy.sh                      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼   scripts/deploy.sh (existing flow)
┌─────────────────────────────────────────────────────────────────┐
│ RUNTIME (NAS — no sops/age installed)                           │
│   /volume2/docker/<stack>/.env ← consumed by docker compose     │
└─────────────────────────────────────────────────────────────────┘
```

**Key idea:** vault = data lake; manifest = view definition (each stack selects its keys + renames if needed); generator = ETL. Decryption happens once on workstation; NAS only sees plaintext `.env` per stack — same as today.

---

## 3. Vault Schema (`secrets/vault.sops.yaml`)

Two top-level sections — **`shared:`** (cross-stack secrets) and **`stacks:`** (stack-private secrets):

```yaml
shared:
  llm:
    openrouter_api_key: sk-or-...
    anthropic_api_key:  sk-ant-...
    cohere_api_key:     ...
  notion:
    secretary_token:    ntn_...      # used by secretary/ingest
    sync_token:         ntn_...      # used by local sync_notion.py (to deprecate)
  nas:
    user:               <USER>
    host:               <HOST>
    port:               "2222"
    sudo_password:      ...
    ssh_key:            ~/.ssh/id_ed25519
    target_path:        /volume2/docker

stacks:
  homepage:
    nas_username:       ...
    nas_password:       ...
    jellyfin_api_key:   ...
    plex_api_key:       ...
    portainer_api_key:  ...
  news_feed:
    line:     { channel_access_token: ..., user_id: U... }
    telegram: { bot_token: ..., chat_id: ... }
    admin_token: ...
  hermes_agent:
    telegram: { bot_token: ..., allowed_users: ... }
    discord:  { bot_token: ..., allowed_guilds: ... }
  watchtower:
    line:     { channel_access_token: ..., user_id: ... }
    telegram: { bot_token: ..., chat_id: ... }
  torrentwatch:
    site:              { username: ..., password: ... }
    line:              { access_token: ..., user_id: ... }
    telegram:          { bot_token: ..., chat_id: ... }
    nginx_basic_auth:  { user: ..., pass: ... }
  maid_tracker:
    line:              { channel_access_token: ..., channel_secret: ..., group_id: ... }
    nginx_basic_auth:  { user: ..., pass: ... }
  secretary:
    n8n: { basic_auth_user: admin, basic_auth_password: ... }
```

### Promotion rule

- A key with the **same value** used by ≥2 stacks → `shared.<domain>.<name>`
- A key unique to one stack (even if it has the same shape elsewhere) → `stacks.<stack>.<...>`
- Keys inside vault use `snake_case` (decoupled from ENV naming).

---

## 4. Per-Stack Manifest (`<stack>/secrets.manifest.yaml`)

Manifest is the **view definition** — it specifies which vault paths this stack needs and the ENV name to project them as. Committed to git (no secrets inside).

```yaml
# news-feed/secrets.manifest.yaml
env:
  # Shared
  ANTHROPIC_API_KEY:                shared.llm.anthropic_api_key
  OPENROUTER_API_KEY:               shared.llm.openrouter_api_key
  # Stack-specific (Phase A keeps existing ENV names)
  LINE_CHANNEL_ACCESS_TOKEN:        stacks.news_feed.line.channel_access_token
  LINE_USER_ID:                     stacks.news_feed.line.user_id
  NEWS_FEED_TELEGRAM_BOT_TOKEN:     stacks.news_feed.telegram.bot_token
  TELEGRAM_CHAT_ID:                 stacks.news_feed.telegram.chat_id
  ADMIN_TOKEN:                      stacks.news_feed.admin_token

# Plain config values — written as-is to .env (public, not secret)
literals:
  SUMMARIZER_PROVIDER: anthropic
  SUMMARIZER_MODEL:    claude-sonnet-4-6
  DIGEST_TIMES:        "07:00,12:00,18:00"
  ENABLED_SOURCES:     techcrunch_ai,venturebeat,theverge,arstechnica,gsmarena,9to5mac,android_authority
  RETENTION_DAYS:      "30"
  DATA_DIR:            /data
```

### Why split `env:` and `literals:`?

- `env:` resolves through vault decryption.
- `literals:` are public config (model names, retention days, source lists) — committing them in the manifest gives reviewers the full picture without involving sops.

### What this replaces

- `.env.example` per stack → **deleted** (manifest is template + mapping + literal config in one file).
- `OVERRIDES` dict in `sync_env.py` → **eliminated** (per-stack mapping is explicit in each manifest).

---

## 5. Encryption — sops + age

### Tooling choice

- **`age`** — modern, ~100-byte keys, no GPG/keyring overhead.
- **`sops`** — encrypts values only; YAML keys remain readable so PR diffs show *which* secret changed without leaking values.

Install on workstation only: `brew install sops age`. **Not** installed on NAS.

### Key management

| File | Location | Committed? |
|------|----------|------------|
| Private age key | `~/.config/sops/age/keys.txt` | ❌ NEVER |
| Public recipients config | `secrets/.sops.yaml` | ✅ yes |
| Encrypted vault | `secrets/vault.sops.yaml` | ✅ yes (encrypted) |
| Test vault for CI | `secrets/test-vault.sops.yaml` | ✅ yes (dummy values) |

`secrets/.sops.yaml`:

```yaml
creation_rules:
  - path_regex: secrets/vault\.sops\.yaml$
    age: >-
      age1xxx...workstation,
      age1yyy...laptop,
      age1zzz...hermes-deploy
    encrypted_regex: '^(.*)$'
  - path_regex: secrets/test-vault\.sops\.yaml$
    age: age1ttt...ci-test-key
```

### Portability — adding a new machine

```bash
# On the new machine (laptop / hermes container / sandbox):
age-keygen -o ~/.config/sops/age/keys.txt        # prints public key

# On the workstation:
# 1. add the new public key to secrets/.sops.yaml under the prod recipients
# 2. sops updatekeys secrets/vault.sops.yaml      # re-encrypt for the new recipient set
# 3. git commit + push

# Back on the new machine:
git pull
make secrets                                      # works
```

For ephemeral environments, store the workstation private key in Bitwarden / 1Password and pull it on-demand:

```bash
bw get notes age-key-workstation > ~/.config/sops/age/keys.txt
```

### Security wins vs current

- `NAS_SUDO_PASSWORD` moves out of plaintext root `.env` into the encrypted vault.
- All shared API keys (OpenRouter, Anthropic, Notion, etc.) become encrypted-at-rest in git.
- Adding/removing machine access = updating `.sops.yaml` recipients + `sops updatekeys` (auditable in git history).

---

## 6. Generator (`scripts/render_env.py`)

### Inputs / outputs

- Reads: `secrets/vault.sops.yaml` (decrypted via sops) + every `<stack>/secrets.manifest.yaml` + the root `deploy.manifest.yaml`.
- Writes: `<stack>/.env` for each stack + `./.env.deploy` for `deploy.sh`.

### Pseudocode

```python
vault = sops_decrypt("secrets/vault.sops.yaml")            # dict
errors = []

for manifest_path in find_all_manifests():
    manifest = yaml.safe_load(manifest_path.read_text())
    out_lines = [
        "# GENERATED by scripts/render_env.py — DO NOT EDIT",
        f"# Source: secrets/vault.sops.yaml + {manifest_path}",
        "# Regenerate: make secrets",
    ]
    seen = set()
    for env_name, vault_path in (manifest.get("env") or {}).items():
        if env_name in seen:
            errors.append((manifest_path, "duplicate", env_name))
            continue
        seen.add(env_name)
        value = lookup(vault, vault_path)
        if value is None:
            errors.append((manifest_path, "missing vault path", vault_path))
            continue
        out_lines.append(f"{env_name}={compose_quote(value)}")
    for k, v in (manifest.get("literals") or {}).items():
        if k in seen:
            errors.append((manifest_path, "literal collides with env", k))
            continue
        out_lines.append(f"{k}={compose_quote(v)}")
    out_path = manifest_path.parent / ".env"
    out_path.write_text("\n".join(out_lines) + "\n")

if errors:
    print_errors(errors)
    sys.exit(1)
```

### Value quoting

Quoting follows **docker-compose `.env` parser semantics** (not generic shell):

- Wrap values in double quotes whenever they contain space, `#`, `$`, `"`, `\`, or newline.
- Escape `$` as `$$` only when inside compose interpolation contexts (not applicable here — `.env` values are passed to the container, not interpolated, so `$` is literal).
- Multiline values are rejected (compose `.env` does not support them); raise an error and instruct the user to base64-encode or split.

A one-line note in the generator references compose's documented `.env` parsing rules to avoid drift toward generic shell escaping.

### CLI

```bash
make secrets                                # all stacks + .env.deploy
python3 scripts/render_env.py --stack news-feed
python3 scripts/render_env.py --check       # validate manifests + vault, exit non-zero on error, no writes
python3 scripts/render_env.py --dry-run     # print outputs to stdout, no writes
```

### Validation rules

| Rule | Action |
|------|--------|
| Manifest references a vault path that does not exist | Error, fail render |
| Manifest has duplicate ENV name (in `env:` or between `env:` and `literals:`) | Error |
| Vault has a key not referenced by any manifest | Warning (orphan secrets — possibly intentional) |
| Value contains `\n` | Error with remediation note |
| Manifest fails schema validation | Error (see §8) |

---

## 7. Deploy.sh Integration

### Single change: how `deploy.sh` gets `NAS_*`

`render_env.py` writes a `./.env.deploy` at repo root from a small `deploy.manifest.yaml`:

```yaml
# deploy.manifest.yaml (repo root)
env:
  NAS_USER:          shared.nas.user
  NAS_HOST:          shared.nas.host
  NAS_PORT:          shared.nas.port
  NAS_SSH_KEY:       shared.nas.ssh_key
  NAS_TARGET_PATH:   shared.nas.target_path
  NAS_SUDO_PASSWORD: shared.nas.sudo_password
literals:
  NAS_SSH_ALIAS: nas
```

`deploy.sh` changes one line:

```bash
# Before
ENV_FILE="${PROJECT_ROOT}/.env"

# After
ENV_FILE="${PROJECT_ROOT}/.env.deploy"
```

### Pre-upload verification

Add a fail-fast block in `deploy.sh` before the tar step to catch "forgot to run `make secrets`":

```bash
log "Verifying generated .env files ..."
MISSING=()
for stack in "${ALL_STACKS[@]}"; do
  manifest="${PROJECT_ROOT}/${stack}/secrets.manifest.yaml"
  envfile="${PROJECT_ROOT}/${stack}/.env"
  [[ -f "$manifest" && ! -f "$envfile" ]] && MISSING+=("$stack")
done
if [[ ${#MISSING[@]} -gt 0 ]]; then
  err "Missing .env for: ${MISSING[*]}"
  echo "  Run: make secrets"
  exit 1
fi
```

Everything past this verification stays identical — same tar+ssh upload, same per-stack `.env` push, same `docker compose --project-directory` restart. The NAS never sees sops or age.

---

## 8. Makefile

```makefile
AGE_KEY ?= $(HOME)/.config/sops/age/keys.txt
export SOPS_AGE_KEY_FILE = $(AGE_KEY)

.PHONY: secrets check edit-vault rotate-key clean-env help

help:           ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-14s %s\n", $$1, $$2}'

secrets:        ## Render <stack>/.env + .env.deploy from vault + manifests
	@python3 scripts/render_env.py

check:          ## Validate manifests + vault consistency (no write)
	@python3 scripts/render_env.py --check

edit-vault:     ## Open vault in $EDITOR (sops decrypts on read, re-encrypts on save)
	@sops secrets/vault.sops.yaml

rotate-key:     ## Re-encrypt vault for current .sops.yaml recipients
	@sops updatekeys secrets/vault.sops.yaml

clean-env:      ## Remove all generated .env files (does not touch vault)
	@find . -name '.env' -not -path './.git/*' -delete
	@rm -f .env.deploy
```

Daily flow:

```bash
make edit-vault       # change a secret
make secrets          # regenerate
./scripts/deploy.sh   # upload + restart
```

---

## 9. Schema Validation (`secrets/manifest.schema.json`)

JSON Schema validates every `secrets.manifest.yaml` plus `deploy.manifest.yaml`:

- `env:` — object, values must match `^(shared|stacks|deploy)\..+`
- `literals:` — object, values must be strings, numbers, or booleans
- No additional top-level keys allowed
- Validated by `make check` and CI

---

## 10. Testing Strategy

### Unit tests (`tests/test_render_env.py`)

- Fixture vault + manifest → assert exact output, including header comments.
- Error cases: missing vault path, duplicate ENV, malformed YAML, multiline value.
- Quoting cases: value with space, `$`, `"`, `\`, `#` — verify compose-`.env`-compliant output.

### Schema validation tests

- Valid + invalid manifest fixtures, each asserts the expected jsonschema verdict.

### Migration equivalence test (`tests/test_migration_equivalence.py`)

- Used during Phase A rollout (§11.3).
- For each stack: load `before/<stack>.env` (pre-migration backup) and `<stack>/.env` (post-render), normalize comments + whitespace, assert equal key=value sets.

### CI (`.github/workflows/secrets.yml`)

- Use `secrets/test-vault.sops.yaml` (dummy values) decrypted with an age key stored in GitHub Actions secrets — **not** the prod vault.
- Run `make check` + render unit tests + schema tests on every PR.
- Fail PR if a manifest references a vault path missing from the test vault.

---

## 11. Migration Plan

The migration is split into **two phases** that are independently shippable. Phase A delivers the value (DRY + encryption + single source); Phase B is optional ergonomic cleanup.

### 11.1 Phase 0 — Setup (one-time, ~15 min)

1. `brew install sops age`
2. `age-keygen -o ~/.config/sops/age/keys.txt`
3. Create `secrets/.sops.yaml` with the workstation public key as the only recipient (more added later).

### 11.2 Phase A — Vault + manifests (infra only, no container code change)

Goal: replace the storage + sync layer. **Manifests use the same ENV names that container code reads today** — including the inconsistent `NEWS_FEED_TELEGRAM_BOT_TOKEN`, `HERMES_TELEGRAM_BOT_TOKEN`, `WATCHTOWER_*` prefixes. This keeps Phase 3 equivalence meaningful (real byte-diff) and means container code is untouched.

```
Step 1 — Build the vault
├── scripts/import_envs.py             ← NEW one-shot helper (migration only)
│     - reads every current <stack>/.env
│     - keys whose value matches across ≥2 stacks → suggest under shared.<domain>
│     - everything else → stacks.<stack>.<key>
│     - prints a draft plaintext vault.yaml to stdout
├── review and hand-edit draft → secrets/vault.yaml
└── sops -e -i secrets/vault.yaml && mv secrets/vault.yaml secrets/vault.sops.yaml

Step 2 — Write manifests (per stack)
├── scripts/import_envs.py --emit-manifests
│     for each stack, emit secrets.manifest.yaml whose env: keys are the
│     CURRENT ENV names from that stack's .env, mapped to the vault path
│     chosen in Step 1
└── manual review (cosmetic only — do NOT rename ENV keys here)

Step 3 — Validate equivalence (the safety net)
├── git stash or copy current <stack>/.env files to backup/
├── make secrets
├── scripts/diff_envs.py <stack> --against backup/<stack>/.env
│     compares key=value sets (ignoring comments + ordering)
└── repeat until every stack passes

Step 4 — Switch over
├── deploy.sh: change ENV_FILE to .env.deploy, add pre-upload verification
├── delete: scripts/sync_env.py, all <stack>/.env.example, root .env,
│           root .env.example, scripts/sync_notion.py if NOTION moved to vault
├── update CLAUDE.md and README to describe the new flow
└── deploy one small stack first (uptime-kuma) as smoke test

Step 5 — Production rollout
└── deploy all stacks, monitor 24h
```

**Rollback at any point before Step 4:** the existing `<stack>/.env` files have not been touched (rendered output goes through the diff helper before overwriting), and `sync_env.py` still works.

### 11.3 Phase B — Naming cleanup (optional, one PR per stack)

After Phase A is stable, rename inconsistent ENV names to upstream conventions, one stack at a time. Each PR touches:

1. The stack's manifest (`env:` key on the left side of mappings).
2. The stack's container code that reads `os.environ[...]`.
3. The stack's `docker-compose.yml` if any keys are interpolated.

| Stack | Old ENV name | New ENV name |
|-------|--------------|--------------|
| news-feed | `NEWS_FEED_TELEGRAM_BOT_TOKEN` | `TELEGRAM_BOT_TOKEN` |
| hermes-agent | `HERMES_TELEGRAM_BOT_TOKEN` | `TELEGRAM_BOT_TOKEN` |
| watchtower | `WATCHTOWER_TELEGRAM_BOT_TOKEN` | `TELEGRAM_BOT_TOKEN` |
| torrentwatch | `TORRENTWATCH_TELEGRAM_BOT_TOKEN` | `TELEGRAM_BOT_TOKEN` |
| torrentwatch | `TORRENTWATCH_LINE_ACCESS_TOKEN` | `LINE_CHANNEL_ACCESS_TOKEN` |
| maid-tracker | `MAID_LINE_CHANNEL_ACCESS_TOKEN` | `LINE_CHANNEL_ACCESS_TOKEN` |
| secretary/ingest | `SECRETARY_NOTION_TOKEN` | `NOTION_TOKEN` |
| watchtower | `WATCHTOWER_LINE_CHANNEL_ACCESS_TOKEN` | `LINE_CHANNEL_ACCESS_TOKEN` |

Disambiguation moves from ENV name → vault path (manifest maps `TELEGRAM_BOT_TOKEN` to a different `stacks.<name>.telegram.bot_token` per stack).

**Phase B can be deferred indefinitely** — Phase A delivers all four pain-point fixes on its own.

---

## 12. `.gitignore` Additions (part of Phase A, Step 4)

Current `.gitignore` already covers `.env` (matches at any depth). Add:

```
.env.deploy            # generated root file for deploy.sh
secrets/vault.yaml     # transient unencrypted intermediate during migration / edit
```

`secrets/vault.sops.yaml` is committed (encrypted). `secrets/.sops.yaml` is committed (public recipients only). `secrets/test-vault.sops.yaml` is committed (dummy values, encrypted with CI test key).

---

## 13. Documentation Updates (part of Phase A, Step 4)

- **`CLAUDE.md`** — rewrite the "Environment & Deployment Gotchas" section:
  - Replace `Per-Stack .env` description with vault + manifest model.
  - Add a "Secrets workflow" subsection: `make edit-vault` / `make secrets` / `./scripts/deploy.sh`.
  - Note that NAS still consumes `<stack>/.env` exactly as before — no NAS-side change.
- **`README.md`** — replace the env-setup quick-start with:
  1. `brew install sops age`
  2. Import age key (from password manager or `age-keygen` if new)
  3. `make secrets`
  4. `./scripts/deploy.sh`
- Remove references to `sync_env.py`, `sync_notion.py`, root `.env`, `.env.example` per stack.

---

## 14. Out of Scope (will not be implemented)

- Migration to HashiCorp Vault / Bitwarden Secrets Manager / cloud KMS.
- Per-environment vaults (dev / staging / prod) — this project is single-environment (the NAS).
- Secret rotation automation (rotating API keys at upstream providers automatically).
- Runtime decryption on NAS — sops stays on workstation only.

---

## 15. Security Note — Pre-Spec Incident

During the design exploration (this session), the assistant read the root `.env` file with the `Read` tool, which echoed live values into the session transcript. The exposed secrets were:

- `NAS_SUDO_PASSWORD`
- `SYNC_NOTION_TOKEN`

These should be rotated independently of whether this redesign is accepted. Future inspections of `.env` files should be masked (e.g., `grep -E '^[A-Z_]+=' .env | sed 's/=.*/=<redacted>/'`).
