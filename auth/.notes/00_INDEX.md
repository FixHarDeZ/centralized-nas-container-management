# auth Stack — Index

**สร้าง:** 2026-05-23  
**Ports:** 9091 (Authelia) / 8222 (Vaultwarden)  
**Status:** ⚠️ ถอดออกจาก deploy pipeline แล้ว (2026-05-24) — Vaultwarden ยังทำงานบน NAS, Authelia ถูกตัดออก

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
| `docker-compose.yml` | 2 services + auth_net, pin Authelia 4.37.5, watchtower disabled ทั้งคู่ |
| `authelia/entrypoint.sh` | exec authelia โดยตรง (ไม่มี sed แล้ว) |
| `authelia/configuration.yml` | Authelia 4.37 format: server.host/port, ไม่มี session.domain (cookie scoped ตาม access host) |
| `authelia/users_database.yml` | User list + Argon2id password hashes |
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
error_page 401 =302 http://<AUTHELIA_HOST>:9091;   # ใช้ IP ตรง ไม่ใช้ DDNS domain
```

`AUTHELIA_HOST` ตั้งในแต่ละ stack's `.env` (ค่า LAN IP เช่น `192.168.50.200`) เพราะ Authelia session cookie ต้อง scope ตาม host ที่เข้า

---

## One-time Setup (ก่อน deploy ครั้งแรก)

1. `cp .env.example .env` + เติม: `AUTHELIA_SESSION_SECRET`, `AUTHELIA_STORAGE_ENCRYPTION_KEY`, `AUTHELIA_JWT_SECRET`, `VAULTWARDEN_ADMIN_TOKEN`
2. Generate Argon2id hash: `docker run --rm authelia/authelia:4.37.5 authelia hash-password -- 'YOUR_PASS'`
3. ใส่ hash ใน `authelia/users_database.yml`
4. Deploy auth ก่อน (สร้าง auth_net): `bash scripts/deploy.sh`
5. Redeploy homepage + maid-tracker

---

## Known Gotchas

- **auth ต้อง deploy ก่อนเสมอ** — stack อื่นที่ join auth_net จะ start ไม่ได้ถ้า network ยังไม่มี
- **Watchtower disabled** บนทั้ง Authelia และ Vaultwarden (critical infra)
- **Pin 4.37.5 ห้ามใช้ latest** — Authelia 4.38 enforce HTTPS สำหรับ `authelia_url` แต่ setup นี้ HTTP-only; `AUTHELIA_SESSION_COOKIES_0_*` env vars ก็ไม่ support ใน 4.38
- **ไม่มี session.domain ใน configuration** — cookie จะ scope ตาม host ที่ browser ใช้เข้า Authelia (เพื่อรองรับ IP access บน LAN); ถ้าอยากใช้ domain ต้องเพิ่ม local DNS หรือ /etc/hosts ให้ domain → NAS IP
- **AUTHELIA_HOST ต้องตั้งค่าใน homepage/.env และ maid-tracker/.env** ด้วย LAN IP เช่น `192.168.50.200`

---

## Change Log

- **2026-05-23** — สร้าง stack, migrate homepage + maid-tracker จาก basic auth → Authelia forward-auth
- **2026-05-23** — แก้ crash-loop (รอบ 1): ลบ template syntax, ทดสอบ AUTHELIA_SESSION_COOKIES_0_* (ไม่ work)
- **2026-05-24** — แก้ crash-loop (รอบ 2): pin 4.37.5, entrypoint.sh+sed, rewrite config → running ✅
