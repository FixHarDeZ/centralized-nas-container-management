# CLAUDE.md

This file guides Claude Code (claude.ai/code) on project rules, architecture, and deployment for this Synology NAS Docker repository.

## 📌 Memory & Documentation Rules (Strict)

*   **Before Task:** อ่านไฟล์ใน `.notes/` ของ sub-directory นั้นๆ ก่อนเริ่มงานเสมอ
*   **After Task:** สรุปสิ่งที่ทำลงใน `.notes/daily_log.md` ทุกครั้งที่จบงาน
*   **Every Session End:** อัปเดตข้อมูลที่เปลี่ยนไป (DB schema, API, settings, gaps) ใน `.notes/00_INDEX.md` ควบคู่กับ log เสมอ (ไม่มีข้อยกเว้น ไม่ต้องรอ structural change)
*   **Notion Sync:** บันทึกขึ้น Notion ด้วยคำสั่ง: `python3 scripts/sync_notion.py "[Title]" "[Content]"`

---

## 🛠️ Tech Stack & Global Config

*   **Environment:** ไฟล์ `.env` อยู่ที่ root ใช้ร่วมกันทุก Stacks (**ห้าม Commit เด็ดขาด**)
*   **Target OS:** Synology DSM 7.3.2 (Container Manager) บน DS925+ NAS
*   **Deployment:** ใช้สคริปต์ `scripts/deploy.sh` เพื่อ rsync โค้ดผ่าน SSH (Key-based) และสั่ง Restart Container อัตโนมัติ (ใช้ `NAS_SUDO_PASSWORD` ในการสั่ง `sudo docker compose down && up -d --build`)

### Adding New Stack to DSM
1. รัน `scripts/deploy.sh` เพื่ออัปโหลดไฟล์ไปที่ NAS (`/volume1/docker/`)
2. เปิด **Container Manager** -> **Project** -> **Create** -> เลือก Path โฟลเดอร์ -> กด **Build**

---

## 📦 Stacks Directory & Ports

| Directory | Purpose | Port (Internal / HTTPS via Proxy) |
| :--- | :--- | :--- |
| `homepage/` | Dashboard UI (gethomepage) | 3000 / 443 |
| `jellyfin/` | Media server (NVIDIA GPU Transcoding) | 8096 |
| `maid-tracker/` | ระบบลงเวลา/คำนวณเงินเดือนแม่บ้าน (FastAPI + SQLite) | 5055 |
| `portainer/` | Docker management UI | 9000 |
| `uptime-kuma/` | Service health monitor | 3001 |
| `watchtower/` | อัปเดต Container อัตโนมัติ + LINE Notification Sidecar | — |
| `line-secretary/`| AI LINE Bot เลขาส่วนตัว (FastAPI + Groq LLM + Notion) | 5057 / 5058 |
| `torrentwatch/` | สคริปต์ดูด/กรอง Torrent จาก bearbit.org + แจ้งเตือน LINE | 5059 / 5062 |

---

## 📐 Stack Architecture Summary

### 1. Homepage (`homepage/`)
*   ต่อหลัง Nginx Proxy (ทำ HTTPS + HTTP Basic Auth ด้วย `NGINX_BASIC_AUTH_*`)
*   ดึง SSL Cert จากระบบ Synology (`/usr/syno/etc/certificate/system/default/`)
*   ใช้ `HOMEPAGE_VAR_*` จาก root `.env` ในการใส่ความลับลง `services.yaml`
*   Widget ของ NAS ให้ใช้ IP ตรง `http://192.168.x.x:5000` (HTTP) เพื่อเลี่ยง Cert mismatch

### 2. Watchtower (`watchtower/`)
*   มี 2 Services: ตัวหลักอัปเดตอิมเมจ (ทุก 24 ชม.) + ตัว Sidecar (`watchtower-notifier` รันด้วย Python 3.12-slim)
*   Sidecar อ่าน Log ผ่าน Unix Socket โดยตรง และส่ง Push Notification เข้า LINE Messaging API
*   ตัว Sidecar ติดป้ายกำกับห้ามตัวเองอัปเดตอัตโนมัติ (`com.centurylinklabs.watchtower.enable=false`)

### 3. Maid Tracker (`maid-tracker/`)
*   FastAPI + SQLite (ข้อมูลเซฟใน volume `maid_tracker_data` ที่ `/data`) + Static SPA (Bootstrap 5)
*   **Logic:** ทำงาน จ-ส (อาทิตย์ = Holiday), ขาด/ลา/มาชดเชย คิดทศนิยมได้ (0.5 / 1.0 วัน) เก็บในตาราง `attendance` ฟิลด์ `half_day`
*   **Salary:** เรทรายวัน = `เงินเดือน ÷ จำนวนวันทำงานในเดือนนั้นๆ` ไม่หักเงินรายเดือน แต่สะสมยอดลา/ชดเชยไปคิดตอนลาออก
*   ส่งแจ้งเตือน Check-in/out และสรุปรายเดือนเข้า LINE

### 4. Line Secretary (`line-secretary/`)
*   FastAPI รับ Webhook จาก LINE (ต้องใช้พอร์ต HTTPS 5058) + ใช้ Groq (`llama-3.3-70b-versatile`)
*   มี Agent Tools สำหรับจัดการ Notion (Search, Get Content, Schema, Query, Propose Create)
*   **Security:** มี Whitelist ผู้ใช้ (`LINE_SECRETARY_ALLOWED_USER_IDS`), การเขียนข้อมูลลง Notion ต้องรอผู้ใช้พิมพ์ยืนยันว่า **"ใช่"** เสมอ
*   เซฟ State (`pending`, `history` ย้อนหลัง 4 ครั้ง) ไว้ที่ `/data/state.json` (ข้อมูลไม่หายตอนรีสตาร์ท)

### 5. TorrentWatch (`torrentwatch/`)
*   FastAPI (พอร์ต HTTPS 5062) + เก็บข้อมูลใน volume `torrentwatch_data`
*   **Schedule (เวลาไทย):** 19:00–01:00 (ทุก 30 นาที) / 01:00–06:00 (หยุดรัน) / 06:00–19:00 (ทุก 60 นาที)
*   รองรับ Multi-source แยก Keyword และตั้งค่าผ่าน Settings UI ดึงปักหมุด bearbit ได้ (และเคลียร์ออกอัตโนมัติถ้าหลุดหมุด)
*   โหลดไฟล์เข้าเครื่องผ่าน Proxy Browser หรือเซฟลง `/downloads` (NAS path) โดยตรง
*   ลบประวัติเก่าเกิน 7 วันทุกวันอาทิตย์ตี 3, แก้ Selector การดูดเว็บได้ที่ด้านบนของ `scraper.py`
*   มี endpoint `/api/status` เป็น Public สำหรับดึงไปโชว์ที่ Homepage

---

## 🚀 Release & Security Process

เมื่อมีการเรียกใช้คำสั่ง `/release` **ให้ทำตามลำดับนี้ก่อน Commit เสมอ:**
1.  **Update Stack README:** หากแก้ฟีเจอร์, ตั้งค่า, API หรือสถาปัตยกรรมของ Stack ใด ให้แก้ `README.md` ในโฟลเดอร์นั้นทันที
2.  **Update Root Docs:** หากกระทบภาพรวม (เช่น เพิ่ม Stack ใหม่, เปลี่ยนพอร์ต, เพิ่ม Env) ให้แก้ `CLAUDE.md` และ `README.md` ที่ root
3.  **One Commit:** รวมไฟล์เอกสารที่อัปเดตเข้ากับ Commit ของโค้ดหลักพร้อมกันเลย (ห้ามแยก Commit เอกสาร)
4.  **Security:** ห้าม Commit `.env`, ห้าม Hardcode ไอพี/ชื่อโฮสต์/รหัสผ่านจริง ให้ใช้ Placeholder เช่น `<NAS_HOST>`, `<NAS_USER>` แทนเสมอ