# Uptime Kuma

![Uptime Kuma](../screenshots/uptime-kuma.png)

Service health monitor with a clean web UI.

**Local URL:** `http://<NAS_IP>:3001`
**External URL:** `https://<NAS_HOST>:13001` (via Synology Reverse Proxy)

## Ports & Reverse Proxy

| Layer | Detail |
|---|---|
| Container | HTTP on port `3001` |
| Host port | `3001` (plain HTTP, LAN only) |
| Synology Reverse Proxy | `https://…:13001` → `http://localhost:3001` |
| Router port forward | External `13001` → NAS `13001` |

TLS is terminated by Synology Reverse Proxy — Uptime Kuma itself runs plain HTTP internally.

## Setup

Upload via `deploy.sh` from your local machine and register the stack in Container Manager (see root README).

## Data

All monitor configs, history, and settings are persisted at `/volume2/docker/uptime-kuma` on the host.

## Homepage Integration

The Homepage dashboard connects to Uptime Kuma via the `uptimekuma` widget using a status page slug. Set `HOMEPAGE_VAR_UPTIME_KUMA_SLUG` in root `.env` to match the slug of your public status page.
