# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This repo manages Docker containers deployed on a Synology DS925+ NAS. It is a collection of `docker-compose.yml` stacks, not an application codebase. Each subdirectory is an independent stack deployed to the NAS via Synology Container Manager (or direct Docker CLI).

## Stacks

| Directory | Purpose | Port(s) |
|---|---|---|
| `homepage/` | Dashboard UI (gethomepage/homepage) | 3000 |
| `portainer/` | Docker management UI | 9000, 9443 |
| `watchtower/` | Auto-update containers + LINE notification sidecar | — |

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
