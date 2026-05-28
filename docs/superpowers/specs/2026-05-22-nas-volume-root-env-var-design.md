# Design: Centralise NAS volume root path in .env

**Date:** 2026-05-22  
**Status:** Approved

## Problem

All three Docker Compose stacks that mount host paths hardcode `/volume1` directly in their YAML. Migrating from `volume1` to `volume2` requires hunting through multiple files. The `.env` already has `NAS_TARGET_PATH=/volume2/docker` for `deploy.sh`, but compose files do not use it.

## Goal

One edit in `.env` (`NAS_VOLUME_ROOT=<value>`) propagates to every compose volume mount and the Homepage disk monitor widget automatically.

## Out of scope

- `deploy.sh` and `NAS_TARGET_PATH` — no changes needed; deploy.sh already reads `NAS_TARGET_PATH` from env
- Stacks with no `/volume1` references: `maid-tracker`, `portainer`, `watchtower`, `line-secretary`, `torrentwatch`

## Approach: Add NAS_VOLUME_ROOT, keep NAS_TARGET_PATH

### New variable

```env
NAS_VOLUME_ROOT=/volume1   # root of the Synology storage volume
```

Added to `.env` and `.env.example` under the `NAS Deployment` section, above `NAS_TARGET_PATH`.

### .env relationship

```
NAS_VOLUME_ROOT=/volume1         ← change this when moving volumes
NAS_TARGET_PATH=/volume2/docker  ← also update this (deploy.sh uses it directly)
```

Docker Compose `.env` does not expand variables within itself, so both must be independent lines. When migrating to `volume2`, update both values in `.env` only.

### Compose file changes

| File | Change |
|---|---|
| `uptime-kuma/docker-compose.yml` | `/volume2/docker/uptime-kuma` → `${NAS_VOLUME_ROOT}/docker/uptime-kuma` |
| `homepage/docker-compose.yml` | `/volume1:/volume1:ro` → `${NAS_VOLUME_ROOT}:${NAS_VOLUME_ROOT}:ro` |
| `homepage/docker-compose.yml` | Add env `HOMEPAGE_VAR_VOLUME_ROOT=${NAS_VOLUME_ROOT}` |
| `jellyfin/docker-compose.yml` | All 6 volume lines: `/volume1/...` → `${NAS_VOLUME_ROOT}/...` |

### Homepage widgets.yaml

`homepage/config/widgets.yaml` is read by the Homepage app inside the container using its own `{{HOMEPAGE_VAR_xxx}}` substitution, not Docker Compose interpolation.

```yaml
disk:
  - "{{HOMEPAGE_VAR_VOLUME_ROOT}}"
```

`HOMEPAGE_VAR_VOLUME_ROOT` is injected via the `homepage` service's `environment` block in its compose file.

## Files changed (6 total)

1. `.env` — add `NAS_VOLUME_ROOT=/volume1`
2. `.env.example` — same
3. `uptime-kuma/docker-compose.yml` — 1 volume line
4. `homepage/docker-compose.yml` — 1 volume line + 1 env var
5. `jellyfin/docker-compose.yml` — 6 volume lines
6. `homepage/config/widgets.yaml` — 1 disk path line

## Verification after deploy

- `docker compose config` in each affected stack should show resolved absolute paths (no `${...}` literals)
- Homepage dashboard disk widget should display the correct volume
- Jellyfin library paths should remain accessible (no re-scan needed unless paths change)
