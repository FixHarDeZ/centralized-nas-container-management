# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This repo manages Docker containers deployed on a Synology DS925+ NAS. It is a collection of `docker-compose.yml` stacks, not an application codebase. Each subdirectory is an independent stack deployed to the NAS via Synology Container Manager (or direct Docker CLI).

## Stacks

| Directory | Purpose | Port(s) |
|---|---|---|
| `homepage/` | Dashboard UI (gethomepage/homepage) | 3000 |
| `jellyfin/` | Media server with NVIDIA GPU transcoding | 8096 |
| `portainer/` | Docker management UI | 9000, 9443 |
| `uptime-kuma/` | Service health monitor | 3001 |
| `watchtower/` | Auto-update containers + LINE notification sidecar | — |

## Deploying to NAS

Use `deploy.sh` to upload the entire project from your local machine to `/volume1/docker` on the NAS over SSH, and optionally restart stacks automatically.

```bash
# 1. Copy the example config and fill in your NAS password
cp .deploy.env.example .deploy.env
nano .deploy.env

# 2. Install sshpass (required, one-time)
brew install sshpass   # macOS

# 3. Upload (and optionally restart stacks)
./deploy.sh
```

The script reads credentials from `.deploy.env` (excluded from git), checks the SSH connection first, then uploads the project via `tar`+SSH — excluding `.git/`, `.deploy.env`, and `deploy.sh` itself.

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

> **Note:** The NAS user must have `sudo` privileges. The script pipes the password from `.deploy.env` via `sudo -S`.

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
> For subsequent updates, use `deploy.sh` (which runs `docker compose down` + `up -d --build` via SSH) instead of re-registering.

## Common Commands

All commands are run on the NAS (SSH or Container Manager), not locally.

```bash
# Deploy / update a stack
docker compose up -d

# Rebuild sidecar image and restart
docker compose up -d --build

# View notifier logs
docker compose logs -f watchtower-notifier

# Pull latest images and restart
docker compose pull && docker compose up -d
```

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

### Portainer (`portainer/`)
- Standard Portainer CE deployment. Data persisted in a named volume `portainer_data`.

## Credentials Warning

The following files contain real plaintext credentials that should be moved to `.env`:
- `homepage/docker-compose.yml` — `JELLYFIN_API_KEY`, `PLEX_TOKEN`, `NAS_USERNAME`, `NAS_PASSWORD`
- `homepage/config/services.yaml` — Jellyfin API key, Plex token, NAS username/password, Portainer API key
- `watchtower/docker-compose.yml` — `LINE_CHANNEL_ACCESS_TOKEN`, `LINE_USER_ID`

Use `homepage/.env.example` as the template for the homepage stack's `.env` file.
