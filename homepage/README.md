# Homepage

Dashboard UI for the home lab, powered by [gethomepage/homepage](https://gethomepage.dev).

**URL:** `http://<NAS_IP>:3000`

## File Structure

```
homepage/
├── .env                  ← credentials (gitignored, copy from .env.example)
├── .env.example          ← template
├── docker-compose.yml
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
# Fill in real values in .env
docker compose up -d
```

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
