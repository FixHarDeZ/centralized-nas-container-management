# Line Secretary

**EN** | [ไทย](#ภาษาไทย)

A personal AI secretary LINE bot that searches and records information in your Notion workspace. Runs as a Docker container on Synology NAS.

---

## Features

- Ask anything in natural language (Thai or English) — the bot searches your Notion and answers
- Reads pages, simple tables, toggle sections, and embedded databases automatically
- Proposes a confirmation before writing any new record to Notion
- Whitelist-based access — only your LINE user ID can use the bot

## How it works

```
You (LINE) → Webhook → FastAPI app
                           ↓
                  Notion search (multi-query)
                           ↓
                  Auto-read pages & tables
                           ↓
                  Groq LLM (llama-3.3-70b)
                           ↓
                  Answer → LINE push
```

1. Every message triggers a Notion search with multiple keyword variants
2. Pages, toggle blocks, and simple tables are read recursively (up to 2 levels deep)
3. The Groq LLM receives the Notion data as context and generates a Thai/English answer
4. Write requests go through a confirmation step before touching Notion

## Stack

| Component | Detail |
|---|---|
| Runtime | Python 3.12 · FastAPI · Uvicorn |
| AI | Groq `llama-3.3-70b-versatile` (free tier) |
| Knowledge base | Notion API (Internal Integration Token) |
| Messaging | LINE Messaging API |
| Host port | `5057` → container `8000` |
| Reverse proxy | Synology RP `https://…:5058` → `http://localhost:5057` |

## Setup

### 1. Groq API Key (free)

Sign up at [console.groq.com](https://console.groq.com) and create an API key.

### 2. Notion Integration Token

1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations) → **New integration**
2. Copy the **Internal Integration Token**
3. In Notion, open each page/database you want the bot to access → **Share** → invite the integration

### 3. LINE Official Account

1. Go to [developers.line.biz](https://developers.line.biz) → Create a **Messaging API** channel
2. Copy **Channel Secret** and **Channel Access Token**
3. Set webhook URL: `https://<NAS_HOST>:5058/webhook`
4. Enable **Use webhooks**, disable **Auto-reply messages**

### 4. Environment variables

Add to the root `.env`:

```env
LINE_SECRETARY_CHANNEL_SECRET=...
LINE_SECRETARY_CHANNEL_ACCESS_TOKEN=...
LINE_SECRETARY_ALLOWED_USER_IDS=Uxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
GROQ_API_KEY=gsk_...
NOTION_TOKEN=ntn_...
```

> `LINE_SECRETARY_ALLOWED_USER_IDS` — your LINE user ID (found in LINE Developers Console → Messaging API → Your user ID). Comma-separated for multiple users.

### 5. Deploy

```bash
./deploy.sh   # upload files and optionally restart line-secretary
```

Register in Synology Container Manager → Project → Create → path `/volume1/docker/line-secretary`.

## Debug commands

Send these in LINE chat to inspect raw data (owner only):

| Command | Description |
|---|---|
| `/debug <query>` | Raw Notion search results for a query |
| `/debug2 <query>` | Full deep search — pages + embedded databases |
| `/debug3 <page_id>` | Raw block children of a Notion page |
| `/debug4 <db_id>` | Raw database query response |

## Example usage

```
You:  ขอเลขบัตรเครดิต UOB
Bot:  บัตร UOB Preferred Platinum: xxxx-xxxx-xxxx-2917
      บัตร UOB World: xxxx-xxxx-xxxx-0262
      (จาก page Credit cards)

You:  github api token ฉันคืออะไร
Bot:  GitHub token: ghp_xxxxxxxxxxxx
      (จาก page API Token)

You:  จด github token ใหม่ให้หน่อย github ghp_newtoken123
Bot:  จะบันทึก GitHub token ghp_newtoken123 ใน database 'API Token' ใช่ไหมครับ?
      ตอบ 'ใช่' เพื่อยืนยัน
You:  ใช่
Bot:  บันทึกเรียบร้อยแล้วครับ
```

---

## ภาษาไทย

Line Secretary คือ LINE bot เลขาส่วนตัว AI ที่ค้นหาและบันทึกข้อมูลใน Notion ของคุณ รันเป็น Docker container บน Synology NAS

---

## คุณสมบัติ

- ถามเป็นภาษาไทยหรืออังกฤษก็ได้ bot จะค้นหาใน Notion แล้วตอบ
- อ่าน page ธรรมดา, ตาราง (simple table), toggle section, และ database อัตโนมัติ
- มี confirmation step ก่อนจะ write ข้อมูลใหม่ลง Notion ทุกครั้ง
- จำกัดการใช้งานด้วย LINE user ID whitelist

## การทำงาน

```
คุณ (LINE) → Webhook → FastAPI
                           ↓
              ค้นหา Notion หลาย keyword variants
                           ↓
              อ่าน page, table, toggle แบบ recursive
                           ↓
              Groq LLM วิเคราะห์ข้อมูล + ตอบ
                           ↓
              ส่งคำตอบกลับ LINE
```

## การตั้งค่า

### 1. Groq API Key (ฟรี)

สมัครที่ [console.groq.com](https://console.groq.com) แล้ว create API key

### 2. Notion Integration Token

1. ไปที่ [notion.so/my-integrations](https://www.notion.so/my-integrations) → **New integration**
2. Copy **Internal Integration Token**
3. ใน Notion เปิดแต่ละ page/database ที่อยากให้ bot เข้าถึง → **Share** → invite integration นั้น
   > ถ้า share ที่ root page (เช่น Personal Home) จะได้ access ทุก subpage ทีเดียว

### 3. LINE Official Account

1. ไปที่ [developers.line.biz](https://developers.line.biz) → สร้าง channel แบบ **Messaging API**
2. Copy **Channel Secret** และ **Channel Access Token**
3. ตั้ง Webhook URL: `https://<NAS_HOST>:5058/webhook`
4. เปิด **Use webhooks**, ปิด **Auto-reply messages**

### 4. Environment Variables

เพิ่มใน `.env` ที่ root ของ project:

```env
LINE_SECRETARY_CHANNEL_SECRET=...
LINE_SECRETARY_CHANNEL_ACCESS_TOKEN=...
LINE_SECRETARY_ALLOWED_USER_IDS=Uxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
GROQ_API_KEY=gsk_...
NOTION_TOKEN=ntn_...
```

> `LINE_SECRETARY_ALLOWED_USER_IDS` คือ LINE user ID ของคุณ (ดูได้ใน LINE Developers Console → Messaging API → Your user ID) ถ้ามีหลายคนให้คั่นด้วย comma

### 5. Deploy

```bash
./deploy.sh   # อัปโหลดไฟล์และ restart stack
```

จากนั้น register ใน Synology Container Manager → Project → Create → path `/volume1/docker/line-secretary`

## Debug commands

ส่งใน LINE chat เพื่อ inspect ข้อมูลดิบ (เฉพาะเจ้าของ):

| Command | ทำอะไร |
|---|---|
| `/debug <query>` | แสดง raw search results จาก Notion |
| `/debug2 <query>` | แสดง deep search ทั้ง pages และ databases |
| `/debug3 <page_id>` | แสดง raw blocks ของ page นั้น |
| `/debug4 <db_id>` | แสดง raw database query response |

## ตัวอย่างการใช้งาน

```
คุณ:  ขอเลขบัตรเครดิต UOB
Bot:  บัตร UOB Preferred Platinum: xxxx-xxxx-xxxx-2917
      บัตร UOB World: xxxx-xxxx-xxxx-0262
      (จาก page Credit cards)

คุณ:  github api token ฉันคืออะไร
Bot:  GitHub token: ghp_xxxxxxxxxxxx
      (จาก page API Token)

คุณ:  จด github token ใหม่ให้หน่อย ghp_newtoken123
Bot:  จะบันทึก GitHub token ghp_newtoken123 ใน database 'API Token' ใช่ไหมครับ?
      ตอบ 'ใช่' เพื่อยืนยัน
คุณ:  ใช่
Bot:  บันทึกเรียบร้อยแล้วครับ
```
