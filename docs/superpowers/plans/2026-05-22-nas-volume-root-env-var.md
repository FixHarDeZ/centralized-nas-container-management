# NAS Volume Root Env Var Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all hardcoded `/volume1` host paths in Docker Compose files and Homepage config with `${NAS_VOLUME_ROOT}` so migrating to a different volume requires one edit in `.env`.

**Architecture:** Add `NAS_VOLUME_ROOT=/volume1` to `.env` and `.env.example`. Docker Compose substitutes `${NAS_VOLUME_ROOT}` in volume declarations at parse time via the `--env-file` flag already passed by `deploy.sh`. The Homepage disk-monitor widget uses Homepage's own `{{HOMEPAGE_VAR_VOLUME_ROOT}}` substitution, injected through the compose `environment` block.

**Tech Stack:** Docker Compose v3.8 env-var interpolation, Homepage `{{HOMEPAGE_VAR_*}}` config substitution

---

## File Map

| File | Change |
|---|---|
| `.env` | Add `NAS_VOLUME_ROOT=/volume1` before `NAS_TARGET_PATH` |
| `.env.example` | Same (this file IS committed) |
| `uptime-kuma/docker-compose.yml` | 1 volume line |
| `homepage/docker-compose.yml` | 1 volume line + 1 env var |
| `jellyfin/docker-compose.yml` | 6 volume lines |
| `homepage/config/widgets.yaml` | 1 disk path line |

---

### Task 1: Add NAS_VOLUME_ROOT to .env and .env.example

**Files:**
- Modify: `.env` (not committed — edit locally)
- Modify: `.env.example`

- [ ] **Step 1: Edit `.env`** — insert `NAS_VOLUME_ROOT=/volume1` on a new line between `NAS_SSH_KEY` and `NAS_TARGET_PATH`

  Current block (lines 10-12 of `.env`):
  ```
  NAS_SSH_KEY=~/.ssh/id_ed25519
  NAS_TARGET_PATH=/volume2/docker
  ```

  After:
  ```
  NAS_SSH_KEY=~/.ssh/id_ed25519
  NAS_VOLUME_ROOT=/volume1
  NAS_TARGET_PATH=/volume2/docker
  ```

- [ ] **Step 2: Edit `.env.example`** — same insertion at the same position (lines 10-11 of `.env.example`)

  Current:
  ```
  NAS_SSH_KEY=~/.ssh/id_ed25519
  NAS_TARGET_PATH=/volume2/docker
  ```

  After:
  ```
  NAS_SSH_KEY=~/.ssh/id_ed25519
  NAS_VOLUME_ROOT=/volume1
  NAS_TARGET_PATH=/volume2/docker
  ```

- [ ] **Step 3: Verify .env.example looks correct**

  ```bash
  grep -A2 -B2 NAS_VOLUME_ROOT .env.example
  ```

  Expected output:
  ```
  NAS_SSH_KEY=~/.ssh/id_ed25519
  NAS_VOLUME_ROOT=/volume1
  NAS_TARGET_PATH=/volume2/docker
  ```

---

### Task 2: Update uptime-kuma/docker-compose.yml

**Files:**
- Modify: `uptime-kuma/docker-compose.yml:12`

- [ ] **Step 1: Replace the volume path**

  Current line 12:
  ```yaml
        - /volume2/docker/uptime-kuma:/app/data
  ```

  After:
  ```yaml
        - ${NAS_VOLUME_ROOT}/docker/uptime-kuma:/app/data
  ```

- [ ] **Step 2: Verify interpolation resolves locally**

  ```bash
  cd uptime-kuma && docker compose --env-file ../.env config 2>/dev/null | grep app/data
  ```

  Expected output:
  ```
        - /volume2/docker/uptime-kuma:/app/data:rw
  ```

  *(The path should show the resolved value `/volume1/...`, not the literal `${NAS_VOLUME_ROOT}`)*

---

### Task 3: Update homepage/docker-compose.yml

**Files:**
- Modify: `homepage/docker-compose.yml:14` (volume line)
- Modify: `homepage/docker-compose.yml:17` (add env var after `TZ=Asia/Bangkok`)

- [ ] **Step 1: Replace the volume mount line**

  Current line 14:
  ```yaml
        - /volume1:/volume1:ro
  ```

  After:
  ```yaml
        - ${NAS_VOLUME_ROOT}:${NAS_VOLUME_ROOT}:ro
  ```

  > Why both sides use `${NAS_VOLUME_ROOT}`: Homepage accesses the disk widget path inside the container at the same absolute path as the host (`/volume1` or `/volume2`). Both the host source and container destination must match.

- [ ] **Step 2: Add HOMEPAGE_VAR_VOLUME_ROOT to the homepage service environment block**

  Current `environment` block (lines 16-17):
  ```yaml
      environment:
        - TZ=Asia/Bangkok
  ```

  After:
  ```yaml
      environment:
        - TZ=Asia/Bangkok
        - HOMEPAGE_VAR_VOLUME_ROOT=${NAS_VOLUME_ROOT}
  ```

- [ ] **Step 3: Verify interpolation resolves locally**

  ```bash
  cd homepage && docker compose --env-file ../.env config 2>/dev/null | grep -E "volume1|volume2|NAS_VOLUME|VOLUME_ROOT"
  ```

  Expected: resolved paths (e.g. `/volume1:/volume1:ro`) and `HOMEPAGE_VAR_VOLUME_ROOT=/volume1`, no literal `${NAS_VOLUME_ROOT}` in output.

---

### Task 4: Update jellyfin/docker-compose.yml

**Files:**
- Modify: `jellyfin/docker-compose.yml:13-19`

- [ ] **Step 1: Replace all 6 volume lines**

  Current lines 12-19:
  ```yaml
      volumes:
        # Config & Cache
        - /volume2/docker/jellyfin/config:/config
        - /volume2/docker/jellyfin/cache:/cache
        # Media Folders (ตั้งเป็น Read-Only ตามต้นฉบับของคุณ)
        - /volume1/Movies:/data/movies:ro
        - /volume1/Series:/data/series:ro
        - /volume1/private_media/porn:/data/private:ro
        - /volume1/Concerts:/data/concerts:ro
  ```

  After:
  ```yaml
      volumes:
        # Config & Cache
        - ${NAS_VOLUME_ROOT}/docker/jellyfin/config:/config
        - ${NAS_VOLUME_ROOT}/docker/jellyfin/cache:/cache
        # Media Folders (ตั้งเป็น Read-Only ตามต้นฉบับของคุณ)
        - ${NAS_VOLUME_ROOT}/Movies:/data/movies:ro
        - ${NAS_VOLUME_ROOT}/Series:/data/series:ro
        - ${NAS_VOLUME_ROOT}/private_media/porn:/data/private:ro
        - ${NAS_VOLUME_ROOT}/Concerts:/data/concerts:ro
  ```

- [ ] **Step 2: Verify interpolation resolves locally**

  ```bash
  cd jellyfin && docker compose --env-file ../.env config 2>/dev/null | grep -E "/data|/config|/cache"
  ```

  Expected: 6 lines showing resolved paths like `/volume2/docker/jellyfin/config:/config`, `/volume1/Movies:/data/movies:ro`, etc. No `${NAS_VOLUME_ROOT}` literals.

---

### Task 5: Update homepage/config/widgets.yaml

**Files:**
- Modify: `homepage/config/widgets.yaml:10`

- [ ] **Step 1: Replace the disk path**

  Current line 10:
  ```yaml
        - /volume1
  ```

  After:
  ```yaml
        - "{{HOMEPAGE_VAR_VOLUME_ROOT}}"
  ```

  > Why quotes: YAML would otherwise interpret `{{` as a mapping block. Quoting the string prevents a parse error.

- [ ] **Step 2: Confirm the file still parses as valid YAML**

  ```bash
  python3 -c "import yaml, sys; yaml.safe_load(open('homepage/config/widgets.yaml'))" && echo "YAML OK"
  ```

  Expected: `YAML OK`

---

### Task 6: Final grep check — no hardcoded /volume1 remaining

- [ ] **Step 1: Confirm no `/volume1` in compose files**

  ```bash
  grep -rn "/volume1" \
    uptime-kuma/docker-compose.yml \
    homepage/docker-compose.yml \
    jellyfin/docker-compose.yml \
    homepage/config/widgets.yaml
  ```

  Expected: **no output** (zero matches)

- [ ] **Step 2: Confirm NAS_VOLUME_ROOT is present in both env files**

  ```bash
  grep NAS_VOLUME_ROOT .env .env.example
  ```

  Expected:
  ```
  .env:NAS_VOLUME_ROOT=/volume1
  .env.example:NAS_VOLUME_ROOT=/volume1
  ```

---

### Task 7: Commit

- [ ] **Step 1: Stage all changed files (not .env — it's gitignored)**

  ```bash
  git add \
    .env.example \
    uptime-kuma/docker-compose.yml \
    homepage/docker-compose.yml \
    jellyfin/docker-compose.yml \
    homepage/config/widgets.yaml
  ```

- [ ] **Step 2: Commit**

  ```bash
  git commit -m "$(cat <<'EOF'
  refactor: centralise NAS volume root path via NAS_VOLUME_ROOT env var

  Replace all hardcoded /volume1 host paths in compose files and
  homepage/config/widgets.yaml with ${NAS_VOLUME_ROOT}. Add NAS_VOLUME_ROOT
  to .env.example. Change volume root in .env once to migrate stacks.

  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
  EOF
  )"
  ```

- [ ] **Step 3: Verify clean working tree**

  ```bash
  git status
  ```

  Expected: `nothing to commit, working tree clean`

---

## Post-deploy verification (on NAS)

After running `./scripts/deploy.sh -s uptime-kuma,homepage,jellyfin`:

```bash
# SSH into NAS, then:
docker compose --env-file /volume2/docker/.env \
  -f /volume2/docker/uptime-kuma/docker-compose.yml config \
  | grep app/data
# Expected: /volume2/docker/uptime-kuma:/app/data

docker compose --env-file /volume2/docker/.env \
  -f /volume2/docker/homepage/docker-compose.yml config \
  | grep VOLUME_ROOT
# Expected: HOMEPAGE_VAR_VOLUME_ROOT=/volume1
```

Homepage disk widget should display the correct volume in the dashboard top bar.
