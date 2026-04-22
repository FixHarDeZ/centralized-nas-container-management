# Uptime Kuma

![Uptime Kuma](../screenshots/Uptime-kuma.png)

Service health monitor with a clean web UI.

**Local URL:** `http://<NAS_IP>:3001`
**External URL:** `https://<NAS_HOST>:3002` (via Synology Reverse Proxy)

## Ports & Reverse Proxy

| Layer | Detail |
|---|---|
| Container | HTTP on port `3001` |
| Host port | `3001` (plain HTTP, LAN only) |
| Synology Reverse Proxy | `https://…:3002` → `http://localhost:3001` |
| Router port forward | External `3002` → NAS `3002` |

TLS is terminated by Synology Reverse Proxy — Uptime Kuma itself runs plain HTTP internally.

## Setup

Upload via `deploy.sh` from your local machine and register the stack in Container Manager (see root README).

## Data

All monitor configs, history, and settings are persisted at `/volume1/docker/uptime-kuma` on the host.

## Homepage Integration

The Homepage dashboard connects to Uptime Kuma via the `uptimekuma` widget using a status page slug. Set `HOMEPAGE_VAR_UPTIME_KUMA_SLUG` in root `.env` to match the slug of your public status page.
