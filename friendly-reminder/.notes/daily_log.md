# Daily Log — Friendly Reminder

## 2026-06-26
- สร้าง stack ใหม่ `friendly-reminder/` ครบทั้งหมด
- Files: Dockerfile, docker-compose.yml, requirements.txt, secrets.manifest.yaml, nginx/nginx.conf
- App: app/__init__.py, app/db.py, app/main.py, app/notify.py (vendored shared)
- Frontend: app/static/index.html, style.css, app.js (dark theme, Thai language)
- เพิ่ม entry ใน CLAUDE.md (port 5066)
- Pending: vault keys + htpasswd ต้องทำ manual ก่อน deploy
- **Fix 500 Internal Server Error:** nginx `.htpasswd` บน NAS เป็น `600 root:root` → nginx worker (user `nginx`) อ่านไม่ได้ → `[crit] open(".htpasswd") failed (13: Permission denied)` → 500. สาเหตุ: deploy ครั้งแรก tar extract ด้วย `--no-same-permissions` (deploy.sh:204) + root umask 077 → 644 กลายเป็น 600. Fix: `chmod 644` บน NAS + `nginx -s reload` → 200. (stack อื่น 4 ตัวเป็น 644 อยู่แล้ว, chmod ครั้งเดียวอยู่ถาวรเพราะ tar overwrite เก็บ perm ไฟล์เดิม)
