# centralized-nas-container-management

Docker stacks for Synology DS925+ NAS, managed via Synology Container Manager or Docker CLI.

![Homepage Dashboard](screenshots/Homepage.png)

## Stacks

| Directory | Purpose | Port(s) |
|---|---|---|
| `homepage/` | Dashboard UI (gethomepage/homepage) | 3000 |
| `jellyfin/` | Media server with NVIDIA GPU transcoding | 8096 |
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

## Stack Setup

Each stack lives in its own directory. Before deploying on the NAS, copy the example env file and fill in real values:

```bash
# Homepage
cp homepage/.env.example homepage/.env

# Watchtower
cp watchtower/.env.example watchtower/.env
```

Then deploy the stack from its directory on the NAS:

```bash
cd homepage   # or portainer / watchtower
docker compose up -d
```

For watchtower (has a local build):

```bash
cd watchtower
docker compose up -d --build
```

## Common Commands

```bash
# View logs
docker compose logs -f

# Pull latest images and restart
docker compose pull && docker compose up -d

# Stop a stack
docker compose down
```

## Architecture Notes

- **Homepage** — config is in `homepage/config/` (YAML, no rebuild needed). Secrets are injected via `HOMEPAGE_VAR_*` env vars and referenced in `services.yaml` as `{{HOMEPAGE_VAR_*}}`.
- **Watchtower** — runs two services: the updater and a Python sidecar that tails Watchtower logs via raw Docker socket HTTP and pushes LINE notifications. The sidecar is excluded from auto-updates via `com.centurylinklabs.watchtower.enable=false`.
- **Portainer** — standard CE deployment, data persisted in `portainer_data` named volume.
