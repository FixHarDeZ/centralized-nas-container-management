# Auth Stack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** สร้าง `auth/` stack ที่รวม Authelia (SSO) + Vaultwarden (password vault) แล้ว migrate homepage และ maid-tracker จาก nginx basic auth มาใช้ Authelia forward-auth

**Architecture:** `auth/` docker-compose สร้าง Docker network `auth_net` (bridge) ที่ stack อื่น join ผ่าน `external: true`. Nginx sidecar ของแต่ละ stack เรียก Authelia `/api/authz/forward-auth` ผ่าน `auth_request`. Vaultwarden ไม่ผ่าน Authelia เพราะมี auth ของตัวเองอยู่แล้ว

**Tech Stack:** Authelia v4.38+ (SSO), Vaultwarden (Bitwarden-compatible vault), nginx:alpine (forward-auth proxy), Docker Compose networks

**Design spec:** `docs/superpowers/specs/2026-05-23-auth-stack-design.md`

---

## File Map

**Create:**
- `auth/docker-compose.yml`
- `auth/.env.example`
- `auth/README.md`
- `auth/authelia/configuration.yml`
- `auth/authelia/users_database.yml`
- `maid-tracker/nginx/nginx.conf`

**Modify:**
- `homepage/docker-compose.yml` — add `auth_net`, ลบ htpasswd command, ลบ env_file จาก nginx
- `homepage/nginx/nginx.conf` — แทน `auth_basic` ด้วย forward-auth block
- `homepage/.env.example` — ลบ `NGINX_BASIC_AUTH_*` vars
- `maid-tracker/docker-compose.yml` — `ports:` → `expose:`, add nginx sidecar, add networks
- `CLAUDE.md` — เพิ่ม auth/ ใน stacks table
- `README.md` — เพิ่ม auth/ ใน stacks table

---

## Task 1: Create `auth/` stack core files

**Files:**
- Create: `auth/docker-compose.yml`
- Create: `auth/.env.example`

- [ ] **Step 1: Create `auth/docker-compose.yml`**

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
    environment:
      - TZ=Asia/Bangkok
      - AUTHELIA_SESSION_SECRET=${AUTHELIA_SESSION_SECRET}
      - AUTHELIA_STORAGE_ENCRYPTION_KEY=${AUTHELIA_STORAGE_ENCRYPTION_KEY}
      - AUTHELIA_IDENTITY_VALIDATION_RESET_PASSWORD_JWT_SECRET=${AUTHELIA_JWT_SECRET}
    networks:
      - auth_net
    labels:
      - "com.centurylinklabs.watchtower.enable=false"

  vaultwarden:
    image: vaultwarden/server:latest
    container_name: vaultwarden
    restart: unless-stopped
    ports:
      - "8222:80"
    volumes:
      - vaultwarden_data:/data
    environment:
      - TZ=Asia/Bangkok
      - ADMIN_TOKEN=${VAULTWARDEN_ADMIN_TOKEN}
      - WEBSOCKET_ENABLED=true
    labels:
      - "com.centurylinklabs.watchtower.enable=false"

volumes:
  authelia_data:
  vaultwarden_data:
```

- [ ] **Step 2: Create `auth/.env.example`**

```
# ─── Authelia secrets (generate each with: openssl rand -hex 64) ──────────────
AUTHELIA_SESSION_SECRET=
AUTHELIA_STORAGE_ENCRYPTION_KEY=
AUTHELIA_JWT_SECRET=

# ─── Vaultwarden admin panel token ───────────────────────────────────────────
# Generate with: openssl rand -base64 48
VAULTWARDEN_ADMIN_TOKEN=
```

- [ ] **Step 3: Validate compose syntax**

Run:
```bash
cd auth && docker compose config
```
Expected: YAML output with no errors, services `authelia` and `vaultwarden` visible.

- [ ] **Step 4: Commit**

```bash
git add auth/docker-compose.yml auth/.env.example
git commit -m "feat(auth): add auth stack skeleton — Authelia + Vaultwarden compose"
```

---

## Task 2: Create Authelia configuration

**Files:**
- Create: `auth/authelia/configuration.yml`
- Create: `auth/authelia/users_database.yml`

- [ ] **Step 1: Create `auth/authelia/configuration.yml`**

แทนที่ `<NAS_HOST>` ทุก occurrence ด้วย hostname จริงของ NAS (เช่น LAN IP `192.168.1.x` หรือ DDNS hostname)

Authelia v4.38+ รับ secrets ผ่าน env vars อัตโนมัติ (`AUTHELIA_SESSION_SECRET` → `session.secret`, `AUTHELIA_STORAGE_ENCRYPTION_KEY` → `storage.encryption_key`) ไม่ต้อง reference ใน config file

ไฟล์ที่ต้อง commit:
```yaml
server:
  address: 'tcp://0.0.0.0:9091'

log:
  level: 'info'

authentication_backend:
  file:
    path: '/config/users_database.yml'
    password:
      algorithm: argon2
      argon2:
        iterations: 3
        memory: 65536
        parallelism: 4
        key_length: 32
        salt_length: 16

access_control:
  default_policy: 'deny'
  rules:
    - domain: '<NAS_HOST>'
      policy: 'one_factor'

session:
  name: 'authelia_session'
  expiration: '12h'
  inactivity: '45m'
  cookies:
    - domain: '<NAS_HOST>'
      authelia_url: 'http://<NAS_HOST>:9091'
      default_redirection_url: 'http://<NAS_HOST>:3000'

storage:
  local:
    path: '/data/db.sqlite3'

notifier:
  filesystem:
    filename: '/data/notifications.txt'
```

- [ ] **Step 2: Generate Argon2 password hash**

รัน command นี้เพื่อ hash password ที่จะใช้ login Authelia:
```bash
docker run --rm authelia/authelia:latest \
  authelia crypto hash generate argon2 --password 'your_chosen_password'
```
Expected output ตัวอย่าง:
```
Digest: $argon2id$v=19$m=65536,t=3,p=4$abc123...$/xyz456...
```
คัดลอก Digest ไว้ใช้ใน step ถัดไป

- [ ] **Step 3: Create `auth/authelia/users_database.yml`**

แทนที่ `<ARGON2_HASH>` ด้วย hash จาก step 2, `<YOUR_EMAIL>` ด้วย email จริง:
```yaml
users:
  admin:
    displayname: "Admin"
    password: "<ARGON2_HASH>"
    email: "<YOUR_EMAIL>"
    groups:
      - admins
      - users
```

ตัวอย่างไฟล์ที่สมบูรณ์:
```yaml
users:
  admin:
    displayname: "Admin"
    password: "$argon2id$v=19$m=65536,t=3,p=4$abc123def456$xyz789abc123def456xyz789"
    email: "admin@example.com"
    groups:
      - admins
      - users
```

- [ ] **Step 4: Commit**

```bash
git add auth/authelia/configuration.yml auth/authelia/users_database.yml
git commit -m "feat(auth): add Authelia configuration and users database"
```

---

## Task 3: Create `auth/README.md`

**Files:**
- Create: `auth/README.md`

- [ ] **Step 1: Create `auth/README.md`**

```markdown
# auth — Centralized SSO + Password Vault

Stack ประกอบด้วย 2 services:

| Service | Port | Purpose |
|---|---|---|
| Authelia | 9091 | SSO portal + forward-auth middleware |
| Vaultwarden | 8222 | Bitwarden-compatible password vault |

## First-Time Setup

```bash
cp .env.example .env
# เติม secrets ด้วย: openssl rand -hex 64
# แล้วสร้าง VAULTWARDEN_ADMIN_TOKEN ด้วย: openssl rand -base64 48
```

แก้ไข `authelia/configuration.yml` — แทนที่ `<NAS_HOST>` ทุก occurrence ด้วย hostname ของ NAS

สร้าง Argon2 hash สำหรับ admin password:
```bash
docker run --rm authelia/authelia:latest \
  authelia crypto hash generate argon2 --password 'your_password'
```

แก้ไข `authelia/users_database.yml` — ใส่ hash ใน `password:` field

## Deploy

```bash
docker compose up -d
```

ตรวจสอบ:
- Authelia portal: `http://<NAS_HOST>:9091`
- Vaultwarden: `http://<NAS_HOST>:8222`
- Vaultwarden admin: `http://<NAS_HOST>:8222/admin`

## Network

สร้าง Docker network `auth_net` (bridge) — stack อื่นที่ต้องการ forward-auth ต้อง join network นี้:

```yaml
networks:
  auth_net:
    external: true
    name: auth_net
```

## Watchtower

ทั้ง Authelia และ Vaultwarden ติด label `watchtower.enable=false` — อัปเดต manually เท่านั้น
เพื่อป้องกัน vault data หรือ auth config ขาดตอนระหว่าง auto-update
```

- [ ] **Step 2: Commit**

```bash
git add auth/README.md
git commit -m "docs(auth): add README with setup guide"
```

---

## Task 4: Deploy auth stack and verify

> **ทำบน NAS หลัง deploy.sh หรือทดสอบ local ก่อน**

- [ ] **Step 1: สร้าง `.env` จาก template และเติม secrets**

```bash
cd auth
cp .env.example .env
```

เปิด `.env` แล้วใส่ค่า (รัน 3 ครั้งสำหรับ 3 secrets):
```bash
openssl rand -hex 64   # ใช้ output เป็น AUTHELIA_SESSION_SECRET
openssl rand -hex 64   # ใช้ output เป็น AUTHELIA_STORAGE_ENCRYPTION_KEY
openssl rand -hex 64   # ใช้ output เป็น AUTHELIA_JWT_SECRET
openssl rand -base64 48  # ใช้ output เป็น VAULTWARDEN_ADMIN_TOKEN
```

- [ ] **Step 2: แก้ไข configuration.yml ให้ใส่ NAS_HOST จริง**

แทนที่ทุก `<NAS_HOST>` ใน `auth/authelia/configuration.yml`:
```bash
# ตรวจสอบว่า <NAS_HOST> หายไปหมดแล้ว
grep '<NAS_HOST>' auth/authelia/configuration.yml
```
Expected: ไม่มี output (ไม่มี placeholder เหลือ)

- [ ] **Step 3: แก้ไข users_database.yml ให้ใส่ hash จริง**

ตรวจสอบว่า hash ไม่ใช่ placeholder:
```bash
grep '<ARGON2_HASH>' auth/authelia/users_database.yml
```
Expected: ไม่มี output

- [ ] **Step 4: Deploy stack**

```bash
docker compose --project-directory auth/ -f auth/docker-compose.yml up -d
```

- [ ] **Step 5: ตรวจสอบ Authelia เริ่มต้นสำเร็จ**

```bash
docker logs authelia 2>&1 | grep -E "Listening|level=error|Starting"
```
Expected output มี:
```
Listening for TLS connections on tcp://0.0.0.0:9091
```
หรือ
```
Listening for non-TLS connections on tcp://0.0.0.0:9091
```

- [ ] **Step 6: ตรวจสอบ Authelia portal response**

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:9091
```
Expected: `200` หรือ `302`

- [ ] **Step 7: ตรวจสอบ Vaultwarden**

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8222
```
Expected: `200`

- [ ] **Step 8: ตรวจสอบ Docker network auth_net ถูกสร้าง**

```bash
docker network inspect auth_net | grep -E '"Name"|"Subnet"'
```
Expected: เห็น `auth_net` และ subnet

---

## Task 5: Migrate homepage — อัปเดต docker-compose.yml

**Files:**
- Modify: `homepage/docker-compose.yml`

- [ ] **Step 1: แทนที่ `homepage/docker-compose.yml` ทั้งไฟล์**

```yaml
version: '3.8'

services:
  homepage:
    image: ghcr.io/gethomepage/homepage:latest
    container_name: homepage
    restart: always
    expose:
      - "3000"
    volumes:
      - ./config:/app/config
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ${NAS_VOLUME_ROOT}:${NAS_VOLUME_ROOT}:ro
    env_file: .env
    environment:
      - TZ=Asia/Bangkok
      - HOMEPAGE_VAR_VOLUME_ROOT=${NAS_VOLUME_ROOT}
    networks:
      - default

  nginx:
    image: nginx:alpine
    container_name: homepage-nginx
    restart: always
    ports:
      - "3000:80"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/conf.d/default.conf:ro
    environment:
      - TZ=Asia/Bangkok
    depends_on:
      - homepage
    networks:
      - default
      - auth_net

networks:
  default:
    driver: bridge
  auth_net:
    external: true
    name: auth_net
```

การเปลี่ยนจากเดิม:
- ลบ `command:` block (htpasswd) ออกจาก nginx
- ลบ `env_file: .env` จาก nginx (ไม่ต้องการ NGINX_BASIC_AUTH_* อีกต่อไป)
- เพิ่ม `networks:` ทั้ง homepage (default) และ nginx (default + auth_net)
- เพิ่ม `networks:` section ที่ bottom

- [ ] **Step 2: Validate compose syntax**

```bash
docker compose --project-directory homepage/ -f homepage/docker-compose.yml config
```
Expected: YAML output ไม่มี error. ตรวจว่า nginx มี 2 networks

- [ ] **Step 3: อัปเดต `homepage/.env.example` — ลบ basic auth vars**

เปิด `homepage/.env.example` แล้วลบ 2 บรรทัดนี้:
```
NGINX_BASIC_AUTH_USER=
NGINX_BASIC_AUTH_PASS=
```
และลบ comment header ของ section นั้น

- [ ] **Step 4: Commit**

```bash
git add homepage/docker-compose.yml homepage/.env.example
git commit -m "feat(homepage): migrate nginx from basic auth to Authelia forward-auth network setup"
```

---

## Task 6: Migrate homepage — อัปเดต nginx.conf

**Files:**
- Modify: `homepage/nginx/nginx.conf`

- [ ] **Step 1: แทนที่ `homepage/nginx/nginx.conf` ทั้งไฟล์**

แทนที่ `<NAS_HOST>` ด้วย hostname NAS จริง (เช่น `192.168.1.x` หรือ DDNS hostname):

```nginx
server {
    listen 80;

    location /authelia {
        internal;
        proxy_pass          http://authelia:9091/api/authz/forward-auth;
        proxy_set_header    X-Forwarded-Method  $request_method;
        proxy_set_header    X-Forwarded-Proto   $scheme;
        proxy_set_header    X-Forwarded-Host    $host;
        proxy_set_header    X-Forwarded-URI     $request_uri;
        proxy_set_header    Content-Length      "";
        proxy_pass_request_body off;
    }

    location / {
        auth_request        /authelia;
        auth_request_set    $target_url $scheme://$http_host$request_uri;
        error_page 401      =302 http://<NAS_HOST>:9091/?rd=$target_url;

        auth_request_set    $user   $upstream_http_remote_user;
        auth_request_set    $groups $upstream_http_remote_groups;
        proxy_set_header    Remote-User     $user;
        proxy_set_header    Remote-Groups   $groups;

        proxy_pass          http://homepage:3000;
        proxy_http_version  1.1;
        proxy_set_header    Host              $http_host;
        proxy_set_header    X-Real-IP         $remote_addr;
        proxy_set_header    X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header    X-Forwarded-Proto $scheme;
        proxy_buffering     off;
    }
}
```

- [ ] **Step 2: Redeploy homepage stack**

```bash
docker compose --project-directory homepage/ -f homepage/docker-compose.yml up -d
```

- [ ] **Step 3: ตรวจสอบ nginx container join auth_net**

```bash
docker inspect homepage-nginx | grep -A5 '"auth_net"'
```
Expected: เห็น `"auth_net"` ใน Networks section

- [ ] **Step 4: ทดสอบ unauthenticated request → redirect ไป Authelia**

```bash
curl -sI http://localhost:3000 | grep -i location
```
Expected: เห็น `Location: http://<NAS_HOST>:9091/?rd=http://...`

ถ้า location ไม่มี — ดู nginx logs:
```bash
docker logs homepage-nginx 2>&1 | tail -20
```

- [ ] **Step 5: Commit**

```bash
git add homepage/nginx/nginx.conf
git commit -m "feat(homepage): replace basic auth with Authelia forward-auth in nginx"
```

---

## Task 7: Migrate maid-tracker — เพิ่ม nginx sidecar

**Files:**
- Modify: `maid-tracker/docker-compose.yml`
- Create: `maid-tracker/nginx/nginx.conf`

- [ ] **Step 1: สร้าง `maid-tracker/nginx/nginx.conf`**

แทนที่ `<NAS_HOST>` ด้วย hostname เดียวกับ homepage:

```nginx
server {
    listen 80;

    location /authelia {
        internal;
        proxy_pass          http://authelia:9091/api/authz/forward-auth;
        proxy_set_header    X-Forwarded-Method  $request_method;
        proxy_set_header    X-Forwarded-Proto   $scheme;
        proxy_set_header    X-Forwarded-Host    $host;
        proxy_set_header    X-Forwarded-URI     $request_uri;
        proxy_set_header    Content-Length      "";
        proxy_pass_request_body off;
    }

    location / {
        auth_request        /authelia;
        auth_request_set    $target_url $scheme://$http_host$request_uri;
        error_page 401      =302 http://<NAS_HOST>:9091/?rd=$target_url;

        auth_request_set    $user   $upstream_http_remote_user;
        auth_request_set    $groups $upstream_http_remote_groups;
        proxy_set_header    Remote-User     $user;
        proxy_set_header    Remote-Groups   $groups;

        proxy_pass          http://maid-tracker:8000;
        proxy_http_version  1.1;
        proxy_set_header    Host              $http_host;
        proxy_set_header    X-Real-IP         $remote_addr;
        proxy_set_header    X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header    X-Forwarded-Proto $scheme;
        proxy_buffering     off;
    }
}
```

- [ ] **Step 2: แทนที่ `maid-tracker/docker-compose.yml` ทั้งไฟล์**

```yaml
services:
  maid-tracker:
    build: .
    container_name: maid-tracker
    restart: unless-stopped
    expose:
      - "8000"
    volumes:
      - maid_tracker_data:/data
    env_file: .env
    environment:
      - TZ=Asia/Bangkok
      - DATA_DIR=/data
    networks:
      - default

  maid-nginx:
    image: nginx:alpine
    container_name: maid-tracker-nginx
    restart: unless-stopped
    ports:
      - "5055:80"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/conf.d/default.conf:ro
    environment:
      - TZ=Asia/Bangkok
    depends_on:
      - maid-tracker
    networks:
      - default
      - auth_net

volumes:
  maid_tracker_data:

networks:
  default:
    driver: bridge
  auth_net:
    external: true
    name: auth_net
```

การเปลี่ยนจากเดิม:
- `maid-tracker.ports: "5055:8000"` → `expose: "8000"` (ไม่เปิด port ออก host โดยตรง)
- เพิ่ม `maid-nginx` service
- เพิ่ม `networks:` section

- [ ] **Step 3: Validate compose syntax**

```bash
docker compose --project-directory maid-tracker/ -f maid-tracker/docker-compose.yml config
```
Expected: YAML ไม่มี error, เห็น `maid-tracker` (expose 8000) และ `maid-nginx` (ports 5055:80)

- [ ] **Step 4: Redeploy maid-tracker stack**

```bash
docker compose --project-directory maid-tracker/ -f maid-tracker/docker-compose.yml up -d --build
```

- [ ] **Step 5: ตรวจสอบ nginx container join auth_net**

```bash
docker inspect maid-tracker-nginx | grep -A5 '"auth_net"'
```
Expected: เห็น `"auth_net"` ใน Networks section

- [ ] **Step 6: ทดสอบ unauthenticated request → redirect**

```bash
curl -sI http://localhost:5055 | grep -i location
```
Expected: `Location: http://<NAS_HOST>:9091/?rd=http://...`

- [ ] **Step 7: Commit**

```bash
git add maid-tracker/docker-compose.yml maid-tracker/nginx/nginx.conf
git commit -m "feat(maid-tracker): add nginx sidecar with Authelia forward-auth"
```

---

## Task 8: อัปเดต documentation และ final commit

**Files:**
- Modify: `CLAUDE.md` — เพิ่ม auth/ ใน stacks table
- Modify: `README.md` — เพิ่ม auth/ ใน stacks table

- [ ] **Step 1: เพิ่ม auth/ ใน `CLAUDE.md` stacks table**

เปิด `CLAUDE.md` และเพิ่ม row นี้ใน Stacks & Ports Directory table (เรียงตาม port):

```markdown
| `auth/` | Centralized SSO + Password Vault | 9091 (Authelia) / 8222 (Vaultwarden) | สร้าง Docker network `auth_net` ที่ stack อื่น join. Authelia ทำ forward-auth แทน basic auth. Vaultwarden มี auth ของตัวเอง. Watchtower disabled บนทั้งสอง service |
```

- [ ] **Step 2: เพิ่ม auth/ ใน `README.md` stacks table**

เปิด `README.md` section `## Stacks` และเพิ่ม row:
```markdown
| `auth/` | Centralized SSO (Authelia) + Password Vault (Vaultwarden) | `9091` (Authelia) / `8222` (Vaultwarden) | — |
```

และใน `.env` section เพิ่ม:
```
auth/.env                 # AUTHELIA_SESSION_SECRET, AUTHELIA_STORAGE_ENCRYPTION_KEY, AUTHELIA_JWT_SECRET, VAULTWARDEN_ADMIN_TOKEN
```

- [ ] **Step 3: Commit docs**

```bash
git add CLAUDE.md README.md
git commit -m "docs: add auth stack to stacks tables (ports 9091, 8222)"
```

---

## Task 9: End-to-end verification

- [ ] **Step 1: ตรวจสอบ services ทั้งหมดรันอยู่**

```bash
docker ps --filter name=authelia --filter name=vaultwarden --filter name=homepage-nginx --filter name=maid-tracker-nginx --format "table {{.Names}}\t{{.Status}}"
```
Expected: ทั้ง 4 containers อยู่ในสถานะ `Up`

- [ ] **Step 2: ทดสอบ homepage ต้อง login ผ่าน Authelia**

```bash
curl -sI http://localhost:3000 | grep -E "HTTP|Location"
```
Expected:
```
HTTP/1.1 302 Found
Location: http://<NAS_HOST>:9091/?rd=http://...
```

- [ ] **Step 3: ทดสอบ maid-tracker ต้อง login ผ่าน Authelia**

```bash
curl -sI http://localhost:5055 | grep -E "HTTP|Location"
```
Expected: `302 Found` พร้อม Location ไป Authelia

- [ ] **Step 4: ทดสอบ Vaultwarden accessible โดยไม่ผ่าน Authelia**

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8222
```
Expected: `200`

- [ ] **Step 5: ทดสอบ login จริงผ่าน browser**

เปิด `http://<NAS_HOST>:3000` ใน browser:
1. ต้อง redirect ไปหน้า login ของ Authelia ที่ port 9091
2. login ด้วย username `admin` และ password ที่ใช้สร้าง hash
3. ต้อง redirect กลับมาที่ homepage และเห็น dashboard

- [ ] **Step 6: ทดสอบ session sharing**

หลัง login homepage แล้ว เปิด `http://<NAS_HOST>:5055` ใน tab เดียวกัน:
Expected: เข้า maid-tracker ได้ทันทีโดยไม่ต้อง login ซ้ำ (session cookie ใช้ร่วมกันได้เพราะ domain เดียวกัน)

- [ ] **Step 7: บันทึก daily log**

เพิ่มรายการใน `auth/.notes/daily_log.md` (สร้าง directory ถ้ายังไม่มี):
```markdown
## YYYY-MM-DD — Auth Stack Setup

- สร้าง auth/ stack: Authelia (9091) + Vaultwarden (8222)
- migrate homepage nginx: basic auth → Authelia forward-auth
- migrate maid-tracker: เพิ่ม nginx sidecar + Authelia forward-auth
- สร้าง auth_net Docker network (shared bridge)
- deploy บน NAS, ทดสอบ login และ session sharing ผ่าน
```
