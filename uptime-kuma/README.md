# Uptime Kuma

Service health monitor with a clean web UI.

**URL:** `http://192.168.50.200:3001`

## Setup

```bash
docker compose up -d
```

## Data

All monitor configs, history, and settings are persisted at `/volume1/docker/uptime-kuma` on the host.

## Homepage Integration

The Homepage dashboard connects to Uptime Kuma via the `uptimekuma` widget using a status page slug. Set `UPTIME_KUMA_SLUG` in `homepage/.env` to match the slug of your public status page.
