# Friendly Reminder — Index

## Stack Overview
FastAPI + SQLite + Nginx Basic Auth  
ติดตามการผ่อนชำระรายเดือน แจ้งเตือนผ่าน LINE

## DB Schema
- `installments` — รายการผ่อน (name, total_price, num_installments, start_date YYYY-MM, due_day 1-31, note)
- `payments` — งวดการชำระ (installment_id, installment_number, due_year, due_month, amount, paid_at, slip_filename)

## ENV vars (from vault)
- `FRIENDLY_LINE_CHANNEL_ACCESS_TOKEN` → `stacks.friendly_reminder.line.channel_access_token`
- `FRIENDLY_LINE_CHANNEL_SECRET` → `stacks.friendly_reminder.line.channel_secret` (webhook signature verify)
- `FRIENDLY_LINE_GROUP_ID` → `stacks.friendly_reminder.line.group_id`
- `REMINDER_TIME` = `"08:00"` (literal — เวลารันแจ้งเตือน "ครบกำหนด/เกินกำหนด" ทุกวัน ยิงซ้ำจนกว่าจ่าย)
- `DAY_BEFORE_REMINDER_TIME` = `"20:00"` (literal — แจ้งเตือนล่วงหน้า 1 วันก่อน due_day)
- `DATA_DIR` = `/data`

## API Endpoints
- `GET /api/installments` — list all with stats
- `POST /api/installments` — create (name, total_price, num_installments, start_date, due_day, note)
- `GET /api/installments/{id}` — detail + all payments
- `DELETE /api/installments/{id}` — delete (cascades to payments)
- `POST /api/payments/{id}/pay` — mark paid → sends LINE notification
- `POST /api/payments/{id}/unpay` — undo
- `GET /api/summary` — current month view
- `GET /api/report` — CSV download

## Scheduler
- Cron: วันที่ 1 ของทุกเดือน เวลา `REMINDER_TIME` → ส่ง LINE รายการที่ยังไม่จ่าย

## Gaps / TODOs
- ยังไม่ได้เพิ่ม vault keys (ต้อง `make edit-vault` เพิ่ม `stacks.friendly_reminder.line.*`)
- ยังไม่ได้สร้าง `nginx/.htpasswd` (ต้อง `htpasswd -c nginx/.htpasswd <user>`)
- ยังไม่ sync `app/notify.py` เข้า `shared/` (vendored manually)
