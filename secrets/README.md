# Secrets Management

Single source of truth for all secrets across every stack, encrypted at rest with [sops](https://github.com/getsops/sops) + [age](https://github.com/FiloSottile/age).

## Architecture

```
secrets/vault.sops.yaml          ← encrypted YAML, committed to git
    ├── shared/                  ← cross-stack secrets (NAS creds, LLM keys)
    ├── stacks/                  ← per-stack private secrets
    └── deploy/                  ← deploy-only secrets (NAS_SUDO_PASSWORD etc.)

<stack>/secrets.manifest.yaml    ← declares which vault paths this stack needs
scripts/render_env.py            ← decrypts vault + reads manifests → writes .env
```

**Flow:** `make edit-vault` (edit encrypted YAML) → `make secrets` (generate .env files) → `./scripts/deploy.sh` (upload + restart)

## Adding a New Secret

### Step 1: Add the value to the vault

```bash
make edit-vault
```

This opens `secrets/vault.sops.yaml` in your `$EDITOR`. sops transparently decrypts on read and re-encrypts on save.

**Where to put it:**

| Scope | Vault path | When to use |
|---|---|---|
| Shared across stacks | `shared.<category>.<key>` | API keys used by 2+ stacks (e.g. `shared.llm.openrouter_api_key`) |
| Stack-private | `stacks.<stack_name>.<key>` | Secrets only one stack needs (e.g. `stacks.maid_tracker.line.channel_access_token`) |

**Naming conventions:**
- Vault keys: `snake_case` (e.g. `channel_access_token`, not `CHANNEL_ACCESS_TOKEN`)
- Stack name in path: match directory name but replace `-` with `_` (e.g. `maid-tracker/` → `stacks.maid_tracker`)
- Nesting is fine: `stacks.watchtower.line.user_id`

**Example — adding a new shared API key:**

```yaml
shared:
  llm:
    openrouter_api_key: sk-or-v1-...    # existing
    new_service_api_key: abc123         # ← add this

stacks:
  news_feed:
    telegram:
      bot_token: 8774745907:AAFz...
    new_service_api_key: xyz789         # ← or per-stack version
```

Save and close the editor. sops re-encrypts automatically.

### Step 2: Map it in the stack's manifest

Edit `<stack>/secrets.manifest.yaml`:

```yaml
env:
  # Existing mappings...
  OPENROUTER_API_KEY: shared.llm.openrouter_api_key

  # New mapping: ENV_NAME_IN_DOTENV → vault.dotted.path
  NEW_SERVICE_API_KEY: shared.llm.new_service_api_key

literals:
  # Public config values (not secrets) — written as-is
  SOME_PUBLIC_URL: https://api.example.com
```

**Rules:**
- `env:` values must start with `shared.`, `stacks.`, or `deploy.`
- `env:` keys must be `UPPER_SNAKE_CASE` (validated by `secrets/manifest.schema.json`)
- `literals:` are for non-secret config (URLs, feature flags, defaults)
- No duplicate ENV names between `env:` and `literals:`

### Step 3: Regenerate .env files

```bash
make secrets
```

Output:
```
  wrote hermes-agent/.env
  wrote homepage/.env
  ...
  wrote <stack>/.env
```

Verify the new key appears:
```bash
grep NEW_SERVICE_API_KEY <stack>/.env
```

### Step 4: Use it in the application

**Docker Compose** (`docker-compose.yml`):

```yaml
services:
  my-service:
    env_file: .env                    # loads all vars from .env
    environment:
      - NEW_SERVICE_API_KEY=${NEW_SERVICE_API_KEY}   # explicit pass-through (optional)
```

**Python** (FastAPI, scripts, etc.):

```python
import os

api_key = os.getenv("NEW_SERVICE_API_KEY", "")        # with default
api_key = os.environ["NEW_SERVICE_API_KEY"]            # required (crashes if missing)
```

**JavaScript/Node.js:**

```javascript
const apiKey = process.env.NEW_SERVICE_API_KEY;
```

**Shell script:**

```bash
echo "$NEW_SERVICE_API_KEY"
# or with default:
echo "${NEW_SERVICE_API_KEY:-fallback}"
```

### Step 5: Test

```bash
make check                    # validate manifests against vault
make test                     # run pytest (43 tests)
python scripts/render_env.py --dry-run   # preview rendered output
```

### Step 6: Commit + Deploy

```bash
git add <stack>/secrets.manifest.yaml
git commit -m "feat(<stack>): add NEW_SERVICE_API_KEY"
make secrets && ./scripts/deploy.sh -s <stack> -y
```

> `vault.sops.yaml` is already tracked — just commit the manifest change. The generated `.env` files are gitignored.

## Removing a Secret

1. **Remove from manifest** — delete the line from `<stack>/secrets.manifest.yaml`
2. **Remove from vault** — `make edit-vault`, delete the key
3. **Remove from code** — remove `os.getenv()` / `os.environ[]` references
4. **Regenerate** — `make secrets`
5. **Commit** — `git add -A && git commit`

## Rotating a Secret

1. `make edit-vault` — update the value
2. `make secrets` — regenerate .env files
3. `./scripts/deploy.sh -s <stack> -y` — restart the stack
4. (If the old value was leaked) revoke it at the provider

## Setting Up on a New Machine

### Prerequisites

```bash
# 1. Install tooling
brew install sops age        # macOS
# or: apt install sops age   # Linux

# 2. Get the age private key (from Bitwarden / 1Password / vault maintainer)
mkdir -p ~/.config/sops/age
cat > ~/.config/sops/age/keys.txt << 'EOF'
# created: 2026-05-30T...
# public key: age19dju...
AGE-SECRET-KEY-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
EOF
chmod 600 ~/.config/sops/age/keys.txt
```

### Clone + Generate

```bash
git clone https://github.com/FixHarDeZ/centralized-nas-container-management.git
cd centralized-nas-container-management

# Create venv + install deps (for render_env.py)
python3 -m venv .venv
.venv/bin/pip install pyyaml

# Generate all .env files
make secrets

# Verify
make check
```

### Deploy

```bash
# Fill in deploy credentials (NAS host, user, sudo password)
make edit-vault
# Edit shared.nas.* section

# Generate + deploy
make secrets
./scripts/deploy.sh
```

### Adding a New Age Recipient (Multi-Machine)

If a new machine needs to decrypt the vault:

```bash
# On the new machine: generate a key pair
age-keygen -o ~/.config/sops/age/keys.txt
# Note the public key: age1...

# On a machine that already has access: add the new public key to .sops.yaml
# Then re-encrypt:
sops updatekeys secrets/vault.sops.yaml

# Commit the updated .sops.yaml and vault.sops.yaml
git add .sops.yaml secrets/vault.sops.yaml
git commit -m "chore(secrets): add new age recipient"
```

## CI / GitHub Actions

The workflow `.github/workflows/secrets.yml` validates on every PR:

1. Installs sops + age on `ubuntu-latest`
2. Loads `SOPS_AGE_KEY` from GitHub Actions secret (CI-only age key)
3. Runs `pytest tests/ -v` (43 tests)
4. Runs `python scripts/render_env.py --check --vault secrets/test-vault.sops.yaml`

**`secrets/test-vault.sops.yaml`** is a separate vault encrypted with the CI age key, containing dummy values. It validates that manifests are structurally correct without exposing real secrets.

To add the CI secret (one-time):
1. Go to GitHub repo → Settings → Secrets and variables → Actions
2. Add `SOPS_AGE_KEY` with the CI private key value

## File Reference

| File | Tracked | Purpose |
|---|---|---|
| `.sops.yaml` | yes | age public keys for encryption (prod + CI) |
| `vault.sops.yaml` | yes | All secrets, encrypted |
| `test-vault.sops.yaml` | yes | CI dummy vault, encrypted with CI key |
| `manifest.schema.json` | yes | JSON Schema validating manifests |
| `<stack>/secrets.manifest.yaml` | yes | Per-stack vault → ENV mapping |
| `deploy.manifest.yaml` | yes | Root deploy vault → ENV mapping |
| `<stack>/.env` | **no** (gitignored) | Generated, uploaded to NAS |
| `.env.deploy` | **no** (gitignored) | Generated, used by deploy.sh locally |

## Troubleshooting

**`sops decrypt failed: no secret keys found`**
- Check `~/.config/sops/age/keys.txt` exists and has the private key
- Or set `SOPS_AGE_KEY_FILE` env var to the key file path

**`manifest references missing vault path`**
- The vault path in `secrets.manifest.yaml` doesn't exist in `vault.sops.yaml`
- `make edit-vault` to add the missing key, or fix the manifest path

**`render_env.py` produces empty value**
- The vault key exists but its value is empty string `""`
- This is valid — the .env will have `KEY=`

**CI fails with `sops decrypt failed`**
- The `SOPS_AGE_KEY` GitHub Actions secret is missing or contains the wrong key
- CI uses `secrets/test-vault.sops.yaml` (different age key from prod)

**Want to preview without writing:**
```bash
python scripts/render_env.py --dry-run
```
