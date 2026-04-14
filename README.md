# centralized-nas-container-management

Docker stacks for Synology DS925+ NAS, managed via Synology Container Manager.

![Homepage Dashboard](screenshots/Homepage.png)

## Stacks

| Directory | Purpose | Port(s) |
|---|---|---|
| `homepage/` | Dashboard UI (gethomepage/homepage) | 3000 |
| `jellyfin/` | Media server with NVIDIA GPU transcoding | 8096 |
| `maid-tracker/` | Household worker attendance & salary tracker | 5055 |
| `portainer/` | Docker management UI | 9000, 9443 |
| `uptime-kuma/` | Service health monitor | 3001 |
| `watchtower/` | Auto-update containers + LINE notification sidecar | — |

## Uploading to NAS

Use `deploy.sh` to sync the project from your local machine to `/volume1/docker` on the NAS over SSH/rsync.

```bash
# 1. Copy the example config and fill in your password
cp .deploy.env.example .deploy.env
nano .deploy.env

# 2. Install sshpass (one-time, macOS)
brew install sshpass

# 3. Run
./deploy.sh
```

`.deploy.env` is gitignored — never commit it. Use `.deploy.env.example` as the reference template.

## Adding a Stack to Container Manager (DSM 7.3.2)

After uploading files to the NAS via `deploy.sh`, register each stack in Synology Container Manager:

1. Open **DSM** → **Container Manager** → **Project** tab
2. Click **Create**
3. Fill in:
   - **Project Name** — e.g. `homepage`
   - **Path** — point to the stack directory on NAS, e.g. `/volume1/docker/homepage`
     Container Manager will automatically detect `docker-compose.yml` in that path
4. Click **Next** → review the compose config → click **Build**
5. Container Manager pulls images and starts the containers

> For stacks with a local build (e.g. `watchtower`), Container Manager will build the image on first run. On subsequent updates, use `deploy.sh` with the restart option instead of re-registering the project.

## Stack Setup

Each stack lives in its own directory. Before registering in Container Manager, copy the example env file and fill in real values **on your local machine**, then upload via `deploy.sh`:

```bash
# Homepage
cp homepage/.env.example homepage/.env

# Watchtower
cp watchtower/.env.example watchtower/.env
```

## Architecture Notes

- **Homepage** — config is in `homepage/config/` (YAML, no rebuild needed). Secrets are injected via `HOMEPAGE_VAR_*` env vars and referenced in `services.yaml` as `{{HOMEPAGE_VAR_*}}`.
- **Maid Tracker** — FastAPI + SQLite single-container app. Database persisted in a named volume `maid_tracker_data`. Local build; no env file required.
- **Watchtower** — runs two services: the updater and a Python sidecar that tails Watchtower logs via raw Docker socket HTTP and pushes LINE notifications. The sidecar is excluded from auto-updates via `com.centurylinklabs.watchtower.enable=false`.
- **Portainer** — standard CE deployment, data persisted in `portainer_data` named volume.
