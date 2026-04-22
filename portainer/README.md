# Portainer

![Portainer](../screenshots/Portainer.png)

Docker management UI (Community Edition).

**Local URL:** `http://<NAS_IP>:9000`
**External URL:** `https://fixhardez.synology.me:9444` (via Synology Reverse Proxy)

## Setup

Upload via `deploy.sh` from your local machine and register the stack in Container Manager (see root README).

## HTTPS

HTTPS is handled by **Synology Reverse Proxy** (DSM → Control Panel → Login Portal → Advanced):

| Source | Destination |
|---|---|
| `https://fixhardez.synology.me:9444` | `http://localhost:9000` |

Portainer itself runs plain HTTP on port 9000. No custom cert configuration needed inside the container.

## Data

Container data is persisted in a named Docker volume `portainer_data`.

## Homepage Integration

The Homepage dashboard connects to Portainer via the `portainer` widget. Set `PORTAINER_KEY` in `homepage/.env` to an API key generated from **Account Settings → Access Tokens** in the Portainer UI.
