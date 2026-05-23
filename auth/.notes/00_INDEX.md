# auth Stack — Index

**สร้าง:** 2026-05-23  
**Ports:** 9091 (Authelia) / 8222 (Vaultwarden)  
**Status:** Complete — รอ one-time setup ก่อน deploy

---

## Architecture

2 services ใน stack เดียว:
- **Authelia** (port 9091) — SSO portal + forward-auth provider สำหรับ nginx sidecars
- **Vaultwarden** (port 8222) — Bitwarden-compatible password vault, auth ของตัวเอง

Docker network `auth_net` (bridge) — stack อื่น join ผ่าน `external: true` เพื่อให้ nginx เรียก Authelia ได้

---

## File Map

| File | Responsibility |
|------|---------------|
| `docker-compose.yml` | 2 services + auth_net, watchtower disabled ทั้งคู่ |
| `authelia/configuration.yml` | Authelia config (default_policy: deny, session, storage, notifier) |
| `authelia/users_database.yml` | User list + Argon2 password hashes |
| `.env.example` | Secrets template |

---

## .env Variables

| Variable | Purpose |
|----------|---------|
| AUTHELIA_SESSION_SECRET | Session signing key |
| AUTHELIA_STORAGE_ENCRYPTION_KEY | SQLite encryption key |
| AUTHELIA_JWT_SECRET | JWT signing key |
| VAULTWARDEN_ADMIN_TOKEN | Vaultwarden admin panel token |

---

## Stacks ที่ใช้ forward-auth

| Stack | Nginx sidecar | Port |
|-------|--------------|------|
| `homepage/` | homepage-nginx | 3000 (HTTPS) |
| `maid-tracker/` | maid-nginx | 5055 |

Pattern nginx config:
```nginx
auth_request /authelia;
error_page 401 =302 http://<NAS_HOST>:9091;
```

---

## One-time Setup (ก่อน deploy ครั้งแรก)

1. `cp .env.example .env` + เติม secrets จริง
2. แทน `<NAS_HOST>` ใน `authelia/configuration.yml` และ nginx configs ของ homepage + maid-tracker
3. Generate Argon2 hash: `docker run --rm authelia/authelia:latest authelia crypto hash generate argon2 --password 'YOUR_PASS'`
4. ใส่ hash ใน `authelia/users_database.yml`
5. Deploy auth ก่อน (สร้าง auth_net): `scripts/deploy.sh -s auth`
6. Redeploy homepage + maid-tracker

---

## Known Gotchas

- **auth ต้อง deploy ก่อนเสมอ** — stack อื่นที่ join auth_net จะ start ไม่ได้ถ้า network ยังไม่มี
- **Watchtower disabled** บนทั้ง Authelia และ Vaultwarden (critical infra)
- **default_policy: deny** — ทุก route ต้อง explicit allow ไม่งั้นถูก block หมด

---

## Change Log

| วันที่ | เรื่อง |
|--------|--------|
| 2026-05-23 | สร้าง stack, migrate homepage + maid-tracker จาก basic auth → Authelia forward-auth |
