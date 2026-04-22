# Jellyfin

![Jellyfin](../screenshots/Jellyfin.png)

Media server with NVIDIA GPU hardware transcoding.

**Local URL:** `http://<NAS_IP>:8096`
**External URL:** `https://<NAS_HOST>:8097` (via Synology Reverse Proxy)

## Ports & Reverse Proxy

| Layer | Detail |
|---|---|
| Container | HTTP on port `8096` |
| Host port | `8096` (plain HTTP, LAN only) |
| Synology Reverse Proxy | `https://…:8097` → `http://localhost:8096` |
| Router port forward | External `8097` → NAS `8097` |

TLS is terminated by Synology Reverse Proxy — Jellyfin itself runs plain HTTP internally.

## Setup

Upload via `deploy.sh` from your local machine and register the stack in Container Manager (see root README).

## Media Paths

| Container Path | Host Path | Mode |
|---|---|---|
| `/data/movies` | `/volume1/Movies` | read-only |
| `/data/series` | `/volume1/Series` | read-only |
| `/data/concerts` | `/volume1/Concerts` | read-only |
| `/data/private` | `/volume1/private_media/porn` | read-only |
| `/config` | `/volume1/docker/jellyfin/config` | read-write |
| `/cache` | `/volume1/docker/jellyfin/cache` | read-write |

## Hardware Transcoding

Uses NVIDIA GPU via the `NVIDIA_VISIBLE_DEVICES=all` and `NVIDIA_DRIVER_CAPABILITIES=compute,video,utility` env vars. Requires the NVIDIA Container Toolkit installed on the host.

To enable hardware transcoding in Jellyfin: **Dashboard → Playback → Transcoding → NVIDIA NVENC**.
