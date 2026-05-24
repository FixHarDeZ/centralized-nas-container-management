# line-secretary — Stack Index

> Memory index สำหรับ Claude Code — อ่านก่อนเริ่มงานใดๆ ใน stack นี้

---

## Overview

LINE bot เลขาส่วนตัว AI ค้นหาและบันทึกข้อมูลใน Notion workspace
รันเป็น Docker container บน Synology NAS (Python 3.12 + FastAPI)

---

## Ports

| Endpoint | Value |
|---|---|
| Host port | `5057` |
| Container port | `8000` |
| Synology RP (HTTPS) | `5058` → `http://localhost:5057` |
| LINE Webhook URL | `https://<NAS_HOST>:5058/webhook` |

---

## Tech Stack

| Layer | Detail |
|---|---|
| Runtime | Python 3.12 · FastAPI · Uvicorn |
| AI (primary) | Groq `llama-3.3-70b-versatile` (free, 100K tokens/day) |
| AI (fallback) | OpenRouter (pay-per-use) — auto-switch on rate-limit |
| AI mode | `AI_PROVIDER=auto` (แนะนำ) / `groq` / `openrouter` |
| Knowledge base | Notion API (Internal Integration Token) |
| Messaging | LINE Messaging API |
| State storage | `/data/state.json` via `store.py` (volume `line_secretary_data`) |
| Page cache | In-memory, warm at startup, refresh ทุก 10 นาที |

---

## Source Files

| File | หน้าที่ |
|---|---|
| `main.py` | FastAPI app, routes: `GET /health`, `POST /webhook` |
| `agent.py` | Core logic — search, rank, write, LLM call |
| `cache.py` | In-memory Notion page header cache |
| `config.py` | อ่าน env vars, ตั้งค่า global config |
| `provider.py` | Groq ↔ OpenRouter failover logic |
| `notion.py` | Notion API calls (search, read page, query DB) |
| `line_client.py` | LINE push message |
| `store.py` | Persist state (pending, history) ลง `/data/state.json` |
| `docker-compose.yml` | Stack definition, volume mount |
| `Dockerfile` | Build image จาก `python:3.12-slim` |

---

## Application Logic

### Request Flow

```
LINE message → POST /webhook
    → whitelist check (LINE_SECRETARY_ALLOWED_USER_IDS)
    → check store: has_pending? → confirmation flow
    → agent.run() 
        → cache lookup + Notion search (parallel)
        → recursive read: pages, tables, toggles (2 levels)
        → relevance ranking (_rank_context)
        → LLM call (Groq / OpenRouter)
        → if no Notion data → ask general knowledge confirm
        → if write intent → propose → wait "ใช่"
    → LINE push reply
```

### State Machine (per user)

| State | ความหมาย |
|---|---|
| `pending` | รอผู้ใช้ยืนยัน write ลง Notion (`store.get_pending`) |
| `pending_general` | รอผู้ใช้ยืนยันตอบจากความรู้ทั่วไป |
| `history` | บันทึก 4 exchange ล่าสุดต่อ user สำหรับ LLM context |

### Agent Tools (ใน agent.py)

- `_search_variants` — สร้าง query variants จาก user message
- `_fallback_scan` — header-based keyword scan จาก cache
- `_rank_context` — จัดลำดับ Notion pages ตาม keyword relevance
- `_deep_search` — full page + DB search
- `_write_one` / `execute_write` — write ลง Notion หลัง confirm

---

## Environment Variables (root `.env`)

```env
LINE_SECRETARY_CHANNEL_SECRET=...
LINE_SECRETARY_CHANNEL_ACCESS_TOKEN=...
LINE_SECRETARY_ALLOWED_USER_IDS=Uxxxxxxxxxxxxxxxx   # comma-separated

AI_PROVIDER=auto          # auto / groq / openrouter
GROQ_API_KEY=gsk_...
OPENROUTER_API_KEY=sk-or-v1-...

NOTION_TOKEN=ntn_...
NOTION_QUICK_NOTE_PAGE_ID=...          # parent page สำหรับ quick note (optional)

# Proactive reminders (optional — leave blank to disable)
NOTION_REMINDER_DB_IDS=db-id-1,db-id-2   # comma-sep database IDs ที่มี date property
NOTION_REMINDER_TIME=08:00               # Bangkok time HH:MM (default 08:00)
```

---

## Debug Commands (ส่งใน LINE chat)

| Command | ทำอะไร |
|---|---|
| `/debug <query>` | Raw Notion search results |
| `/debug2 <query>` | Deep search (pages + DBs) |
| `/debug3 <page_id>` | Raw block children ของ page |
| `/debug4 <db_id>` | Raw database query response |
| `/provider` | Provider ที่ใช้อยู่ + เวลา Groq resume |
| `/cache` | Cache stats: จำนวน page + เวลา rebuild ล่าสุด |

---

## Key Behaviours / Gotchas

- **Whitelist-only** — user IDs นอก whitelist ถูก silent ignore; non-text messages (image/sticker) ตอบ "รับแค่ข้อความ"
- **Write confirmation** — ทุก write ต้องรอ "ใช่" ก่อน execute; pending หมดอายุ 6 ชั่วโมงอัตโนมัติ
- **Notion sharing** — integration ต้อง share ที่ root page จึงจะเห็น subpages
- **Cache warm-up** — API call แรกหลัง restart อาจช้ากว่าปกติ (cache ยัง cold)
- **Groq daily limit** — 100K tokens/day สำหรับ 70b model; auto mode จะ failover เอง
- **Toggle content** — Notion search API ไม่ index toggle blocks, ใช้ fallback scan จาก cache แทน
- **Quick note** — ถ้าชื่อ page ตรงกับ page เดิม (case-insensitive) จะ append แทนสร้างใหม่; รองรับ Markdown: `# ## ###` heading, `- *` bullet, `[ ] [x]` to-do
- **Agent timeout** — LLM call มี hard timeout 45 วินาที ทั้ง attempt แรกและ retry
- **Proactive reminders** — background loop เช็ค Notion DB ที่ตั้งไว้ทุกวันตอนเวลาที่กำหนด (Bangkok) แล้ว push LINE ถ้าพบ row ที่ date = วันนี้

---

## Deploy

```bash
scripts/deploy.sh   # อัปโหลด + restart line-secretary บน NAS
```

NAS path: `/volume1/docker/line-secretary`
