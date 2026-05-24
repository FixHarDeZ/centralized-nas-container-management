# Daily Log — line-secretary

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
