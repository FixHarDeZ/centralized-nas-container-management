# my-secretary

**EN** | [ไทย](#ภาษาไทย)

A personal AI secretary bot that searches and records information in your Notion workspace. Runs as a Docker container on Synology NAS. Supports both **LINE** and **Telegram** — state is isolated per platform.

---

## Features

- Ask anything in natural language (Thai or English) — the bot searches your Notion and answers
- Reads pages, simple tables, toggle sections, and embedded databases automatically
- Always runs both Notion search and header-based fallback scan in parallel — finds content even in toggle blocks that Notion's search doesn't index; both plain text paragraphs and table cell inside toggles are included in the keyword index
- Page headers cached in memory at startup and refreshed every 10 minutes — ~90% fewer Notion API calls per message once warm
- Relevance-ranked context — most keyword-matching pages are packed into the LLM prompt first
- Automatic Groq→OpenRouter failover — when both keys are set (`AI_PROVIDER=auto`), Groq is used first (free); on rate-limit it switches to OpenRouter automatically and switches back once Groq resets
- Answers only from your Notion data — never hallucinates from general knowledge; if the answer isn't in Notion, asks whether to answer from general knowledge instead
- Proposes a confirmation before writing any new record to Notion; pending confirmations auto-expire after 6 hours
- Quick note with rich Markdown-like formatting — `# heading`, `- bullet`, `[ ] todo`, `[x] done`; if you name an existing page the bot appends to it instead of creating a new one
- Send an image while in a note flow (LINE only) and it is uploaded directly to the Notion page via Notion's File Upload API
- Includes 🔗 Notion page URLs in replies — so you can click directly to the source
- Whitelist-based access — only your LINE user IDs / Telegram chat IDs can use the bot

## How it works

```
LINE:      POST /webhook           → verify X-Line-Signature         → handle_message("U{id}", text, line_push_fn)
Telegram:  POST /webhook/telegram  → verify X-Telegram-Bot-Api-Secret-Token → handle_message("tg_{chat_id}", text, tg_push_fn)
```

Both platforms share the same `handle_message()` core logic. State (history, pending confirmations) is keyed by `U{LINE_user_id}` for LINE and `tg_{chat_id}` for Telegram — no cross-platform sharing.

## Stack

| Component | Detail |
|---|---|
| Runtime | Python 3.12 · FastAPI · Uvicorn |
| AI | Groq `llama-3.3-70b-versatile` (primary, free) → OpenRouter fallback (auto mode) |
| Knowledge base | Notion API (Internal Integration Token) |
| Messaging | LINE Messaging API · Telegram Bot API |
| Host port | `5057` → container `8000` |
| Reverse proxy | Synology RP `https://…:15057` → `http://localhost:5057` |

## Setup

### 1. AI Provider

**Recommended: set both keys and use `AI_PROVIDER=auto`**

In auto mode the bot uses Groq (free) as the primary provider. When Groq's daily limit is hit, it switches to OpenRouter automatically and switches back once Groq resets — no restart needed.

**Groq (free, primary)**
- Sign up at [console.groq.com](https://console.groq.com) and create an API key
- Free tier: 100K tokens/day for the 70b model

**OpenRouter (pay-per-use, fallback)**
- Get a key at [openrouter.ai](https://openrouter.ai) — supports Claude, GPT, Llama, and more

### 2. Notion Integration Token

1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations) → **New integration**
2. Copy the **Internal Integration Token**
3. In Notion, open the root page you want the bot to access → **Share** → invite the integration
   > Sharing a parent page (e.g. Personal Home) gives access to all its subpages at once

### 3. LINE Setup

1. Go to [developers.line.biz](https://developers.line.biz) → Create a **Messaging API** channel
2. Copy **Channel Secret** and **Channel Access Token**
3. Set webhook URL: `https://<NAS_HOST>:15057/webhook`
4. Enable **Use webhooks**, disable **Auto-reply messages**
5. Find your LINE user ID in Developers Console → Messaging API → Your user ID

### 4. Telegram Setup

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token to `TELEGRAM_BOT_TOKEN`
2. Set `TELEGRAM_WEBHOOK_URL` to your NAS HTTPS endpoint (Synology Reverse Proxy → port 8443):
   ```
   https://<NAS_HOST>:8443/webhook/telegram
   ```
3. Set `TELEGRAM_WEBHOOK_SECRET` to any random string (used to validate Telegram's requests)
4. Set `TELEGRAM_ALLOWED_CHAT_IDS` to your numeric Telegram chat ID (find it via [@userinfobot](https://t.me/userinfobot))
5. Deploy and restart — the bot registers its webhook automatically on startup

> **Note:** LINE and Telegram maintain separate conversation histories. Chatting on LINE does not share context with Telegram.

### 5. Environment variables

```env
LINE_SECRETARY_CHANNEL_SECRET=...
LINE_SECRETARY_CHANNEL_ACCESS_TOKEN=...
LINE_SECRETARY_ALLOWED_USER_IDS=Uxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

TELEGRAM_BOT_TOKEN=...
TELEGRAM_WEBHOOK_URL=https://<NAS_HOST>:8443/webhook/telegram
TELEGRAM_WEBHOOK_SECRET=random-secret-string
TELEGRAM_ALLOWED_CHAT_IDS=123456789

AI_PROVIDER=auto
GROQ_API_KEY=gsk_...
OPENROUTER_API_KEY=sk-or-v1-...

NOTION_TOKEN=ntn_...
NOTION_QUICK_NOTE_PAGE_ID=32-char-hex-uuid
```

| Variable | Description |
| --- | --- |
| `LINE_SECRETARY_CHANNEL_SECRET` | LINE Messaging API channel secret |
| `LINE_SECRETARY_CHANNEL_ACCESS_TOKEN` | LINE Messaging API channel access token |
| `LINE_SECRETARY_ALLOWED_USER_IDS` | Your LINE user ID(s). Comma-separated for multiple users. |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token from @BotFather |
| `TELEGRAM_WEBHOOK_URL` | Full HTTPS URL for the Telegram webhook. Allowed ports: 443, 80, 88, 8443. |
| `TELEGRAM_WEBHOOK_SECRET` | Secret token for validating Telegram requests (any random string) |
| `TELEGRAM_ALLOWED_CHAT_IDS` | Comma-separated numeric chat IDs allowed to use the bot. Leave empty to allow all (not recommended). |
| `NOTION_TOKEN` | Notion Internal Integration Token |
| `NOTION_QUICK_NOTE_PAGE_ID` | Notion page ID of your "Quick note" parent page. Leave empty to disable the feature. |
| `AI_PROVIDER` | `"auto"` (Groq primary + OpenRouter fallback), `"groq"`, or `"openrouter"` |
| `GROQ_API_KEY` | Groq API key |
| `OPENROUTER_API_KEY` | OpenRouter API key |

### 6. Deploy

```bash
scripts/deploy.sh -s my-secretary -y
```

## Debug commands

Send these in LINE or Telegram chat to inspect raw data (whitelisted users only):

| Command | Description |
|---|---|
| `/debug <query>` | Raw Notion search results for a query |
| `/debug2 <query>` | Full deep search — pages + embedded databases |
| `/debug3 <page_id>` | Raw block children of a Notion page |
| `/debug4 <db_id>` | Raw database query response |
| `/provider` | Active AI provider and time remaining until Groq resumes (if rate-limited) |
| `/cache` | Cache stats — page count and time since last rebuild |
| `/refresh` | Force immediate cache rebuild |
| `/history` | Last 4 conversation exchanges |
| `/clear` | Wipe conversation history + pending state (use when bot gets stuck) |

---

## ภาษาไทย

[EN](#my-secretary)

my-secretary คือ AI bot เลขาส่วนตัวที่ค้นหาและบันทึกข้อมูลใน Notion ของคุณ รันเป็น Docker container บน Synology NAS รองรับทั้ง **LINE** และ **Telegram** — ประวัติการสนทนาแยกกันต่างหาก

---

## คุณสมบัติ

- ถามเป็นภาษาไทยหรืออังกฤษก็ได้ bot จะค้นหาใน Notion แล้วตอบ
- อ่าน page ธรรมดา, ตาราง, toggle section, และ database อัตโนมัติ
- รัน Notion search และ fallback scan พร้อมกันเสมอ — เจอข้อมูลแม้ซ่อนใน toggle
- เก็บ header ของทุก page ไว้ใน memory ตั้งแต่ตอน start และ refresh ทุก 10 นาที
- จัดลำดับ context ตาม relevance — page ที่เกี่ยวข้องสุดจะถูกส่งให้ LLM ก่อนเสมอ
- Groq→OpenRouter auto-failover ใน `AI_PROVIDER=auto`
- ตอบจากข้อมูลใน Notion เท่านั้น — ถ้าหาไม่เจอจะถามก่อนว่าต้องการให้ตอบจากความรู้ทั่วไปได้ไหม
- มี confirmation step ก่อนจะ write ข้อมูลลง Notion ทุกครั้ง
- ใส่ 🔗 Notion page URL ในแต่ละคำตอบ
- จำกัดการใช้งานด้วย LINE user ID / Telegram chat ID whitelist

## การตั้งค่า

ดูขั้นตอนการตั้งค่าทั้งหมดในหัวข้อ [Setup](#setup) ด้านบน (ภาษาอังกฤษ) — มีทั้งการตั้งค่า LINE, Telegram, Notion, AI Provider, และ deploy script
