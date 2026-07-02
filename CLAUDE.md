# CLAUDE.md

Guidance for Claude Code (claude.ai/code) on project rules, architecture, and deployment for this Synology NAS Docker repository.

## 📌 Memory & Documentation Rules (Strict)

*   **Before Task:** อ่านไฟล์ใน `.notes/` ของ sub-directory นั้นๆ ก่อนเริ่มงานเสมอ
*   **After Task:** สรุปสิ่งที่ทำลงใน `<stack>/.notes/daily_log.md` ของ sub-directory ที่ทำงานอยู่เสมอ (เช่น งานใน `news-feed/` → เขียนที่ `news-feed/.notes/daily_log.md`) **ห้ามเขียนที่ root `.notes/`**
*   **Every Session End:** อัปเดตข้อมูลที่เปลี่ยนไป (DB schema, API, settings, gaps) ใน `<stack>/.notes/00_INDEX.md` ของ sub-directory นั้นๆ ควบคู่กับ log เสมอ (ไม่มีข้อยกเว้น ไม่ต้องรอ structural change)

---

## 🛠️ Environment & Deployment Gotchas

*   **NAS Environment:** Synology DSM 7.4 (Container Manager) บน DS925+ NAS Target Path: `/volume2/docker/`
*   **Secrets Vault:** Secrets ทั้ง project อยู่ใน `secrets/vault.sops.yaml` (sops+age encrypted, commit ลง git ได้). แต่ละ stack มี `secrets.manifest.yaml` ระบุว่าตัวเองใช้ key อะไร mapped จาก vault path ไหน (`env:` = secret จาก vault, `literals:` = ค่า public). Generator `scripts/render_env.py` (เรียกผ่าน `make secrets`) decrypt vault + อ่าน manifest → สร้าง `<stack>/.env` + root `.env.deploy` (gitignored)
*   **Workflow:** `make edit-vault` (sops transparently decrypt+re-encrypt) → `make secrets` → `./scripts/deploy.sh`
*   **NAS ไม่ต้องลง sops/age:** decryption เกิดที่ workstation, NAS รับ `<stack>/.env` plaintext แบบเดิมเป๊ะ — ไม่มี runtime decrypt
*   **Portability:** ไปเครื่องใหม่ → `age-keygen`, เพิ่ม public key ใน `.sops.yaml`, รัน `sops updatekeys secrets/vault.sops.yaml`, commit → เครื่องใหม่ใช้ `make secrets` ได้ (private key อยู่ที่ `~/.config/sops/age/keys.txt` เก็บใน Bitwarden/1Password ก็ได้)
*   **Deployment Flow:** ใช้ `scripts/deploy.sh` — pre-upload verify ว่าทุก stack มี `.env` ก่อน tar รวมโปรเจคต์ส่งผ่าน SSH. Root `.env.deploy` source ใน deploy.sh เพื่ออ่าน `NAS_*` (ไม่ upload ขึ้น NAS — excluded จาก tar). Restart ใช้ `docker compose --project-directory <stack>/ -f <stack>/docker-compose.yml up -d --build`
*   **⚠️ ห้ามใช้ `rsync`:** macOS bundled rsync (`openrsync` protocol 29) ไม่ compatible กับ Synology GNU rsync (protocol 31) ส่งผลให้ Transfer ล้มเหลว ให้ใช้ `tar | ssh` แทนเสมอ
*   **⚠️ SSH Multi-arg Shell Quote:** หากส่งคำสั่งที่มี pipe หรือ sub-shell ผ่าน SSH ต้องห่อเป็น single quoted string เสมอเพื่อป้องกัน remote shell ตีความพลาด: `ssh host "bash -lc \"cmd | pipe\""`
*   **⚠️ DSM Auto-Block:** Container ที่ยิง DSM API (homepage widget) ถูก auto-block IP ได้ถ้า login fail ซ้ำๆ — error code 407 ที่ homepage display เป็น "Authentication failed. 2FA enabled." จริงๆ คือ Max Tries ของ Auto Block. **Fix:** Control Panel → Security → Protection → Allow List ใส่ private subnets (`10.0.0.0/255.0.0.0`, `172.16.0.0/255.240.0.0`, `192.168.0.0/255.255.0.0`) แล้วลบ Docker IPs ออกจาก Block List

---

## 📦 Stacks & Ports Directory

| Directory | Purpose | Port (Internal / Proxy) | Critical Gotchas / Architecture |
| :--- | :--- | :--- | :--- |
| `homepage/` | Dashboard UI | 3000 / 443 | ต่อหลัง Nginx Proxy + Basic Auth. ดึง SSL จาก NAS `/usr/syno/etc/certificate/system/default/`. **Widget ห้ามใช้ HTTPS/Domain** ให้ยิงตรงไปที่ DSM HTTP `http://192.168.x.x:5000` เพื่อเลี่ยง Cert Mismatch |
| `jellyfin/` | Media Server | 8096 / — | รองรับ NVIDIA GPU Transcoding |
| `maid-tracker/` | ระบบเวลา/เงินเดือนแม่บ้าน | 5055 / — | FastAPI + SQLite (Volume `/data`). อัตรารายวัน = `เงินเดือน ÷ จำนวนวันทั้งเดือน (รวมวันหยุด — วันหยุดจ่ายด้วย)`. full month = จ่ายเต็ม, partial month/หักลา pro-rate ตาม calendar days. ลา/ชดเชยบันทึกทศนิยมได้ (`half_day`) แจ้งเตือนผ่าน LINE. **Probation mode** (`employment_status`): แม่บ้านใหม่จ่ายรายวัน (`probation_daily_rate`) ลาปิด → กดผ่านโปร set `monthly_start_date` เข้า monthly. Monthly calc anchor = `monthly_start_date or start_date`. Transition month แบ่งที่ pass date. **Slip โอนเงิน** (`payment_method=transfer`) + **เอกสาร id/passport/other** (`doc_label` กรณี other) หลายรูป เก็บ `/data/slips` `/data/documents` (ไม่อยู่ใน DB backup, nginx `client_max_body_size 25m` กัน 413). **ผู้จ่าย** (`paid_by` ฟิก/ปุ๊ก) เลือกตอน mark paid ทั้ง daily+monthly. **Daily SQLite backup ผ่าน APScheduler 03:00** → `/data/backups/maid-*.db.gz` retention 30 วัน. **Payslip CSV** ที่ `/api/employees/{id}/payslip/{year}/{month}` |
| `portainer/` | Docker Management | 9000 / — | UI สำหรับจัดการคอนเทนเนอร์ในระบบ |
| `auth/` | Centralized SSO + Password Vault | 9091 (Authelia) / 8222 (Vaultwarden) | สร้าง Docker network `auth_net` ที่ stack อื่น join. Authelia ทำ forward-auth แทน basic auth. Vaultwarden มี auth ของตัวเอง. Watchtower disabled บนทั้งสอง service |
| `uptime-kuma/`| Service Monitor | 3001 / — | ตรวจสอบสถานะการทำงานของ Services |
| `watchtower/` | Auto-update Container | — / — | มี Sidecar `watchtower-notifier` (Python 3.12-slim) อ่าน Unix Socket Log ส่ง LINE. ติดป้ายกำกับตัวเองห้ามอัปเดต: `com.centurylinklabs.watchtower.enable=false` |
| `my-secretary/`| AI Bot เลขาส่วนตัว (LINE + Telegram) | 5057 / 15057 (HTTPS)| FastAPI + Groq (`llama-3.3-70b-versatile`) + Notion Tools. มี Whitelist ID. **การเซฟลง Notion ต้องรอพิมพ์ยืนยัน "ใช่" เสมอ**. Save State ไว้ที่ `/data/state.json` |
| `hermes-agent/` | Autonomous AI Agent (Telegram + Discord) | 5063 (basic-auth Nginx dashboard) / — (gateway) | Build clones `NousResearch/hermes-agent` from GitHub (`ARG HERMES_REF`). Dashboard now sits behind `nginx:alpine` HTTP Basic Auth sidecar proxying to internal port 9119. `config.yaml` auto-generated on first run. `network_mode: host` dropped — uses bridge networking. Port 5060/5061 blocked by browsers (SIP), uses 5063. |
| `torrentwatch/` | Scraper & Filter | 5059 / 15059 (HTTPS)| FastAPI + Volume `/data`. สแกน bearbit.org ตามช่วงเวลา (19:00-01:00 รันทุก 30 นาที / 01:00-06:00 หยุด / 06:00-19:00 รันทุก 60 นาที) โหลดเข้า `/downloads` ตรง. ลบประวัติเก่าเกิน 7 วัน ทุกวัน 03:00 (+ ตอน startup เพื่อ enforce retention หลัง restart). มี Endpoint `/api/status` แบบ Public |
| `news-feed/` | AI & IT News Feed Bot + Dashboard | 5064 / — | Single container: FastAPI + APScheduler + SQLite. Summariser switchable via dashboard (Anthropic default, OpenRouter/DeepSeek option). Digest sent to LINE + Telegram at 07:00/12:00/18:00. |
| `secretary/` | Personal Knowledge Base (Notion→Qdrant RAG + n8n Automation) | 5065 (query) / 15065 · 5678 (n8n) / 15678 | Multi-service stack: qdrant, ollama, n8n, secretary-query (FastAPI), secretary-ingest (one-shot). BGE-M3 ~2GB download on first run (cached in `hf_cache` volume). Ingest subservice: `restart: "no"`, run with `docker compose run --rm secretary-ingest`. Sub-services have own `.env` at `ingest/.env` and `query/.env`. |
| `friendly-reminder/` | ระบบติดตามการผ่อนชำระรายเดือน | 5066 / — | FastAPI + SQLite (Volume `/data`) + Nginx Basic Auth. บันทึกรายการผ่อน (ชื่อ, ราคา, จำนวนงวด, เดือนเริ่มต้น) — auto-generate payment rows ตลอดอายุสัญญา. **`due_day` ต่อรายการ** (วันครบกำหนดของเดือน เช่นทุกวันที่ 25, clamp วันเกินเดือนด้วย `calendar.monthrange`). กดปุ่ม "จ่ายแล้ว" ต่องวด แจ้ง LINE เมื่อจ่าย. APScheduler ส่ง LINE reminder ทุกวันเวลา `REMINDER_TIME` (default 08:00) สำหรับงวดที่ครบกำหนด/เกินกำหนด **ยิงซ้ำทุกวันจนกว่าจ่าย** + day-before reminder 1 วันก่อน `due_day` (`DAY_BEFORE_REMINDER_TIME` default 20:00). Export CSV ผ่าน `/api/report`. **LINE webhook** `/webhook/line` (public ผ่าน DSM RP `:15066`, nginx ข้าม basic auth, app ตรวจ `X-Line-Signature`): โพสต์สลิปในกลุ่ม → แนบสลิป+mark paid อัตโนมัติ (งวดค้างเดียว=auto, หลายงวด=บอทถามชื่อ, "ค้าง"=ครบกำหนด≤เดือนนี้ & unpaid). Vault keys: `stacks.friendly_reminder.line.*` (`channel_access_token`, `channel_secret`, `group_id`). **LINE OA: Use webhook ON + Auto-reply OFF** |
| `wallpaper-scout/` | Wallpaper research/curation bot | 5067 / 15067 | FastAPI + SQLite (Volume `/data`) + Nginx Basic Auth. Topics (search query + purpose(s) + source(s) + frequency) แจ้งผ่านหน้า dashboard, ค้นรูปจากหลาย source (SFW only) ตาม preset ความละเอียด/สัดส่วน 2 แบบ (`mobile`/`pc`) เขียนไฟล์ตรงไปที่ `/volume1/homes/fixhardez/Photos/wallpapers/<purpose>/<topic>/` ให้ Synology Photos auto-index (Folders tab, ไม่ใช้ DSM Photos API). **Sources (per-topic multi-select, default `wallhaven`):** `wallhaven` (real/idol), `booru` (`app/booru.py` — yande.re + konachan.**net** Moebooru, `rating:s`; konachan.com โดน Cloudflare 403 ต้องใช้ .net + browser UA; anime/game เท่านั้น), `reddit` (idol/คนจริง — OAuth userless client_credentials, vault `stacks.wallpaper_scout.reddit.{client_id,client_secret}`; `[]` ถ้าไม่ตั้ง). Dedup ด้วย source-namespaced image id (`wh` bare, `yr:`/`kc:` booru, `rd:` reddit; `:`→`-` ใน filename). `max_new_per_cycle` = cap รวมต่อ purpose เติมตาม source order. Sort: `toplist` ครั้งแรกตอนสร้าง topic แล้วสลับเป็น `date_added` รอบถัดไป. LLM (MiMo primary / Anthropic fallback switch, reuse `shared.llm.*` vault keys) ใช้ขยาย alias คำค้นเท่านั้น (text-only, ไม่มี vision). แจ้งสรุปยอดดาวน์โหลดรายวันผ่าน Telegram (ใช้ bot/chat เดียวกับ `news-feed`) ครั้งเดียวต่อวัน. **Container `user:` ต้องตรงกับ UID/GID ของ DSM user `fixhardez`** ไม่งั้น synofoto จะไม่เห็นไฟล์ที่เขียนเข้าไป |

---

## 🚀 Release & Security Process

เมื่อใช้คำสั่ง `/release` **ให้ปฏิบัติเรียงตามลำดับอย่างเคร่งครัดก่อน Commit เสมอ:**

1. **Update Stack README:** แก้ไขฟีเจอร์/สถาปัตยกรรมของ Stack ไหน ให้เข้าไปอัปเดต `README.md` ของโฟลเดอร์นั้นทันที
2. **Update Root Docs:** หากมีการเปลี่ยนพอร์ต, เพิ่ม Stack ใหม่ หรือเพิ่ม Env Configuration ให้แก้ไข `CLAUDE.md` และ `README.md` ที่ root
3. **Atomic Commit:** รวมไฟล์เอกสารที่อัปเดตทั้งหมดเข้ากับ Commit ของซอร์สโค้ดหลักในรอบนั้นทันที (ห้ามแยก Commit เอกสารออกจากโค้ด)
4. **Security Guardrail:** ห้าม Commit `.env`, `.env.deploy`, `secrets/vault.yaml` (plaintext intermediate) หรือ Hardcode ไอพี/รหัสผ่านจริงลงในโค้ดหรือเอกสาร ให้แทนที่ด้วย Placeholder เช่น `<NAS_HOST>`, `<NAS_USER>`, `<NAS_SUDO_PASSWORD>` ทุกครั้ง — `secrets/vault.sops.yaml` commit ได้เพราะ encrypted แล้ว
5. **Vault Edits:** ใช้ `make edit-vault` (sops จัดการ encrypt/decrypt ในที่) ห้ามแก้ `vault.sops.yaml` ตรงๆ ใน editor