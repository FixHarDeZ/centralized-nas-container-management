# CLAUDE.md

Guidance for Claude Code (claude.ai/code) on project rules, architecture, and deployment for this Synology NAS Docker repository.

## 📌 Memory & Documentation Rules (Strict)

*   **Before Task:** อ่านไฟล์ใน `.notes/` ของ sub-directory นั้นๆ ก่อนเริ่มงานเสมอ
*   **After Task:** สรุปสิ่งที่ทำลงใน `.notes/daily_log.md` ทุกครั้งที่จบงาน
*   **Every Session End:** อัปเดตข้อมูลที่เปลี่ยนไป (DB schema, API, settings, gaps) ใน `.notes/00_INDEX.md` ควบคู่กับ log เสมอ (ไม่มีข้อยกเว้น ไม่ต้องรอ structural change)
*   **Notion Sync:** บันทึกขึ้น Notion ด้วยคำสั่ง: `python3 scripts/sync_notion.py "[Title]" "[Content]"`

---

## 🛠️ Environment & Deployment Gotchas

*   **NAS Environment:** Synology DSM 7.3.2 (Container Manager) บน DS925+ NAS Target Path: `/volume2/docker/`
*   **Per-Stack .env:** ทุก stack มี `.env` ของตัวเองใน folder ของมัน (เช่น `homepage/.env`) — secrets จำกัดเฉพาะ container ที่ใช้จริง **ห้าม Commit** (gitignore pattern `.env` ครอบคลุมทุก level). Root `.env` ใช้เฉพาะ `deploy.sh` + `scripts/sync_notion.py` (`NAS_*`, `NOTION_*`) เท่านั้น — containers ไม่เห็น root `.env`
*   **.env.example:** ทุก stack มี template `.env.example` (commit ได้) — `cp <stack>/.env.example <stack>/.env` แล้วเติมค่า
*   **Deployment Flow:** ใช้ `scripts/deploy.sh` — tar รวมทั้ง project (รวม `<stack>/.env` ทั้งหมด) ส่งผ่าน SSH เท่านั้น. Root `.env` **ไม่ถูก upload** (excluded จาก tar). Restart ใช้ `docker compose --project-directory <stack>/ -f <stack>/docker-compose.yml up -d --build` เพื่อให้ compose หา `<stack>/.env` เจอเอง
*   **⚠️ ห้ามใช้ `rsync`:** macOS bundled rsync (`openrsync` protocol 29) ไม่ compatible กับ Synology GNU rsync (protocol 31) ส่งผลให้ Transfer ล้มเหลว ให้ใช้ `tar | ssh` แทนเสมอ
*   **⚠️ SSH Multi-arg Shell Quote:** หากส่งคำสั่งที่มี pipe หรือ sub-shell ผ่าน SSH ต้องห่อเป็น single quoted string เสมอเพื่อป้องกัน remote shell ตีความพลาด: `ssh host "bash -lc \"cmd | pipe\""`
*   **⚠️ DSM Auto-Block:** Container ที่ยิง DSM API (homepage widget) ถูก auto-block IP ได้ถ้า login fail ซ้ำๆ — error code 407 ที่ homepage display เป็น "Authentication failed. 2FA enabled." จริงๆ คือ Max Tries ของ Auto Block. **Fix:** Control Panel → Security → Protection → Allow List ใส่ private subnets (`10.0.0.0/255.0.0.0`, `172.16.0.0/255.240.0.0`, `192.168.0.0/255.255.0.0`) แล้วลบ Docker IPs ออกจาก Block List

---

## 📦 Stacks & Ports Directory

| Directory | Purpose | Port (Internal / Proxy) | Critical Gotchas / Architecture |
| :--- | :--- | :--- | :--- |
| `homepage/` | Dashboard UI | 3000 / 443 | ต่อหลัง Nginx Proxy + Basic Auth. ดึง SSL จาก NAS `/usr/syno/etc/certificate/system/default/`. **Widget ห้ามใช้ HTTPS/Domain** ให้ยิงตรงไปที่ DSM HTTP `http://192.168.x.x:5000` เพื่อเลี่ยง Cert Mismatch |
| `jellyfin/` | Media Server | 8096 / — | รองรับ NVIDIA GPU Transcoding |
| `maid-tracker/` | ระบบเวลา/เงินเดือนแม่บ้าน | 5055 / — | FastAPI + SQLite (Volume `/data`). คำนวณเงินเดือน จ-ส: `เงินเดือน ÷ จำนวนวันทำงานจริงเดือนนั้น`. ลา/ชดเชยบันทึกทศนิยมได้ (`half_day`) แจ้งเตือนผ่าน LINE |
| `portainer/` | Docker Management | 9000 / — | UI สำหรับจัดการคอนเทนเนอร์ในระบบ |
| `uptime-kuma/`| Service Monitor | 3001 / — | ตรวจสอบสถานะการทำงานของ Services |
| `watchtower/` | Auto-update Container | — / — | มี Sidecar `watchtower-notifier` (Python 3.12-slim) อ่าน Unix Socket Log ส่ง LINE. ติดป้ายกำกับตัวเองห้ามอัปเดต: `com.centurylinklabs.watchtower.enable=false` |
| `line-secretary/`| AI LINE Bot เลขาส่วนตัว | 5057 / 5058 (HTTPS)| FastAPI + Groq (`llama-3.3-70b-versatile`) + Notion Tools. มี Whitelist ID. **การเซฟลง Notion ต้องรอพิมพ์ยืนยัน "ใช่" เสมอ**. Save State ไว้ที่ `/data/state.json` |
| `hermes-agent/` | Autonomous AI Agent (Telegram + Discord) | 5063 (dashboard) / — (gateway) | Build clones `NousResearch/hermes-agent` from GitHub (`ARG HERMES_REF`). `config.yaml` auto-generated on first run. `network_mode: host` dropped — uses bridge networking. Port 5060/5061 blocked by browsers (SIP), uses 5063. |
| `torrentwatch/` | Scraper & Filter | 5059 / 5062 (HTTPS)| FastAPI + Volume `/data`. สแกน bearbit.org ตามช่วงเวลา (19:00-01:00 รันทุก 30 นาที / 01:00-06:00 หยุด / 06:00-19:00 รันทุก 60 นาที) โหลดเข้า `/downloads` ตรง. ลบประวัติเก่าเกิน 7 วัน ทุกวันอาทิตย์ 03:00. มี Endpoint `/api/status` แบบ Public |

---

## 🚀 Release & Security Process

เมื่อใช้คำสั่ง `/release` **ให้ปฏิบัติเรียงตามลำดับอย่างเคร่งครัดก่อน Commit เสมอ:**

1. **Update Stack README:** แก้ไขฟีเจอร์/สถาปัตยกรรมของ Stack ไหน ให้เข้าไปอัปเดต `README.md` ของโฟลเดอร์นั้นทันที
2. **Update Root Docs:** หากมีการเปลี่ยนพอร์ต, เพิ่ม Stack ใหม่ หรือเพิ่ม Env Configuration ให้แก้ไข `CLAUDE.md` และ `README.md` ที่ root
3. **Atomic Commit:** รวมไฟล์เอกสารที่อัปเดตทั้งหมดเข้ากับ Commit ของซอร์สโค้ดหลักในรอบนั้นทันที (ห้ามแยก Commit เอกสารออกจากโค้ด)
4. **Security Guardrail:** ห้าม Commit `.env` หรือ Hardcode ไอพี/รหัสผ่านจริงลงในโค้ดหรือเอกสาร ให้แทนที่ด้วย Placeholder เช่น `<NAS_HOST>`, `<NAS_USER>`, `<NAS_SUDO_PASSWORD>` ทุกครั้ง