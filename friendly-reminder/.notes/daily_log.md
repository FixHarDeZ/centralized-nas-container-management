# Daily Log — Friendly Reminder

## 2026-06-26 (v2)
- Fix: ยอดค้างจ่าย not update — เพิ่ม `conn.commit()` explicit ใน mark_paid/mark_unpaid ก่อน return + เปลี่ยน JS pay/unpay เป็น sequential แทน Promise.all
- Add: slip upload per payment (`POST /api/payments/{id}/slip`, `DELETE /api/payments/{id}/slip`, `GET /api/slips/{fn}`) — รองรับ jpg/png/webp/pdf
- Add: day-before LINE notification — scheduler รันทุกวันเวลา `DAY_BEFORE_REMINDER_TIME` (default 20:00) ส่งเฉพาะวันสุดท้ายของเดือน (พรุ่งนี้ = วันที่ 1)
- DB migration: เพิ่ม `slip_filename TEXT` column ใน payments table

## 2026-06-26 (v1)
- สร้าง stack ใหม่ `friendly-reminder/` ครบทั้งหมด
- Files: Dockerfile, docker-compose.yml, requirements.txt, secrets.manifest.yaml, nginx/nginx.conf
- App: app/__init__.py, app/db.py, app/main.py, app/notify.py (vendored shared)
- Frontend: app/static/index.html, style.css, app.js (dark theme, Thai language)
- เพิ่ม entry ใน CLAUDE.md (port 5066)
- Pending: vault keys + htpasswd ต้องทำ manual ก่อน deploy
