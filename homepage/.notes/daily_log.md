# Daily Log — homepage

---

## 2026-05-24 — ย้ายกลับ basic auth (ลบ Authelia)

### งานที่ทำ

**เหตุผล:** ลบ Authelia auth stack ออก → homepage nginx กลับมาใช้ basic auth เหมือนเดิม

**ไฟล์ที่เปลี่ยน:**

`homepage/nginx/nginx.conf`:
- ลบ `location /authelia` (forward-auth endpoint) ออก
- ลบ `auth_request /authelia` และ `error_page 401 =302 http://<AUTHELIA_HOST>:9091` ออก
- เพิ่ม `auth_basic "Restricted"` + `auth_basic_user_file /etc/nginx/.htpasswd`
- mount path เปลี่ยนจาก `templates/default.conf.template` → `conf.d/default.conf` (ไม่ต้องใช้ envsubst แล้ว ไม่มี env vars ใน config)

`homepage/docker-compose.yml`:
- ลบ `auth_net` external network ออกทั้งหมด (nginx ไม่ต้อง join auth_net อีก)
- ลบ `AUTHELIA_HOST` env var ออกจาก nginx service
- เพิ่ม volume mount: `./nginx/.htpasswd:/etc/nginx/.htpasswd:ro`

`homepage/nginx/.htpasswd` (ใหม่, ไม่ commit):
- APR1 hash สำหรับ user `fixhardez`

`homepage/.env.example`:
- ลบ `NAS_HOST` + `AUTHELIA_HOST` block ออก (ไม่ใช้อีกต่อไป)

`homepage/.env`:
- ลบ `NAS_HOST`, `AUTHELIA_HOST`, `NGINX_BASIC_AUTH_USER`, `NGINX_BASIC_AUTH_PASS` ออก

**Deploy:** `scripts/deploy.sh -s homepage -y` — Container homepage-nginx recreated ✅

### Bug หลัง deploy — 500 Permission denied

**อาการ:** หลัง deploy ได้ 500 Internal Server Error ทันที

**Root cause:** `tar --no-same-permissions` extract `.htpasswd` ออกมาเป็น permission `600` (root-only) → nginx worker (non-root) อ่านไม่ได้ → `open() "/etc/nginx/.htpasswd" failed (13: Permission denied)`

**Fix ทันที:** `sudo chmod 644 /volume2/docker/homepage/nginx/.htpasswd` + `docker restart homepage-nginx`

**Fix ถาวร:** เพิ่ม chmod loop ใน `scripts/deploy.sh` — หลัง upload ทุกครั้งจะ `chmod 644` ทุก `nginx/.htpasswd` ใน stacks อัตโนมัติ
