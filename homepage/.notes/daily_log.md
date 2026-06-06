# Daily Log — homepage

---

## 2026-06-06 — Phase 1+2 enhance: Glances + bookmark reorg

### งานที่ทำ

**Phase 1 — Glances system monitor**
- เพิ่ม `glances` service ใน `docker-compose.yml` (image `nicolargo/glances:latest-full`, expose 61208, `pid: host`, `privileged: true`, NVIDIA env mirror Jellyfin)
- `widgets.yaml`: เพิ่ม 2 glances top-bar widgets — `metric: gpu:0` + `metric: process` (API v4)
- `services.yaml`: เพิ่ม Glances tile ใน `📥 Downloads & Monitoring` (type: glances, metric: info)

**Phase 2 — Bookmark reorganization**
- `bookmarks.yaml` rewrite — 5 groups: Quick Access / NAS Admin / Network / Dev Tools / Reference
- เพิ่ม shortcut: Anthropic Console, OpenRouter, Synology DSM/Container Manager direct link, regex101, JSON Crack, Homepage Docs, Jellyfin Docs

**ไฟล์ที่เปลี่ยน:**
- `homepage/docker-compose.yml` — เพิ่ม glances service
- `homepage/config/widgets.yaml` — rewrite ใส่ glances blocks
- `homepage/config/services.yaml` — เพิ่ม Glances tile
- `homepage/config/bookmarks.yaml` — rewrite 5 groups
- `homepage/README.md` — อัปเดต file map + Glances section

**Next:**
- Deploy: `make secrets && ./scripts/deploy.sh` แล้ว restart homepage stack ใน Container Manager
- Verify: เปิด dashboard, ดู GPU widget แสดง NVIDIA stats (ต้องมี Jellyfin transcoding active เพื่อเห็น %)
- ถ้า glances UI ไม่ขึ้น: check container log `docker logs glances` — Synology อาจไม่ allow `pid: host` หรือ `privileged: true` ตาม security policy

---

## 2026-05-28 — เพิ่ม n8n widget

### งานที่ทำ

เพิ่ม n8n (Secretary Stack, port 5678/15678) เข้า dashboard ใน section **📝 Tools & Notes**

**ไฟล์ที่เปลี่ยน:**

`homepage/config/services.yaml`:
- เพิ่ม n8n entry ต่อท้าย Hermes Agent — ใช้ `type: n8n` widget + ping

`homepage/.env.example`:
- เพิ่ม 2 ตัวแปร: `HOMEPAGE_VAR_N8N_HTTP`, `HOMEPAGE_VAR_N8N_HTTPS`, `HOMEPAGE_VAR_N8N_KEY`
- สร้าง API key ใน n8n → Settings → API → Create API Key แล้วใส่ใน `.env`

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
