# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This repo manages Docker containers deployed on a Synology DS925+ NAS. It is a collection of `docker-compose.yml` stacks, not an application codebase. Each subdirectory is an independent stack managed via Synology Container Manager (DSM 7.3.2).

## Stacks

| Directory | Purpose | Port(s) |
|---|---|---|
| `homepage/` | Dashboard UI (gethomepage/homepage) | 3000 |
| `jellyfin/` | Media server with NVIDIA GPU transcoding | 8096 |
| `maid-tracker/` | Household worker attendance & salary tracker | 5055 |
| `portainer/` | Docker management UI | 9000, 9443 |
| `uptime-kuma/` | Service health monitor | 3001 |
| `watchtower/` | Auto-update containers + LINE notification sidecar | — |

## Deploying to NAS

Use `deploy.sh` to upload the entire project from your local machine to `/volume1/docker` on the NAS over SSH (key-based auth), and optionally restart stacks automatically.

```bash
# 1. Copy the example config and fill in your NAS details
cp .deploy.env.example .deploy.env
nano .deploy.env

# 2. Upload (and optionally restart stacks)
./deploy.sh
```

The script reads config from `.deploy.env` (excluded from git), checks the SSH connection first, then uploads the project via `tar`+SSH — excluding `.git/`, `.deploy.env`, and `deploy.sh` itself.

SSH uses key-based auth (default: `~/.ssh/id_ed25519`, port 2222). No `sshpass` required.

### Post-upload stack restart

After uploading, the script prompts whether to restart stacks on the NAS:

- **Restart all** — restarts every stack at once
- **Per-stack** — prompts individually for each stack

For each selected stack, the script SSH-es into the NAS and runs:
```bash
sudo docker compose down
sudo docker compose up -d --build
```

`--build` ensures local images (e.g. the `watchtower-notifier` sidecar) are rebuilt. Remote images are re-used from cache unless changed.

> **Note:** `NAS_SUDO_PASSWORD` in `.deploy.env` is used only to authenticate `sudo` for stack restarts. SSH itself uses key auth exclusively. The NAS user must have `sudo` privileges.

## Adding a Stack to Container Manager (DSM 7.3.2)

After uploading files to the NAS via `deploy.sh`, register each new stack in Synology Container Manager UI:

1. Open **DSM** → **Container Manager** → **Project** tab
2. Click **Create**
3. Fill in:
   - **Project Name** — match the directory name, e.g. `homepage`
   - **Path** — point to the stack directory, e.g. `/volume1/docker/homepage`
     Container Manager auto-detects `docker-compose.yml` in that path
4. Click **Next** → review → **Build**

> Stacks with a local build (e.g. `watchtower`) have their image built on first run.
> For subsequent updates, use `deploy.sh` with the restart option instead of re-registering.

## Architecture

### Homepage (`homepage/`)
- Config lives entirely in `config/` (YAML files loaded at runtime, no rebuild needed).
- `services.yaml` defines all dashboard tiles and their widgets (Jellyfin, Plex, Portainer, Uptime Kuma, etc.).
- Secrets are meant to come from `.env` → passed as environment variables in `docker-compose.yml`.
- **Currently, real credentials are hardcoded directly in `docker-compose.yml` and `config/services.yaml` — these must be migrated to `.env` before this repo is made public or shared.**

### Watchtower (`watchtower/`)
- Two services in one compose file: `watchtower` (image update poller) and `watchtower-notifier` (Python sidecar).
- The sidecar (`notifier/notifier.py`) connects to the Docker socket directly via raw Unix socket HTTP (no `docker` CLI binary required) and tails Watchtower's log stream.
- It parses Watchtower 1.7.x structured log format and sends LINE Messaging API push notifications for: notifier start, session start, per-container updates, session summary, and errors.
- The sidecar image is a local build (`python:3.12-slim` base); Watchtower is instructed to skip it via label `com.centurylinklabs.watchtower.enable=false`.
- Poll interval: 86400s (24h). Configured via `WATCHTOWER_POLL_INTERVAL`.

### Maid Tracker (`maid-tracker/`)
- Single-container FastAPI (Python 3.12) app with SQLite database.
- Data persisted in named volume `maid_tracker_data` mounted at `/data`.
- Serves a fully static SPA (Bootstrap 5 + vanilla JS) via FastAPI's `StaticFiles`.
- No `.env` file required — no secrets. `TZ=Asia/Bangkok` is set in compose.
- Local build required (`Dockerfile` uses `python:3.12-slim`). Port 5055 → container 8000.
- Status types: `work` (Mon–Sat default), `leave` (deducted), `holiday` (Sun default), `compensatory` (Sun worked = credit).
- Each leave/compensatory day can be **full day (1.0) or half day (0.5)** — stored as `half_day INTEGER` in the `attendance` table. All cumulative calculations use the fractional value.
- Daily rate = `monthly_salary ÷ working_days_in_month` (Mon–Sat count). First partial month is prorated.
- Salary policy: no monthly deduction — leave/comp settle at resignation. Employee detail page shows cumulative balance (days + approx. amount) before resignation is filed.

### Portainer (`portainer/`)
- Standard Portainer CE deployment. Data persisted in a named volume `portainer_data`.

## Credentials Warning

The following files contain real plaintext credentials that should be moved to `.env`:
- `homepage/docker-compose.yml` — `JELLYFIN_API_KEY`, `PLEX_TOKEN`, `NAS_USERNAME`, `NAS_PASSWORD`
- `homepage/config/services.yaml` — Jellyfin API key, Plex token, NAS username/password, Portainer API key
- `watchtower/docker-compose.yml` — `LINE_CHANNEL_ACCESS_TOKEN`, `LINE_USER_ID`

Use `homepage/.env.example` as the template for the homepage stack's `.env` file.
