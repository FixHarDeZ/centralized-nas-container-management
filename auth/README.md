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
