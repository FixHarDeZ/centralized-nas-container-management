# Auth Stack Design — Authelia + Vaultwarden

**Date:** 2026-05-23  
**Status:** Approved  
**Scope:** New `auth/` stack + migration of homepage and maid-tracker from basic auth to SSO

---

## Overview

Replace per-stack nginx basic auth (htpasswd) with a centralized SSO system. A single `auth/` Docker Compose stack hosts:

- **Authelia** — SSO portal and forward-auth middleware (port 9091)
- **Vaultwarden** — Bitwarden-compatible self-hosted password vault (port 8222)

Other stacks join a shared Docker network `auth_net` so their nginx sidecars can reach Authelia.

---

## Architecture

```
Synology Reverse Proxy (HTTPS :443)
         │
         ▼
  homepage-nginx:3000
         │  auth_request
         ▼
  authelia:9091  ◄──── maid-tracker-nginx:5055
         │
         ▼
  [session valid] → proxy_pass to app
  [no session]    → redirect to Authelia login page
```

Vaultwarden (port 8222) is accessed directly — it has its own auth (master password + optional 2FA) and does not route through Authelia.

---

## Directory Structure

```
auth/
├── docker-compose.yml       # Authelia + Vaultwarden
├── .env.example             # committed — no secrets
├── .env                     # gitignored — real secrets
├── README.md
└── authelia/
    ├── configuration.yml    # Authelia config — committed (no secrets)
    └── users_database.yml   # Argon2-hashed passwords — committed (safe to commit)
```

---

## docker-compose.yml (outline)

```yaml
networks:
  auth_net:
    name: auth_net
    driver: bridge

services:
  authelia:
    image: authelia/authelia:latest
    container_name: authelia
    restart: unless-stopped
    ports:
      - "9091:9091"
    volumes:
      - ./authelia:/config
      - authelia_data:/data
    env_file: .env
    environment:
      - TZ=Asia/Bangkok
    networks:
      - auth_net

  vaultwarden:
    image: vaultwarden/server:latest
    container_name: vaultwarden
    restart: unless-stopped
    ports:
      - "8222:80"
    volumes:
      - vaultwarden_data:/data
    env_file: .env
    environment:
      - TZ=Asia/Bangkok
    labels:
      - "com.centurylinklabs.watchtower.enable=false"

volumes:
  authelia_data:
  vaultwarden_data:
```

---

## Environment Variables (.env.example)

```
# ─── Authelia secrets ────────────────────────────────────────────────────────
AUTHELIA_JWT_SECRET=
AUTHELIA_SESSION_SECRET=
AUTHELIA_STORAGE_ENCRYPTION_KEY=

# ─── Vaultwarden ─────────────────────────────────────────────────────────────
# Generate with: openssl rand -base64 48
VAULTWARDEN_ADMIN_TOKEN=
```

---

## Authelia configuration.yml (key sections)

```yaml
server:
  address: tcp://0.0.0.0:9091

session:
  name: authelia_session
  secret: '{{ secret "AUTHELIA_SESSION_SECRET" }}'
  expiration: 12h
  inactivity: 45m
  cookies:
    - domain: <NAS_HOST>
      authelia_url: http://<NAS_HOST>:9091

storage:
  encryption_key: '{{ secret "AUTHELIA_STORAGE_ENCRYPTION_KEY" }}'
  local:
    path: /data/db.sqlite3

authentication_backend:
  file:
    path: /config/users_database.yml

access_control:
  default_policy: deny
  rules:
    - domain: "<NAS_HOST>"
      policy: one_factor

notifier:
  filesystem:
    filename: /data/notifications.txt
```

---

## Migration: Existing Stacks

### homepage

**docker-compose.yml** — add `auth_net` to nginx service networks:
```yaml
networks:
  - auth_net

networks:
  auth_net:
    external: true
```

**nginx/nginx.conf** — replace `auth_basic` block with forward-auth:
```nginx
location /authelia {
    internal;
    proxy_pass http://authelia:9091/api/authz/forward-auth;
    proxy_set_header X-Forwarded-Method $request_method;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-Uri $request_uri;
    proxy_set_header Content-Length "";
    proxy_pass_request_body off;
}

location / {
    auth_request /authelia;
    auth_request_set $target_url $scheme://$http_host$request_uri;
    error_page 401 =302 http://<NAS_HOST>:9091/?rd=$target_url;
    proxy_pass http://homepage:3000;
    # ... existing proxy headers
}
```

### maid-tracker

**docker-compose.yml** — add nginx sidecar service:
```yaml
  maid-nginx:
    image: nginx:alpine
    container_name: maid-tracker-nginx
    restart: unless-stopped
    ports:
      - "5055:80"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/conf.d/default.conf:ro
    depends_on:
      - maid-tracker
    networks:
      - default
      - auth_net

  maid-tracker:
    # remove ports: 5055:8000 (now internal only)
    expose:
      - "8000"
```

Add `nginx/nginx.conf` with forward-auth pattern (same as homepage).

---

## Port Map

| Stack | Service | Host Port | Notes |
|---|---|---|---|
| `auth/` | Authelia | 9091 | SSO portal + forward-auth endpoint |
| `auth/` | Vaultwarden | 8222 | Web vault + browser extension |
| `homepage/` | nginx | 3000 | via Synology reverse proxy (443) |
| `maid-tracker/` | nginx (new) | 5055 | replaces direct app port |

---

## Auth Flow

```
Browser → nginx → auth_request → authelia:9091
  [no session] → 401 → nginx error_page → redirect to authelia login
  [login ok]   → Authelia sets cookie → redirect back → auth_request passes
  [session ok] → proxy_pass to app
```

**Failure mode:** If Authelia is down, nginx returns 503 — no access without auth (fail closed).

Vaultwarden has independent auth (master password); Authelia being down does not affect vault access.

---

## Security Notes

- `default_policy: deny` — nothing passes without an explicit rule
- Authelia JWT/session/storage secrets must be generated randomly (`openssl rand -hex 64`)
- Vaultwarden admin panel protected by `VAULTWARDEN_ADMIN_TOKEN`
- Neither service commits real secrets — `.env` is gitignored
- Watchtower disabled on Vaultwarden (`enable=false` label) — update manually to avoid breaking vault data
