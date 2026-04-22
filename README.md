# centralized-nas-container-management

Docker stacks for Synology DS925+ NAS, managed via Synology Container Manager.

![Homepage Dashboard](screenshots/Homepage.png)

## Stacks

| Directory | Purpose | Local Port | External (Synology Reverse Proxy) |
|---|---|---|---|
| `homepage/` | Dashboard UI (gethomepage/homepage) | 3000 (nginx) | `https://…:443` |
| `jellyfin/` | Media server with NVIDIA GPU transcoding | 8096 | `https://…:8097` |
| `maid-tracker/` | Household worker attendance & salary tracker | 5055 | `https://…:5056` |
| `portainer/` | Docker management UI | 9000 | `https://…:9444` |
| `uptime-kuma/` | Service health monitor | 3001 | `https://…:3002` |
| `watchtower/` | Auto-update containers + LINE notification sidecar | — | — |

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

- **Homepage** — sits behind an Nginx reverse proxy that handles HTTPS (port 3000 on host → 443 inside container) and HTTP Basic Auth. TLS uses the Synology system certificate mounted from `/usr/syno/etc/certificate/system/default/`. Config files in `homepage/config/` are hot-reloaded. Secrets are injected via `HOMEPAGE_VAR_*` env vars and referenced in `services.yaml` as `{{HOMEPAGE_VAR_*}}`.
- **External HTTPS** — all stacks except homepage use **Synology Reverse Proxy** (DSM → Control Panel → Login Portal → Advanced) for HTTPS termination. Synology handles the SSL cert and auto-renewal; containers run plain HTTP internally.
- **DSM / Download Station widgets** — Homepage connects to the Synology API over HTTP on port 5000 (`NAS_LOCAL_URL=http://192.168.50.200:5000`) to avoid SSL certificate mismatch when using an IP address.
- **Maid Tracker** — FastAPI + SQLite single-container app. Database persisted in a named volume `maid_tracker_data`. Local build; no env file required.
- **Watchtower** — runs two services: the updater and a Python sidecar that tails Watchtower logs via raw Docker socket HTTP and pushes LINE notifications. The sidecar is excluded from auto-updates via `com.centurylinklabs.watchtower.enable=false`.
- **Portainer** — standard CE deployment on port 9000. HTTPS is handled upstream by Synology Reverse Proxy. Data persisted in `portainer_data` named volume.

## SSL Certificate Auto-Renewal

Synology auto-renews its Let's Encrypt certificate every 90 days. The Homepage Nginx container reads the cert at startup, so a monthly reload is needed to pick up renewed certs:

**DSM → Control Panel → Task Scheduler → Create → Scheduled Task → User-defined script**

| Setting | Value |
|---|---|
| Schedule | Monthly, day 1, 03:00 |
| User | root |
| Command | `docker exec homepage-nginx nginx -s reload` |
