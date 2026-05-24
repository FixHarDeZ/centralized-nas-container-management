# Daily Log — auth

---

## 2026-05-24 (session 4) — ลบ Authelia ออกจาก system

### งานที่ทำ

**ตัดสินใจ:** ถอด Authelia SSO ออก — homepage และ maid-tracker กลับใช้ basic auth โดยตรง

**ผลกระทบ:**
- `auth` ถูกลบออกจาก `scripts/deploy.sh` ALL_STACKS list แล้ว (จะไม่ถูก deploy อีกต่อไป)
- `auth_net` network ไม่ถูก reference จาก stack อื่นอีกแล้ว
- Authelia container ยังอยู่บน NAS (ต้องลบด้วย `docker compose down` บน NAS ถ้าต้องการ)
- Vaultwarden ยังทำงานบน port 8222 ได้ตามปกติ (auth ของตัวเอง ไม่ผ่าน Authelia)

**หมายเหตุ:** auth stack files ยังอยู่ใน repo แต่ไม่ถูก deploy แล้ว

---

## 2026-05-24 (session 3) — Authelia running ✅ + แก้ password hash

### งานที่ทำ

**Root cause รอบนี้:** `AUTHELIA_SESSION_COOKIES_0_*` env vars ไม่ support ใน Authelia ("not expected") + `authelia_url` ต้องเป็น HTTPS แต่ทั้ง setup ใช้ HTTP (homepage nginx ก็ port 80)

**Final fix — pin Authelia 4.37.5 + entrypoint.sh:**

`auth/docker-compose.yml`:

- เปลี่ยน image จาก `authelia/authelia:latest` → `authelia/authelia:4.37.5`
- เพิ่ม `entrypoint: ["sh", "/config/entrypoint.sh"]`
- คืน env vars เป็น `AUTHELIA_JWT_SECRET` (correct key สำหรับ 4.37, ไม่ deprecated)
- ลบ `AUTHELIA_SESSION_COOKIES_0_*` และ `AUTHELIA_IDENTITY_VALIDATION_RESET_PASSWORD_JWT_SECRET` ออก

`auth/authelia/configuration.yml` (rewrite เป็น 4.37 format):

- `server.host/port` แทน `server.address` (4.38 syntax)
- `session.domain: 'NAS_HOST_PLACEHOLDER'` (flat string แทน cookies array)
- ลบ `session.cookies` array ทิ้ง

`auth/authelia/entrypoint.sh` (ใหม่):

- `sed "s|NAS_HOST_PLACEHOLDER|${NAS_HOST}|g"` generate `/tmp/configuration.yml` ก่อน start
- Pattern เดียวกับ homepage nginx ที่ใช้ `envsubst`

**Password hash:**

- Generate Argon2id hash ใหม่ด้วย `argon2-cffi` (Python)
- อัปเดต `users_database.yml` — user `admin` login ได้แล้ว

**Result:** `Authelia v4.37.5 is starting` → `Initializing server for non-TLS connections on '[::]:9091'` ✅

---

## 2026-05-23 (session 2) — แก้ Authelia crash-loop หลัง deploy ครั้งแรก

**Root cause:** Authelia 4.38 ไม่ process Go template `{{ env "NAS_HOST" }}` ก่อน URL validation — literal text ถูกส่งเข้า `url.Parse()` โดยตรง → crash.

**fixes:**

`auth/authelia/configuration.yml`:

- ลบ `{{ env "NAS_HOST" }}` ทั้งหมด
- `access_control` เปลี่ยนเป็น `default_policy: 'one_factor'` (ลบ domain-specific rule)
- `session.cookies` ใช้ `127.0.0.1` เป็น placeholder (overridden โดย env vars)

`auth/docker-compose.yml`:

- เพิ่ม `AUTHELIA_SESSION_COOKIES_0_DOMAIN`, `AUTHELIA_SESSION_COOKIES_0_AUTHELIA_URL`, `AUTHELIA_SESSION_COOKIES_0_DEFAULT_REDIRECTION_URL` — Docker Compose expand `${NAS_HOST}` จาก `.env`
- ลบ `NAS_HOST=${NAS_HOST}` ออก (ไม่จำเป็นแล้ว ใช้ผ่าน AUTHELIA_* vars โดยตรง)

**Secrets errors (session 1)** resolved แล้ว — user กรอก `.env` ครบ

---

## 2026-05-23 (session 1) — สร้าง auth stack: Authelia SSO + Vaultwarden + migrate homepage/maid-tracker

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
