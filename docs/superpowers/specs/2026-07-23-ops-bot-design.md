# ops-bot — AI-Powered Incident Response Bot

**Date:** 2026-07-23
**Status:** Approved
**Stack:** `ops-bot/` (new)

---

## Overview

Autonomous AI ops bot ที่รับ alert จาก Uptime Kuma, SSH เข้า NAS รัน diagnostics อัตโนมัติ, ใช้ LLM (mimo-v2.5-pro) วิเคราะห์ root cause, แจ้ง Telegram ภาษาไทย, และ execute fix เมื่อ user ยืนยัน

---

## Architecture

```
Uptime Kuma (port 3001)
    │
    ▼ webhook POST /webhook/uptime-kuma
┌─────────────────────────────────────────┐
│           ops-bot (FastAPI)             │
│                                         │
│  ┌──────────┐  ┌───────────────────┐   │
│  │ Webhook  │  │ Telegram Commands │   │
│  │ Handler  │  │ /status /diagnose │   │
│  │          │  │ /logs             │   │
│  └────┬─────┘  └────────┬──────────┘   │
│       │                 │               │
│       └────────┬────────┘               │
│                ▼                         │
│  ┌─────────────────────────────────┐   │
│  │        Orchestrator             │   │
│  └───┬──────┬──────┬──────┬───────┘   │
│      │      │      │      │            │
│  ┌───▼──┐┌──▼───┐┌─▼──┐┌─▼────────┐  │
│  │ SSH  ││ LLM  ││ TG ││ SQLite   │  │
│  │Client││(mimo)││Bot ││ (history)│  │
│  └──────┘└──────┘└────┘└──────────┘  │
│                                         │
│  ┌─────────────────────────────────┐   │
│  │     Web Dashboard (HTML)        │   │
│  │     /dashboard                  │   │
│  └─────────────────────────────────┘   │
└─────────────────────────────────────────┘
    │ SSH                │ Telegram API
    ▼                    ▼
  NAS Host           Telegram User
(docker, system)    (fix confirmation)
```

---

## Components

### 1. Webhook Handler (`webhook.py`)

- Endpoint: `POST /webhook/uptime-kuma`
- รับ JSON payload จาก Uptime Kuma
- Parse: service name, status, error message, timestamp
- Trigger: Orchestrator pipeline

### 2. Telegram Bot (`telegram_bot.py`)

**Commands:**
- `/status` — แสดงสถานะ container ทั้งหมด (ตาราง: ชื่อ, status, uptime, restart count, mem usage)
- `/diagnose <service>` — manual trigger diagnostics สำหรับ service ที่เลือก
- `/logs <service> [lines]` — ดู logs ล่าสุด (default 50, สูงสุด 200)

**InlineKeyboard:**
- `[🔧 Fix]` — execute suggested fix
- `[🔄 Restart]` — restart container
- `[📋 Compose Logs]` — ดู compose logs

### 3. SSH Client (`ssh_client.py`)

- Paramiko SSH library
- Connect to NAS host with SSH key (key เก็บใน Docker volume `/app/data/ssh/`, mount จาก host `~/.ssh/id_ed25519`)
- Fallback: SSH password จาก vault (ถ้าไม่มี key)
- Execute commands with timeout (default 30s)
- Command whitelist:
  - `docker ps`, `docker logs`, `docker inspect`, `docker restart`
  - `docker compose logs`, `docker compose restart`
  - `df`, `free`, `uptime`, `cat /proc/loadavg`
  - `curl` (health check)
  - `docker network inspect`, `docker port`

### 4. LLM Client (`llm_client.py`)

- mimo-v2.5-pro via Xiaomi subscription
- Base URL: `https://token-plan-sgp.xiaomimimo.com/v1`
- OpenAI-compatible API
- Thai language output
- Structured response: `root_cause`, `severity`, `suggested_fix`, `fix_commands`

### 5. Diagnostics (`diagnostics.py`)

**Step 1: Watchtower Grace Period**
- SSH รัน: `docker logs watchtower --since 5m 2>&1 | grep <container_name>`
- ถ้าพบ "Updated" log สำหรับ container นี้ภายใน 5 นาที → skip alert, log to SQLite (is_watchtower_update=TRUE)
- ถ้าไม่พบ → ดำเนินการต่อ

**Step 2: Container Status**
```
docker ps -a --filter "name=<container>"
docker inspect <container>
docker logs --tail 100 <container>
```

**Step 3: System Resources**
```
df -h && free -m && uptime && cat /proc/loadavg
```

**Step 4: Container Config**
```
docker inspect <container> --format '{{.HostConfig.Memory}}'
docker inspect <container> --format '{{.HostConfig.CpuQuota}}'
```

**Step 5: Service Health Check**
```
curl -s -o /dev/null -w "%{http_code}" http://localhost:<port>/health
```

**Step 6: Network Diagnostics**
```
docker network inspect <network>
docker port <container>
```

**Step 7: Compose Logs**
```
# หา compose file path จาก container label
docker inspect <container> --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}'
docker inspect <container> --format '{{index .Config.Labels "com.docker.compose.project.config_files"}}'

# แล้วรัน
docker compose -f <compose_file> logs --tail 100 <service>
```

### 6. Web Dashboard (`dashboard.py`)

- Route: `/dashboard`
- Features:
  - Incident history table (filter by service, severity, date)
  - Diagnostic details per incident
  - Action history
  - Real-time status overview

---

## Data Model (SQLite)

```sql
CREATE TABLE incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kuma_event_id TEXT,
    service_name TEXT NOT NULL,
    container_name TEXT,
    status TEXT NOT NULL,
    alert_message TEXT,
    is_watchtower_update BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE diagnostics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id INTEGER REFERENCES incidents(id),
    step_name TEXT NOT NULL,
    raw_output TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id INTEGER REFERENCES incidents(id),
    root_cause TEXT,
    severity TEXT,
    suggested_fix TEXT,
    fix_commands TEXT,
    llm_tokens_used INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id INTEGER REFERENCES incidents(id),
    action_type TEXT NOT NULL,
    commands_executed TEXT,
    result_output TEXT,
    success BOOLEAN,
    executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## Telegram UX Flow

```
[Alert arrives]
    │
    ▼
🤖 **แจ้งเตือน: Outline Wiki ล่ม!**
📅 2026-07-22 07:40:51
🔴 Status: DOWN
📡 Error: connect ECONNREFUSED 192.168.1.111:3000

⏳ กำลังวิเคราะห์อัตโนมัติ...
    │
    ▼ (SSH diagnostics + LLM analysis)
    │
🤖 **ผลการวินิจฉัย — Outline Wiki**

| ข้อมูล | ค่า |
|--------|-----|
| Container | outliner-outline-1 |
| Exit Code | 137 (SIGKILL) |
| OOMKilled | ✅ |
| mem_limit | 3g |
| RAM available | ~12.9 GB |
| Restart loop | ตั้งแต่ 07:40 |

🔍 **Root Cause:** OOM Kill — container ใช้ RAM เกิน 3GB limit
⚡ **Severity:** Critical

💡 **แนะนำ:** เพิ่ม mem_limit จาก 3g → 5g

[🔧 Fix: เพิ่ม mem_limit] [🔄 Restart Container] [📋 Compose Logs]
    │
    ▼ (user กด 🔧 Fix)
    │
🤖 กำลังแก้ไข...
✅ เปลี่ยน mem_limit: 3g → 5g
✅ Restart container สำเร็จ
📊 สถานะ: กลับมาทำงานปกติแล้ว
```

---

## Configuration

### Secrets (via vault)

```yaml
# secrets.manifest.yaml
env:
  MIMO_API_KEY:              stacks.ops_bot.mimo_api_key
  MIMO_BASE_URL:             stacks.ops_bot.mimo_base_url
  TELEGRAM_BOT_TOKEN:        stacks.ops_bot.telegram.bot_token
  TELEGRAM_CHAT_ID:          stacks.ops_bot.telegram.chat_id
  NAS_SSH_HOST:              stacks.ops_bot.ssh.host
  NAS_SSH_USER:              stacks.ops_bot.ssh.user
  # SSH key (primary) — mount จาก host ~/.ssh/id_ed25519
  # SSH password (fallback) — จาก vault ถ้าไม่มี key
  NAS_SSH_PASSWORD:          stacks.ops_bot.ssh.password
```

### Docker Compose

```yaml
services:
  ops-bot:
    build: .
    container_name: ops-bot
    restart: unless-stopped
    env_file: .env
    environment:
      - TZ=Asia/Bangkok
    ports:
      - "5070:8000"
    volumes:
      - ops_bot_data:/app/data
    labels:
      - "com.centurylinklabs.watchtower.enable=false"
```

### LLM Config

```python
MIMO_BASE_URL = "https://token-plan-sgp.xiaomimimo.com/v1"
MIMO_MODEL = "mimo-v2.5-pro"
```

---

## Security

1. **SSH Access** — SSH key (ไม่ใช่ password), เก็บใน Docker volume
2. **Telegram Whitelist** — `TELEGRAM_CHAT_ID` จำกัดผู้สั่ง
3. **Command Whitelist** — allowed commands เท่านั้น
4. **Watchtower Label** — `enable=false` ป้องกัน auto-update
5. **Webhook Secret** — Uptime Kuma webhook secret header

---

## Port Allocation

| Port | Service |
|------|---------|
| 5070 | ops-bot (webhook + dashboard) |

---

## Integration Points

### Uptime Kuma

- Notification type: Webhook
- URL: `http://<NAS_IP>:5070/webhook/uptime-kuma`
- Method: POST
- Body: Kuma JSON format

### Watchtower

- Grace period: 5 minutes after image update
- Check: watchtower logs for recent container updates

### Telegram

- Bot API (direct, not through Hermes)
- InlineKeyboard for fix confirmation
- Commands: `/status`, `/diagnose`, `/logs`

---

## Stack Structure

```
ops-bot/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── ssh_client.py
│   ├── llm_client.py
│   ├── telegram_bot.py
│   ├── diagnostics.py
│   ├── watchtower.py
│   ├── db.py
│   ├── webhook.py
│   ├── commands.py
│   ├── dashboard.py
│   └── templates/
│       └── dashboard.html
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── secrets.manifest.yaml
└── README.md
```

---

## Implementation Order

1. **Phase 1: Core** — FastAPI + webhook + SSH + basic diagnostics + Telegram notification
2. **Phase 2: LLM** — mimo integration + root cause analysis + fix suggestions
3. **Phase 3: Telegram UX** — InlineKeyboard + fix execution + commands (/status, /diagnose, /logs)
4. **Phase 4: Dashboard** — Web UI for incident history
5. **Phase 5: Watchtower** — Grace period logic
6. **Phase 6: Polish** — Error handling, logging, README
