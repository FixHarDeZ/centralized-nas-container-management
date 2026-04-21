# Homepage

![Homepage](../screenshots/Homepage.png)

Dashboard UI for the home lab, powered by [gethomepage/homepage](https://gethomepage.dev).

**URL:** `https://<NAS_IP>:3000`  ← HTTPS + HTTP Basic Auth

## File Structure

```
homepage/
├── .env                  ← credentials (gitignored, copy from .env.example)
├── .env.example          ← template
├── docker-compose.yml
├── nginx/
│   └── nginx.conf        ← Nginx reverse proxy + Basic Auth config
└── config/
    ├── settings.yaml     ← theme, layout
    ├── widgets.yaml      ← top bar: datetime, search, resources
    ├── services.yaml     ← service cards
    ├── bookmarks.yaml    ← bookmark links
    └── docker.yaml       ← docker socket config
```

## Setup

```bash
cp .env.example .env
# Fill in real values — including BASIC_AUTH_USER and BASIC_AUTH_PASS
```

Then upload via `deploy.sh` from your local machine and register the stack in Container Manager (see root README).

## HTTPS + HTTP Basic Auth

Access to the homepage is protected by Nginx with TLS and HTTP Basic Auth.

| Item | Detail |
|------|--------|
| Credentials | Set `BASIC_AUTH_USER` and `BASIC_AUTH_PASS` in `.env` |
| Hash generation | `htpasswd` runs automatically on container startup — no manual hashing needed |
| Port layout | Nginx listens on **443 SSL**, exposed on host port **3000**; homepage is internal-only |
| TLS certificate | Synology default cert mounted from `/usr/syno/etc/certificate/system/default/` — uses `RSA-cert.pem` / `RSA-privkey.pem` |

To change the password: update `.env` and restart the stack (`docker compose down && docker compose up -d`).

## Secrets Injection

Credentials are never hardcoded in config files. They flow through two layers:

1. Docker Compose reads `${VAR}` from `.env` and passes them as `HOMEPAGE_VAR_*` container env vars.
2. `services.yaml` references them as `{{HOMEPAGE_VAR_*}}` — Homepage interpolates these at runtime.

## Configuration

All config files in `config/` are hot-reloaded — no container restart needed after edits.

| File | Purpose |
|---|---|
| `settings.yaml` | Theme, layout, title |
| `widgets.yaml` | Top bar widgets (clock, search, system resources) |
| `services.yaml` | Service cards with API widgets |
| `bookmarks.yaml` | Quick-access links |
| `docker.yaml` | Docker socket connection for container status widgets |
