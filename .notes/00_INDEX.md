# Project Root — Index

## Overview
Root-level notes สำหรับ cross-stack changes และ project-wide decisions

---

## โครงสร้าง .env (อัปเดต 2026-05-23)

**Per-stack .env** — secrets แยกตาม stack ตั้งแต่ 2026-05-23:

| ไฟล์ | ใช้งาน |
|---|---|
| `.env` (root) | deploy.sh (`NAS_*`) + scripts/sync_notion.py (`NOTION_*`) เท่านั้น — containers ไม่เห็น |
| `auth/.env` | `AUTHELIA_SESSION_SECRET`, `AUTHELIA_STORAGE_ENCRYPTION_KEY`, `AUTHELIA_JWT_SECRET`, `VAULTWARDEN_ADMIN_TOKEN` |
| `homepage/.env` | `HOMEPAGE_VAR_*`, `NAS_VOLUME_ROOT` (ลบ `NGINX_BASIC_AUTH_*` แล้ว — ใช้ Authelia แทน) |
| `jellyfin/.env` | `NAS_VOLUME_ROOT`, `NAS_MEDIA_ROOT` |
| `my-secretary/.env` | `LINE_SECRETARY_*`, `NOTION_TOKEN`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_CHAT_IDS` |
| `hermes-agent/.env`   | `OPENROUTER_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USERS`, `DISCORD_BOT_TOKEN`, `DISCORD_ALLOWED_GUILDS`, `HERMES_UID`, `HERMES_GID` |
| `maid-tracker/.env` | `MAID_LINE_*`, `MONTHLY_REPORT_TIME` (ลบ `NGINX_BASIC_AUTH_*` แล้ว — ใช้ Authelia แทน) |
| `torrentwatch/.env` | `TORRENTWATCH_*`, `NGINX_BASIC_AUTH_*`, `NAS_TORRENT_PATH` |
| `news-feed/.env` | `ANTHROPIC_API_KEY`, `LINE_CHANNEL_ACCESS_TOKEN`, `LINE_USER_ID`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `ADMIN_TOKEN`, `SUMMARIZER_PROVIDER`, `SUMMARIZER_MODEL`, `OPENROUTER_API_KEY`, `DIGEST_TIMES`, `ENABLED_SOURCES`, `DATA_DIR` |
| `uptime-kuma/.env` | `NAS_VOLUME_ROOT` |
| `watchtower/.env` | `WATCHTOWER_LINE_*`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| `portainer/` | ไม่มี .env |

ทุก `.env` gitignored — `.env.example` ทุก stack commit ได้

**deploy.sh restart ใช้ `--project-directory <stack>/`** เพื่อให้ compose หา `<stack>/.env` เจอเอง

---

## DSM Auto-Block Gotcha (2026-05-23)

Homepage widgets ที่ยิง DSM API จะถูก auto-block IP ถ้า login fail ซ้ำ → error 407 แสดงเป็น "2FA enabled" ใน log

**Fix ถาวร:** DSM → Security → Protection → Allow List ใส่:
- `10.0.0.0 / 255.0.0.0`
- `172.16.0.0 / 255.240.0.0`
- `192.168.0.0 / 255.255.0.0`

---

## Change Log

| วันที่ | เรื่อง |
|---|---|
| 2026-05-22 | เพิ่ม NAS_VOLUME_ROOT / NAS_MEDIA_ROOT — replace hardcoded /volume1 ทั้ง project |
| 2026-05-23 | Refactor per-stack .env, fix homepage DSM auto-block, fix watchtower notifier 429 |
| 2026-05-23 | เพิ่ม Telegram bot: my-secretary webhook + watchtower notification. Router port 8443 → NAS |
| 2026-05-23 | เพิ่ม hermes-agent stack (Telegram + Discord, port 5063). ย้าย Telegram ออกจาก my-secretary |
| 2026-05-23 | สร้าง auth/ stack (Authelia SSO port 9091 + Vaultwarden port 8222). Migrate homepage + maid-tracker จาก basic auth → Authelia forward-auth |
| 2026-05-23 | สร้าง news-feed/ stack (FastAPI + APScheduler + SQLite, port 5064). RSS 7 แหล่ง, สรุปภาษาไทย Anthropic/OpenRouter switchable, digest → LINE + Telegram |
