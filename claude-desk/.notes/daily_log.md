# claude-desk — Daily Log

## 2026-09-15 — สร้าง stack (design → scaffold → build)

**โจทย์:** ใช้ Claude Code จากมือถือโดยไม่เปิด MacBook สำหรับงาน pptx/docx/xlsx พร้อม upload/download — และ "UI modern"

**ตัดสินใจ (grill 4 รอบ):** รันบน NAS (ไม่ใช่ claude.ai/code cloud) · auth ด้วย `claude setup-token` ไม่ใช่ API key · เข้าทาง browser มือถือ · `--dangerously-skip-permissions` ในกรง container · ใส่ LibreOffice ให้ skill render slide ดูเองได้ · เปิด WAN ผ่าน DSM RP 15072 + basic auth · ไฟล์เข้า-ออกทาง DS File + drawer ในหน้าเว็บอ่าน `out/` (ไม่ส่ง Telegram) · tmux กัน session หลุด · skills clone pin sha · pin claude version · `mem_limit 2g` · nginx sidecar basic auth · ชื่อ `claude-desk` · shared folder ใหม่ `claude-work` · โครง `in/ out/` · home volume ทั้งก้อน · รันตลอด · ไม่ลบ out/ เอง · homepage tile + Kuma

**ค้นหา web terminal ที่มีปุ่ม Esc/Ctrl บนมือถือ:** ttyd ยังไม่มี (PR #1493, #1504 เปิดค้าง). ตัวเลือก: NomadTTY (nginx inject ผูก protocol), pawprint0706/ttyd-wrapper (MIT, ไฟล์ HTML เดียวส่งให้ ttyd `-I`), AgentOS (fork ไม่มี license 0 stars), 4weaver/web-terminal (Go+Ghostty สวยแต่ไม่มี auth/docker/file API). เลือก **เขียนหน้าเองต่อยอด ttyd-wrapper** — protocol ของ ttyd ง่าย (handshake JSON แล้ว `'0'+bytes` in / `'1'+JSON` resize) แต่แทนที่จะใช้ `-I` ให้ **nginx เสิร์ฟ `ui/` เองแล้ว proxy เฉพาะ `/ws` `/token`** — แยกไฟล์ได้ (js/css/fonts/vendor) ไม่ต้องอัด 1 MB ลง HTML เดียว

**UI:** slate `#0b0f19` + amber `#f59e0b`, Inter + JetBrains Mono self-host (ดึงจาก GitHub release), header glass + status dot, key bar 2 แถว (`Esc ⇧Tab Tab Ctrl ↑↓←→ ↵NL` / `Paste / ^C A− A+ ⌨`), drawer ไฟล์ขวา (icon ตามสกุล, ขนาด, เวลา), PWA manifest + apple-touch-icon (สร้างจาก SVG ด้วย `qlmanage -t -s 180`). Ctrl = one-shot sticky, ↵NL = `ESC CR` (Alt+Enter ที่ Claude Code รับเป็นขึ้นบรรทัด). ตัด Ctrl+D ออกกันกดพลาด logout. ⌨ ตัวอักษรเป็น tofu ใน headless → เปลี่ยนเป็น SVG.

**Mockup:** Chrome extension ไม่ต่อ → ใช้ `Google Chrome --headless=new --screenshot`. **Headless บน Mac clamp ความกว้างขั้นต่ำ ~500 px** — รูป 390 px ออกมาโดน crop ขวา (header "liv", ปุ่ม → หาย) ตอนแรกนึกว่า layout ล้น แก้ `min-width:0`/`overflow:hidden` ไปแล้วรูปยังเหมือนเดิมเป๊ะ (ไฟล์ขนาดเท่ากัน) ถึงรู้ว่าเป็น artifact; ถ่าย 500 px แล้วครบทุกปุ่ม. รูปเก็บที่ `screenshots/claude-desk-{phone,files,desktop}.png`

**อิมเมจ:** debian bookworm-slim, node 22 ก๊อปจาก image ทางการ, ttyd 1.7.7 sha256 `8a217c…4f55`, claude 2.1.272 (ตรงกับบน Mac), skills `anthropics/skills@34040c9` (2026-09-10). deps อ่านจาก SKILL.md/scripts จริง: LibreOffice `*-nogui` (bookworm มี), poppler-utils, qpdf, npm `pptxgenjs docx react-icons react react-dom sharp`, pip `python-pptx python-docx openpyxl pandas pillow pypdf pdfplumber reportlab pdf2image defusedxml lxml markitdown[...]`. RUN สุดท้าย assert ทั้งหมดตอน build.

**Vault:** `sops set` ใส่ `stacks.claude_desk.{oauth_token,dashboard.*}` (token เป็น placeholder — ต้องรอผู้ใช้รัน `claude setup-token`) → `make sync-test-vault` → `make secrets` → `make check` exit 0 → `.htpasswd` (user `desk`). pytest 39 passed (ข้าม `test_manifest_schema.py` เพราะ venv ไม่มี `jsonschema` — ปัญหาเครื่อง ไม่ใช่โค้ด).

**Deploy:** เพิ่ม `claude-desk` ใน `ALL_STACKS`, upload ด้วย `deploy.sh -y` (ไม่ `-s`) เพราะ **`/volume2/claude-work` ยังไม่มี** — ถ้า `up` ตอนนี้ docker จะสร้าง dir root เปล่าๆ แล้ว DSM สร้าง share ชื่อนี้ไม่ได้อีก. build อิมเมจแยกด้วย `nohup docker compose build` log ที่ `/tmp/claude-desk-build.log` บน NAS.

**ค้างฝั่งผู้ใช้:** (1) สร้าง shared folder `claude-work` ใน DSM (2) `claude setup-token` แล้วบอกให้ใส่ vault (3) DSM RP `15072 → localhost:5072` เปิด WebSocket

**เอกสาร:** README stack + `.notes` นี้ + row ใน root `CLAUDE.md`/`README.md` + tile homepage (ไม่ ping)

**ย้าย share ไป volume2:** ผู้ใช้สร้าง `claude-work` บน **volume2 (SSD)** แทน volume1 เพราะไม่อยากให้ soffice/pptx render เขียนหนักบน HDD ก้อนใหญ่ — แก้ `CLAUDE_WORK_DIR` literal + docs, `make secrets` ใหม่. share มาเป็น `0777+ACL` owner root → uid 1000 ในคอนเทนเนอร์เขียนได้เลย ไม่ต้อง chown.

**Build ครั้งแรกพัง** ที่ RUN assert: `Cannot find module 'pptxgenjs'` — npm global ไม่อยู่บน require path และ `ENV NODE_PATH` ผมวางไว้ท้ายไฟล์หลัง assert → ย้าย `ENV NODE_PATH=/usr/local/lib/node_modules` ขึ้นมาก่อน assert (runtime ก็ต้องการเหมือนกัน เพราะ skill ทำ `require('pptxgenjs')` เปล่าๆ จาก /work)

**Deploy รอบแรก:** nginx bind `${CLAUDE_WORK_DIR}/out` ล้ม (`does not exist`) เพราะ entrypoint ที่ mkdir กับ nginx start พร้อมกัน → mount ทั้ง share เข้า nginx แล้ว `alias /files/out/` แทน. จากนั้น desk container restart loop `mkdir: cannot create directory '/work': Permission denied` — mount ถูกต้อง (`docker inspect` เห็น `/volume2/claude-work -> /work`) แต่ **Synology ACL** ของ share ใหม่มีแค่ `group:administrators` + user เดียว, mode `777+` ไม่มีความหมาย → probe ด้วย `docker run -u 1000:1000` และ `-u 1026:100` (เจ้าของ share เอง) ล้มทั้งคู่ เพราะใน container ไม่มี supplementary gid 101. แก้ด้วย `synoacltool -add ... group:users:allow:rwxpdDaARWc--:fd--` (ต้องใช้ `sudo -S` กับ password ไม่ใช่ `sudo -n`) แล้ว probe `1000:100` ผ่าน → image `useradd -g 100`, compose `user: 1000:100`.

**รอบ 3 — ACL อีกที่:** container ขึ้นแล้ว, 401/ws 101/`/files/` JSON ผ่าน แต่ `/` และ static ทุกไฟล์ **403** และ `/opt/claude-desk/work/` `Permission denied` ใน desk — สาเหตุเดียวกับ share: **dir ใต้ `/volume2/docker/claude-desk` มี ACL ของ share `docker`** nginx worker (uid 101) กับ uid 1000 traverse ไม่ได้; stack อื่นรอดเพราะ bind แค่ไฟล์ (`nginx.conf`, `.htpasswd`) ที่ master อ่านเป็น root. แก้แบบไม่พึ่ง ACL: `nginx/Dockerfile` (`FROM nginx:alpine` + `COPY ui/`) และ `COPY work/CLAUDE.md` เข้า desk image, ตัด bind `./ui` `./work` ออก, เพิ่ม `.dockerignore` กัน `.env`/`.htpasswd` เข้า context.

**รอบ 4 — โหมดไฟล์ 0700:** static ยัง 403 หลัง bake เข้า image เพราะ `tar|ssh` ส่งไฟล์มาเป็น `0700` แล้ว `COPY` เก็บ mode เดิม worker uid 101 อ่านไม่ได้ → `RUN chmod -R a+rX` ใน `nginx/Dockerfile`. อาการเดียวกันโดน `/etc/tmux.conf` เงียบๆ (tmux ไม่บ่น แค่ไม่อ่าน: status bar โผล่, escape-time 500) → `COPY --chmod=0644`. `PS1` จาก profile.d โดน `~/.bashrc` (skel) ทับ → entrypoint append ลง `~/.bashrc` ครั้งเดียว.

**ยืนยันบน NAS:** 401 ไม่มี auth / static 200 ครบ / `/token` / `/files/` JSON / ws 101 ผ่าน nginx เรา / raw ws client ส่ง handshake+input → tmux `main` เกิด แบนเนอร์ขึ้น shell อยู่ `/work` / `claude -p "reply DESK_OK"` ใน container ตอบ `DESK_OK` = token ใช้ได้. ผ่าน DSM RP 15072: `/` 200, `/token` 200, `/files/` OK แต่ **`/ws` = 404 หน้า DSM** — อ่าน `server.ReverseProxy.conf` แล้ว block 15072 **ไม่มี `Upgrade`/`Connection` header** = ยังไม่ได้เพิ่ม WebSocket ใน tab Custom Header ของ rule (ไม่ใช่ checkbox หน้าแรก). `proxy_read_timeout 60` ของ DSM มี `-P 30` ของ ttyd คุมอยู่.
