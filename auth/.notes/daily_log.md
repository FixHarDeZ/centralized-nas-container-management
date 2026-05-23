# Daily Log — auth

---

## 2026-05-23 — สร้าง auth stack: Authelia SSO + Vaultwarden + migrate homepage/maid-tracker

### งานที่ทำ

**สร้าง `auth/` stack ใหม่ (Authelia + Vaultwarden):**
- `auth/docker-compose.yml` — 2 services: Authelia (SSO portal + forward-auth, port 9091) + Vaultwarden (Bitwarden-compatible vault, port 8222)
- สร้าง Docker bridge network `auth_net` ที่ stack อื่น join ผ่าน `external: true`
- `auth/authelia/configuration.yml` — Authelia v4.38+ config, `default_policy: deny` (fail-closed)
- `auth/authelia/users_database.yml` — admin user skeleton + Argon2 password placeholder
- `auth/.env.example` — AUTHELIA_SESSION_SECRET, AUTHELIA_STORAGE_ENCRYPTION_KEY, AUTHELIA_JWT_SECRET, VAULTWARDEN_ADMIN_TOKEN
- Watchtower disabled บนทั้ง 2 services

**Migrate homepage → Authelia forward-auth:**
- ลบ `command:` block (htpasswd) ออกจาก nginx service
- nginx join `auth_net` เพื่อเข้าถึง authelia container
- `nginx.conf` แทน `auth_basic` block ด้วย `auth_request /authelia` + `error_page 401 =302 http://<NAS_HOST>:9091`
- ลบ `NGINX_BASIC_AUTH_*` ออกจาก `.env.example`

**Migrate maid-tracker → Authelia forward-auth:**
- เพิ่ม nginx sidecar (`maid-nginx`) — port 5055:80 พร้อม forward-auth
- maid-tracker app เปลี่ยน `ports: "5055:8000"` → `expose: "8000"` (ไม่เปิด host โดยตรงอีกต่อไป)
- สร้าง `maid-tracker/nginx/nginx.conf` ด้วย pattern เดียวกับ homepage

**อื่นๆ:**
- เพิ่ม `auth` ใน `scripts/deploy.sh` ALL_STACKS (ต้องรันก่อน stack อื่น เพราะสร้าง `auth_net`)
- อัปเดต `CLAUDE.md`, `README.md`, `homepage/README.md`, `maid-tracker/README.md`

### ขั้นตอนก่อน deploy (one-time setup)

1. `cp auth/.env.example auth/.env` แล้วเติม secrets จริง
2. แทน `<NAS_HOST>` ใน `auth/authelia/configuration.yml`, `homepage/nginx/nginx.conf`, `maid-tracker/nginx/nginx.conf`
3. Generate Argon2 hash จริง:
   ```bash
   docker run --rm authelia/authelia:latest authelia crypto hash generate argon2 --password 'YOUR_PASS'
   ```
4. ใส่ hash ใน `auth/authelia/users_database.yml`
5. Deploy `auth` ก่อน แล้วค่อย redeploy `homepage` + `maid-tracker`
