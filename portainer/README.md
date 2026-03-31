# Portainer

Docker management UI (Community Edition).

**URL:** `http://192.168.50.200:9000` | `https://192.168.50.200:9443`

## Setup

```bash
docker compose up -d
```

## Data

Container data is persisted in a named Docker volume `portainer_data`.

## Homepage Integration

The Homepage dashboard connects to Portainer via the `portainer` widget. Set `PORTAINER_KEY` in `homepage/.env` to an API key generated from **Account Settings → Access Tokens** in the Portainer UI.
