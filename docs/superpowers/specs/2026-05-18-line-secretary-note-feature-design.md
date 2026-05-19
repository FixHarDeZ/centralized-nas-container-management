# Design: Line Secretary — Quick Note Feature

**Date:** 2026-05-18
**Stack:** `line-secretary/`
**Approach:** A — new `pending_note` state + inline handler in `main.py`

---

## Overview

เพิ่มความสามารถ "จดโน้ต" ให้ LINE bot: เมื่อผู้ใช้พิมคำสั่งที่มีความหมายว่า "ให้จด" บอทจะถามหัวข้อ → สร้าง Notion sub-page ใน Quick note → รับเนื้อหา (1 ข้อความ) → บันทึกลงหน้านั้น

---

## Conversation Flow

```
user:  "จดหน่อย"
bot:   "จะจดเรื่องอะไรคะ? 📝"

user:  "ค่าน้ำเดือนพฤษภาคม"
bot:   "สร้าง page 'ค่าน้ำเดือนพฤษภาคม' แล้วค่ะ 📄 ส่งเนื้อหาที่จะจดมาได้เลยค่ะ"

user:  "200 บาท จ่าย 15/5/2026\nรหัสอ้างอิง 1234"
bot:   "บันทึกเรียบร้อยแล้วค่ะ ✅"
```

`/clear` resets `pending_note` mid-flow.

---

## State Machine

New state key in `store.py` — `pending_note` (per user):

| Phase | Payload | Meaning |
|---|---|---|
| `asking_topic` | `{"phase": "asking_topic"}` | รอผู้ใช้บอกหัวข้อ |
| `waiting_content` | `{"phase": "waiting_content", "page_id": "...", "title": "..."}` | รอเนื้อหา (page สร้างแล้ว) |

---

## Handler Order in `handle_message()`

```
1. /debug*, /provider, /help, /clear     (unchanged — /clear adds pending_note clear)
2. has_pending_note()  → note flow       ← NEW
3. _is_note_intent()   → start note flow ← NEW
4. has_pending_general()                 (unchanged)
5. has_pending()                         (unchanged)
6. agent.run()                           (unchanged)
```

---

## Intent Detection

```python
_NOTE_INTENT_KEYWORDS = [
    "จดหน่อย", "จดให้หน่อย", "จดให้ด้วย", "จดด้วย",
    "เตรียมจด", "ช่วยจด", "จดไว้", "บันทึกให้หน่อย",
    "note please", "please note", "help me note", "take a note", "make a note",
]

def _is_note_intent(text: str) -> bool:
    t = text.lower().strip()
    return any(k in t for k in _NOTE_INTENT_KEYWORDS)
```

Match strategy: substring `in` — รองรับ "จดหน่อยนะคะ", "ช่วยจดให้หน่อยได้ไหม" ฯลฯ

---

## Files Changed

| File | Change |
|---|---|
| `store.py` | เพิ่ม `pending_note` CRUD functions (get/set/pop/has) |
| `notion.py` | เพิ่ม `create_page()` + `append_blocks()` |
| `config.py` | เพิ่ม `NOTION_QUICK_NOTE_PAGE_ID: str = ""` |
| `main.py` | เพิ่ม `_is_note_intent()`, note flow handler, update `/clear`, update `/help` |

---

## Notion API Details

### `create_page(token, parent_page_id, title) -> dict`

```
POST /v1/pages
{
  "parent": {"page_id": parent_page_id},
  "properties": {
    "title": {"title": [{"type": "text", "text": {"content": title}}]}
  }
}
```

Returns full page object — `page["id"]` used as `page_id` for content append.

### `append_blocks(token, page_id, text) -> dict`

```
PATCH /v1/blocks/{page_id}/children
{
  "children": [
    {"object": "block", "type": "paragraph",
     "paragraph": {"rich_text": [{"type": "text", "text": {"content": line}}]}}
    // one block per non-empty line (split on \n)
  ]
}
```

Constraints: max 100 blocks per call, 2000 chars per `rich_text.content`. Content beyond 2000 chars per line gets truncated (personal bot — unlikely edge case).

---

## Config

`.env` — user adds:
```env
NOTION_QUICK_NOTE_PAGE_ID=<page-id-of-Quick-note>
```

`config.py` — adds field:
```python
NOTION_QUICK_NOTE_PAGE_ID: str = ""
```

---

## Error Handling

| Error | Handling |
|---|---|
| `create_page` fails | Reply error message + `pop_pending_note()` — ไม่ค้างใน state |
| `append_blocks` fails | Reply error + Notion page URL ที่สร้างไปแล้ว — ผู้ใช้ไปพิมเองได้ |
| `NOTION_QUICK_NOTE_PAGE_ID` ไม่ได้ตั้งค่า | Reply "ยังไม่ได้ตั้งค่า Quick note page ค่ะ" + `pop_pending_note()` |

---

## Out of Scope

- Multi-message content accumulation (ส่งข้อความเดียวจบ)
- LLM-assisted formatting
- Editing/deleting notes via bot
