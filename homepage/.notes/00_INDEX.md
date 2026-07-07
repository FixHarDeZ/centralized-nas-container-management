# homepage Stack — Index

**Port:** 3000 (HTTP) / 443 (ผ่าน Synology reverse proxy)  
**Status:** Running — basic auth ✅

---

## Architecture

- **homepage** container (ghcr.io/gethomepage/homepage:latest) — dashboard UI, expose 3000
- **nginx** sidecar (nginx:alpine) — reverse proxy + basic auth, port 3000:80

Basic auth ใช้ `.htpasswd` file mount (APR1 hash) — ไม่ใช้ Authelia อีกต่อไป

---

## File Map

| File | Responsibility |
|------|---------------|
| `docker-compose.yml` | 2 services (homepage + nginx), network bridge เดียว — glances ลบออกแล้ว |
| `nginx/nginx.conf` | basic auth + proxy_pass ไปที่ homepage:3000 |
| `nginx/.htpasswd` | APR1 password hash (ไม่ commit, ต้องสร้างก่อน deploy) |
| `config/` | homepage configuration YAML files |

---

## .env Variables

| Variable | Purpose |
|----------|---------|
| NAS_VOLUME_ROOT | Path ที่ mount เข้า container (เช่น `/volume2`) |
| HOMEPAGE_ALLOWED_HOSTS | CSRF protection — list host:port ที่อนุญาต |
| HOMEPAGE_VAR_* | URL/credential สำหรับ widgets ต่างๆ |

---

## Auth Setup

Basic auth ผ่าน nginx:
1. Generate hash: `openssl passwd -apr1 'YOUR_PASSWORD'`
2. สร้างไฟล์ `homepage/nginx/.htpasswd` รูปแบบ: `username:hash`
3. Deploy (ไฟล์จะถูก upload ผ่าน tar+ssh)

---

## Widget Gotchas

- **DSM widget:** ใช้ `http://<LAN_IP>:5000` (ไม่ใช้ HTTPS/domain) — เลี่ยง cert mismatch
- **Auto-block:** ถ้า widget login fail ซ้ำๆ → DSM auto-block Docker IP; fix: ใส่ private subnets ใน Security → Protection → Allow List

---

## Change Log

- **2026-07-07** — เพิ่ม ink-reader widget (Doujin Library, port 5068/15068)
- **2026-06-07** — ลบ glances sidecar ออกจาก stack + widgets.yaml ทั้งหมด
- **2026-05-24** — ย้ายกลับ basic auth; ลบ Authelia forward-auth + auth_net dependency ทั้งหมด
- **2026-05-23** — migrate ไป Authelia forward-auth (auth stack session)
