# Memory & Notion Sync Protocol

## 1. Directory Structure
- ทุก Stack ต้องมีโฟลเดอร์ `.notes/`
- ข้อมูลหลักอยู่ที่ `00_INDEX.md` (Blueprint) และ `daily_log.md` (Raw logs)

## 2. Note Content Format (Notion Style)
เมื่อสรุปงาน ให้ใช้โครงสร้างนี้เสมอ เพื่อให้ Script สามารถ Parse ไปลง Notion ได้:

### Session Log Entry
**Timestamp:** [YYYY-MM-DD HH:mm]
**Title:** [Short Descriptive Title]
**Details:**
- [Task performed 1]
- [Technical decision made]
- [Next steps/Pending]

## 3. Post-Task Action
- หลังแก้ไข Code สำเร็จ ให้ถาม User ว่า "ต้องการบันทึกลง Daily Note หรือไม่?"
- ถ้าใช่ ให้เขียนสรุปลง `.notes/daily_log.md` และเตรียมคำสั่ง `curl` หรือรันสคริปต์ `sync_notion.py`