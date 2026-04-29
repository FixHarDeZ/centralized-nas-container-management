# centralized-nas-container-management

Docker stacks for Synology DS925+ NAS, managed via Synology Container Manager.

![Homepage Dashboard](screenshots/Homepage.png)

## Stacks

| Directory | Purpose | Local Port | External (Synology Reverse Proxy) |
|---|---|---|---|
| `homepage/` | Dashboard UI (gethomepage/homepage) | `3000` (Nginx + HTTPS inside) | `https://…:443` |
| `jellyfin/` | Media server with NVIDIA GPU transcoding | `8096` | `https://…:8097` |
| `maid-tracker/` | Household worker attendance & salary tracker | `5055` | `https://…:5056` |
| `portainer/` | Docker management UI | `9000` | `https://…:9444` |
| `uptime-kuma/` | Service health monitor | `3001` | `https://…:3002` |
| `watchtower/` | Auto-update containers + LINE notification sidecar | — | — |
| `line-secretary/` | AI personal assistant LINE bot backed by Notion | `5057` | `https://…:5058` |

### Reverse Proxy Summary

All stacks except `watchtower` are exposed externally via **Synology Reverse Proxy** (DSM → Control Panel → Login Portal → Advanced). Synology handles TLS termination; containers run plain HTTP internally.

| Stack | Synology RP Source | → Destination |
|---|---|---|
| homepage | `https://…:443` | `http://localhost:3000` → internal Nginx → Homepage |
| jellyfin | `https://…:8097` | `http://localhost:8096` |
| maid-tracker | `https://…:5056` | `http://localhost:5055` |
| portainer | `https://…:9444` | `http://localhost:9000` |
| uptime-kuma | `https://…:3002` | `http://localhost:3001` |
| line-secretary | `https://…:5058` | `http://localhost:5057` |

> Your router must forward each **external port → NAS** so traffic reaches Synology Reverse Proxy. Homepage is the only exception — it has its own Nginx inside the container that handles TLS, so Synology RP simply forwards `:443` to port `3000` unencrypted and lets Nginx take over from there.

## Environment Variables

**All stacks share a single `.env` at the project root** — edit once, then deploy.

```bash
# First time: copy the template and fill in real values
cp .env.example .env
nano .env
```

`.env` is gitignored — never commit it. Use `.env.example` as the reference template.

## Uploading to NAS

Use `deploy.sh` to sync the project from your local machine to `/volume1/docker` on the NAS over SSH (key-based auth). The script uploads all files and copies `.env` to the NAS automatically.

**Prerequisites (one-time setup)**

1. Generate an SSH key and copy it to the NAS:
   ```bash
   ssh-keygen -t ed25519 -C "nas-key"
   ssh-copy-id -i ~/.ssh/id_ed25519.pub -p 2222 <NAS_USER>@<NAS_HOST>
   ```
2. In DSM → Control Panel → Terminal & SNMP, set SSH port to **2222** and disable password auth in `/etc/ssh/sshd_config` (`PasswordAuthentication no`).

**Deploy**

```bash
# 1. Copy the example config and fill in your details (first time only)
cp .env.example .env
nano .env

# 2. Run
./deploy.sh
```

> `NAS_SUDO_PASSWORD` in `.env` is only used to run `sudo docker compose` during stack restarts. SSH itself uses key auth exclusively.

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

> For stacks with a local build (e.g. `watchtower`, `maid-tracker`), Container Manager will build the image on first run. On subsequent updates, use `deploy.sh` with the restart option instead of re-registering the project.

## Architecture Notes

- **Homepage** — sits behind an Nginx reverse proxy that handles HTTPS (port 3000 on host → 443 inside container) and HTTP Basic Auth (credentials: `NGINX_BASIC_AUTH_USER` / `NGINX_BASIC_AUTH_PASS`). TLS uses the Synology system certificate mounted from `/usr/syno/etc/certificate/system/default/`. Config files in `homepage/config/` are hot-reloaded. Secrets are injected via `HOMEPAGE_VAR_*` env vars from root `.env` and referenced in `services.yaml` as `{{HOMEPAGE_VAR_*}}`. DSM/Download Station widgets reuse `NAS_USER` and `NAS_SUDO_PASSWORD` directly.
- **External HTTPS** — all stacks except homepage use **Synology Reverse Proxy** (DSM → Control Panel → Login Portal → Advanced) for HTTPS termination. Synology handles the SSL cert and auto-renewal; containers run plain HTTP internally.
- **DSM / Download Station widgets** — Homepage connects to the Synology API over HTTP (`HOMEPAGE_VAR_NAS_URL=http://192.168.x.x:5000`) to avoid SSL certificate mismatch when using an IP address.
- **Maid Tracker** — FastAPI + SQLite single-container app. Database persisted in a named volume `maid_tracker_data`. Local build. The container runs on port 5055 internally; external access is via **Synology Reverse Proxy** on port 5056 (`https://<NAS_HOST>:5056`), which handles TLS termination — the container itself serves plain HTTP.
- **Watchtower** — runs two services: the updater and a Python sidecar that tails Watchtower logs via raw Docker socket HTTP and pushes LINE notifications. The sidecar is excluded from auto-updates via `com.centurylinklabs.watchtower.enable=false`.
- **Portainer** — standard CE deployment on port 9000. HTTPS is handled upstream by Synology Reverse Proxy. Data persisted in `portainer_data` named volume.

