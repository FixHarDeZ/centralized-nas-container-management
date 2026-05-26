# Daily Log — my-secretary

## 2026-05-26

### Bug fix session 2: Notion toggle/table content ไม่ทำงานบน Telegram

**ปัญหา:** Feature อ่านจาก toggle list / table ใน Notion ใช้ได้บน LINE แต่ไม่ได้บน Telegram
- "ขอ api token ทั้งหมด" → "ไม่พบข้อมูลใน Notion ค่ะ" ทั้งที่ page มีข้อมูลครบ
- "เพิ่ม api token หน่อย test-token xxx" → propose write ไป 'Scenario' แทน 'API Token | API Key'

**Root causes (3 ชั้น):**

1. **History pollution** (`store.py` / `main.py`):
   - เมื่อ LLM ตอบ "ไม่พบข้อมูลใน Notion ค่ะ" response นั้นถูก **บันทึกลง conversation history**
   - request ครั้งต่อไปที่ถามคำถามเดิม LLM เห็น pattern "ไม่พบ" ใน history → ตอบซ้ำ แม้ว่า context ใหม่มีข้อมูลครบ
   - **Fix:** `main.py` — ไม่บันทึก response ที่มี `"ไม่พบข้อมูลใน Notion"` เข้า history

2. **Context ranking ไม่ weighted ตาม title** (`agent.py` `_rank_context`):
   - `_rank_context` นับ keyword hits จาก `title + content` โดยให้น้ำหนักเท่ากัน → daily log pages ที่มีคำว่า "api"/"token" เยอะใน body content ชนะ 'API Token | API Key' (exact title match)
   - **Fix:** `_rank_context` → title matches ×10, body matches ×1 (เหมือน `_fallback_scan` ที่แก้ก่อนหน้า)

3. **Fallback ranking เดิม** (`agent.py` `_fallback_scan`): แก้ไปแล้ว session ก่อน ✅

**ผลลัพธ์หลัง fix:**
- `Context built: pages=['API Token | API Key', ...]` — rank #1 ✅
- WRITE: `PATCH /blocks/33759cb6.../children → 200 OK` — เขียนลง 'API Token | API Key' ถูก table ✅
- "ไม่พบ" จะไม่ถูกบันทึกลง history อีกต่อไป → ป้องกัน re-poisoning ✅

**Diagnostic logs เพิ่ม (ถาวร):**
- `PAGE[<title>]: <content[:300]>` — แสดง content snippet ของแต่ละ page ที่ส่งให้ LLM
- ช่วย debug ว่า LLM เห็นอะไรบ้าง

**ไฟล์ที่เปลี่ยน:**
- `my-secretary/main.py` — ไม่บันทึก "ไม่พบ" ลง history
- `my-secretary/agent.py` — title ×10 ใน `_rank_context` + diagnostic page content log

---

### Bug fix: Groq 413 "Request Too Large" → failover to OpenRouter

**ปัญหา:** Telegram user ถามคำถามที่ดึง Notion context ใหญ่ (เช่น "ขอ uid เกม wuwa") แล้วได้รับ "เกิดข้อผิดพลาดขึ้นค่ะ ลองใหม่อีกครั้งนะคะ"

**Root cause:** Groq free tier มี TPM limit 12,000 tokens/min แต่ context ที่ประกอบขึ้น (12,587 tokens) เกิน limit → Groq ตอบ HTTP 413 (`APIStatusError`) ซึ่งไม่ได้รับการ handle (code เดิม catch แค่ `RateLimitError` = 429) → exception propagate ขึ้นไปถึง `handle_message` → retry loop fail → user เห็น error

**Fix:**

`my-secretary/provider.py`
- เพิ่ม `on_groq_too_large(settings)` — failover ไป OpenRouter โดย **ไม่ block Groq** (ต่างจาก `on_groq_rate_limit` ที่ block ชั่วคราว เพราะ 413 เป็น context ใหญ่เกินไปเท่านั้น ไม่ใช่ quota หมด)

`my-secretary/agent.py`
- import `APIStatusError` จาก `openai`
- เพิ่ม `except APIStatusError as e: if e.status_code == 413` handler ใน 3 จุด:
  1. `_search_variants()` — small model call สำหรับ Thai translation
  2. `run()` — main LLM call
  3. `run_general()` — general knowledge call

**Deployed:** ✅ Container rebuilt + restarted สำเร็จ

## 2026-05-24

### เพิ่ม Telegram support + rename line-secretary → my-secretary

**Rename (ก่อนหน้า session นี้)**
- `git mv line-secretary my-secretary` — เปลี่ยนชื่อ folder + service + volume + container
- อัปเดต `scripts/deploy.sh` ALL_STACKS, `CLAUDE.md`, `.notes/00_INDEX.md`

**Telegram support — ไฟล์ที่เปลี่ยน:**

`my-secretary/telegram_client.py` (ใหม่)
- `send_message(chat_id, text, token)` — POST to Telegram API, split ที่ 4096 chars
- `register_webhook(token, url, secret_token)` — POST to `setWebhook`

`my-secretary/config.py`
- เพิ่ม 4 env ใหม่: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_URL`, `TELEGRAM_WEBHOOK_SECRET`, `TELEGRAM_ALLOWED_CHAT_IDS`
- เพิ่ม property `telegram_allowed_chat_ids` → `set[str]`

`my-secretary/main.py`
- **Refactor `_push_long(user_id, text, token)` → `_push_long(text, push_fn)`** — platform-agnostic
- **Refactor `handle_message(event)` → `handle_message(user_id, text, push_fn)`** — LINE whitelist check ข้ามสำหรับ `tg_` prefix
- **Refactor `handle_non_text_message`** รับ `(user_id, msg, push_fn, download_fn=None)`
- LINE webhook: เปลี่ยนมาสร้าง `push_fn = lambda t: line_client.push(_uid, t, token)` แล้วส่งเข้า `handle_message`
- เพิ่ม `POST /webhook/telegram`: validate `X-Telegram-Bot-Api-Secret-Token`, check whitelist, dispatch `handle_message("tg_{chat_id}", text, push_fn)`
- lifespan: เรียก `telegram_client.register_webhook()` ถ้า token + url ตั้งไว้

`my-secretary/.env.example`, `my-secretary/README.md`, `README.md`
- เพิ่ม Telegram section

**Tests:** 38/38 passed (เพิ่ม 11 test ใหม่)
- `test_send_message_short`, `test_send_message_splits_at_4096`, `test_register_webhook`
- `test_telegram_allowed_chat_ids_parsed/empty`
- webhook endpoint: wrong secret (403), missing secret (403), no message (200), no text (200), unauthorized chat (200), dispatches handle_message

**ผลกระทบข้างเคียง**
- `agent.py` + `store.py`: เพิ่ม `from __future__ import annotations` เพื่อแก้ Python 3.9 compat บน macOS dev machine (Python 3.12 บน NAS ไม่มีปัญหา)
- `tests/conftest.py`: เพิ่ม `DATA_DIR` → tempdir, Telegram env defaults
- `tests/test_quick_wins.py`: อัปเดต `test_push_long_*` ให้ตรงกับ signature ใหม่

## 2026-05-20

### ลบ Reminder + 5 features ใหม่

**ลบ Reminder feature** — ออกจาก `main.py`, `notion.py`, `config.py`, `.env.example` ทั้งหมด

**#3 `/history` command** (`main.py`)
- แสดงประวัติล่าสุด 4 exchange (user/bot แต่ละคู่) truncate ที่ 120 ตัวอักษรต่อ line

**#4 Pagination** (`notion.py`)
- `list_all_pages()` เปลี่ยนจาก limit=50 เป็น cursor-based pagination (page_size=100)
- วน loop `has_more` + `next_cursor` จนครบทุก page — ไม่ miss pages อีก

**#5 Search page_size** (`notion.py`)
- เพิ่มจาก 8 → 20 results ต่อ query

**#7 Agent สร้าง Notion page** (`agent.py`)
- เพิ่ม `propose_create_page` tool ใน SYSTEM_PROMPT (case G) และ PROPOSE_TOOLS set
- Handler ใน `agent.run()`: สร้าง pending `write_type: "new_page"`
- Execute ใน `_write_one()`: call `notion.create_page()` แล้ว `notion.append_blocks()` ถ้ามี content
- รองรับ Markdown-like formatting เหมือน quick note

**#8 LINE image → Notion** (`line_client.py`, `notion.py`, `main.py`)
- `line_client.download_content()` — ดึง binary จาก LINE Data API
- `notion.upload_image()` — Notion File Upload API (2 step: create + send)
- `notion.append_image_block()` — append `image` block ด้วย `file_upload_id`
- `handle_non_text_message()` — ถ้าส่งรูปตอน `waiting_content` phase → upload แนบ note อัตโนมัติ
- ถ้าส่งรูปนอก note flow → แจ้ง "พิมพ์ 'จดหน่อย' ก่อน"

**Test:** 27/27 passed

## 2026-05-19

### 7 Features ใหม่ (batch)

**#1 Non-text message handler** (`main.py`)
- webhook loop เปลี่ยนจากกรองแค่ `type == text` เป็นแยก handler
- เพิ่ม `handle_non_text_message()` — ตอบ "รับแค่ข้อความ (text) ค่ะ ไม่สามารถประมวลผล {msg_type} ได้ค่ะ" กับ image/sticker/location

**#2 `/cache` stats command** (`cache.py`, `main.py`)
- เพิ่ม `PageCache.stats()` คืน `{pages, indexed, age_seconds}`
- คำสั่ง `/cache` ใน LINE แสดงจำนวน page + เวลา rebuild ล่าสุด

**#3 Timeout บน `agent.run()`** (`main.py`)
- ครอบ `asyncio.wait_for(..., timeout=45)` ทุก LLM call รวมถึง retry
- timeout ตอบ "ขอโทษค่ะ ใช้เวลานานเกินไป" แทนค้างไม่ตอบ

**#4 Append to existing note** (`main.py`)
- ใน `asking_topic` phase ตรวจ cache ก่อนว่ามี page ชื่อตรงกัน (case-insensitive)
- ถ้าเจอ → ข้ามสร้าง page ใหม่ แค่ set state `appending=True` แล้ว append content เข้าไป
- ถ้าไม่เจอ → flow เดิม (สร้าง page ใหม่)
- reply ต่างกัน: "เพิ่มเนื้อหาลง" vs "บันทึกลง"

**#5 Richer note formatting** (`notion.py`)
- เพิ่ม `_line_to_block()` แปลง Markdown-like prefix เป็น Notion block type
  - `# ` → heading_1, `## ` → heading_2, `### ` → heading_3
  - `- ` / `* ` → bulleted_list_item
  - `[ ] ` / `- [ ] ` → to_do (unchecked)
  - `[x] ` / `- [x] ` → to_do (checked)
  - อื่นๆ → paragraph
- `append_blocks()` ใช้ `_line_to_block()` แทนสร้าง paragraph ทุกบรรทัด

**#6 Pending TTL** (`store.py`)
- pending ทั้ง 3 state wrap ด้วย `{"data": ..., "ts": float}`
- `has_pending*` ตรวจ TTL 6 ชั่วโมง — ถ้าหมดอายุ auto-pop + log
- backward compatible กับ state.json เก่า (format ไม่มี "ts" → ไม่ expire)

**#7 Proactive reminders** (`notion.py`, `config.py`, `main.py`)
- env ใหม่: `NOTION_REMINDER_DB_IDS` (comma-sep DB IDs), `NOTION_REMINDER_TIME` (HH:MM BKK, default "08:00")
- `get_database_rows_with_dates()` ใน notion.py — query DB คืน rows ที่มี date property
- `_reminder_loop()` + `_check_reminders()` ใน main.py — asyncio background task
- เช็ค date = วันนี้ (Bangkok UTC+7) แล้ว push LINE ให้ทุก allowed_user_ids
- เริ่ม task ใน lifespan ถ้า `NOTION_REMINDER_DB_IDS` ไม่ว่าง

**Test:** 27/27 passed
