# Daily Log — Friendly Reminder

## 2026-06-30 — Docker healthcheck + CI test coverage
- **Healthcheck** เพิ่มใน `docker-compose.yml` (service `friendly-reminder`): stdlib urllib ยิง `GET http://localhost:8000/` (StaticFiles `html=True` → index) `interval 30s / timeout 10s / retries 3 / start_period 30s`. Hung uvicorn → Docker auto-restart. Deploy + verified `(healthy)` บน NAS.
- **CI:** project เพิ่ม `.github/workflows/tests.yml` — รัน `pytest tests/` ของ stack นี้ (8 tests, `test_slip_match.py`) ทุก PR ที่แตะ `*.py`/`requirements.txt`. เดิมไม่เคยรันใน CI.

## 2026-06-26 (v3) — LINE slip auto-pay + mobile redesign
- **Mobile fix:** payments table 6 คอลัมน์ล้นจอ + CSS เดิม `@media(max-width:600px)` **ซ่อน** คอลัมน์สลิป (`nth-child(5)`) → redesign เป็น stacked cards (`display:block` + `td::before{content:attr(data-label)}`) สลิปเห็นครบ. app.js เพิ่ม `data-label` ทุก `<td>`. Polish: card box-shadow.
- **LINE webhook** `POST /webhook/line` (`app/main.py`): ตรวจ `X-Line-Signature` (HMAC-SHA256, บังคับ — endpoint flip→paid) + กรอง `source.groupId == FRIENDLY_LINE_GROUP_ID`. รูปสลิป → download จาก `api-data.line.me/.../content` ทันที (URL หมดอายุไว) เซฟลง `/data/slips`.
- **Matching logic** `app/slip_match.py` (pure, testable): "ค้าง" = `paid_at IS NULL AND ครบกำหนด ≤ เดือนนี้`. งวดเดียว→attach+pay; หลายงวด→`PendingStore` (in-memory, TTL 600s) + บอทถามชื่อ → text reply จับคู่ (exactly-one substring match) → attach+pay. Idempotent (`paid_at = COALESCE(paid_at, ?)`).
- **Vault:** เพิ่ม `channel_secret` (manifest + ต้อง `make edit-vault` ใส่ค่าจริง + test-vault dummy ก่อน `make check`/deploy ผ่าน)
- **nginx:** `location = /webhook/line` public (ข้าม basic auth)
- Tests: `friendly-reminder/tests/test_slip_match.py` 8/8 (image 1/0/many, text match/no-match/ambiguous/no-pending, TTL expiry, signature roundtrip)
- **Pending manual:** (1) `make edit-vault` → `channel_secret` (2) deploy (3) LINE OA: Use webhook ON + Auto-reply OFF + Verify

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
- **Fix 500 Internal Server Error:** nginx `.htpasswd` บน NAS เป็น `600 root:root` → nginx worker (user `nginx`) อ่านไม่ได้ → `[crit] open(".htpasswd") failed (13: Permission denied)` → 500. สาเหตุ: deploy ครั้งแรก tar extract ด้วย `--no-same-permissions` (deploy.sh:204) + root umask 077 → 644 กลายเป็น 600. Fix: `chmod 644` บน NAS + `nginx -s reload` → 200. (stack อื่น 4 ตัวเป็น 644 อยู่แล้ว, chmod ครั้งเดียวอยู่ถาวรเพราะ tar overwrite เก็บ perm ไฟล์เดิม)
- **500 กลับมาหลัง deploy (stale bind-mount):** deploy ทำ chmod host file เป็น 644 ถูกแล้ว แต่ container ยัง bind inode เก่าจากตอน start (tar `rm+recreate` ไฟล์ → inode ใหม่ host=644, container ถือ inode เก่า=600). single-file bind mount + replace = stale mount classic. nginx `image:` (ไม่ build) → `up -d --build` ไม่ recreate → ไม่ re-bind. **Fix ถาวรใน deploy.sh:** เพิ่ม `--force-recreate` ใน restart step → ทุก container re-bind ไฟล์ที่ extract ใหม่ทุก deploy (แก้ปัญหา nginx.conf/htpasswd ไม่ apply ด้วย). Trade-off: recreate ทุก service ทุก deploy (downtime สั้น, volume คงอยู่) — scope ได้ด้วย `-s <stack>`.
