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

**rtk + headroom:** ผู้ใช้ถามว่า integrate ได้ไหม. **rtk ใส่แล้ว** — Linux musl binary v0.49.0 (sha256 `727823…0c8f`) ลงใน image, hook `PreToolUse Bash → rtk hook claude` เก็บเป็น `claude-settings.json` แล้ว entrypoint merge เข้า `~/.claude/settings.json` ใน home volume แบบ additive (key ด้วย command string ไม่ทับค่าที่ตั้งจากในเครื่อง). **Headroom ไม่ใส่** (ผู้ใช้เลือกข้อ 1): มันคือ `headroom-ai` PyPI (Mac 0.28.0 / ล่าสุด 0.37.0) ทำงานเป็น HTTP proxy `ANTHROPIC_BASE_URL=:8787` + MCP + memory DB, install บน Mac 2.0 GB (onnx/ML) — ถ้าจะทำต้องเป็น sidecar `headroom proxy --host 0.0.0.0` extra `[proxy]` เท่านั้น `mem_limit 512m` และเทสต์ OAuth ผ่าน proxy บน Linux ก่อน.

**Upload/download ใน UI:** ผู้ใช้ขอ in = กดแอดจากหน้าเว็บ, out = กดโหลด. out มีอยู่แล้ว (tap เปิด) เพิ่มปุ่ม ⬇ (`<a download>`) ให้ชัด. in ต้องมีตัวรับเขียน — nginx:alpine ไม่มี upload module → `upload.py` (stdlib, ~90 บรรทัด) รันข้าง ttyd ใน desk container เพราะมันถือ `/work` อยู่แล้วและมี python3 อยู่แล้ว; entrypoint spawn ในลูป `while true` ให้เกิดใหม่ถ้าตาย, ttyd ยังเป็น PID 1. Browser ยิง `PUT upload/<name>` body = ไฟล์ตรงๆ (XHR เพราะ fetch ไม่มี upload progress), เขียน `.part` แล้ว `os.replace` กันไฟล์ครึ่งเดียวโผล่ใน `in/` ให้ Claude อ่านผิด. ชื่อไฟล์: basename เท่านั้น ห้าม `..`/`/`/dot-file. nginx `client_max_body_size 300m` + `proxy_request_buffering off`. drawer แยก tab `in/` (Add files, 🗑) / `out/` (tap, ⬇). Verify บน NAS: PUT 3 MB → `cmp` byte-identical, `..%2Fetc%2Fx` → 400, `/files/` root → 404, list/GET/DELETE ผ่าน.

## 2026-09-15 (ต่อ) — ธีม dark/light

**โจทย์:** ผู้ใช้ขอสลับ dark/light ได้จาก UI. เลือก **toggle 2 สถานะ (sun/moon)** ไม่ใช่ 3 สถานะ auto/dark/light — ได้พฤติกรรม auto ฟรีโดยไม่ต้องมีไอคอนที่สาม: `localStorage` ว่าง = ตามเครื่องและ**ตามต่อเนื่อง** (`matchMedia('(prefers-color-scheme: light)')` + listener), กดครั้งแรก = ปักหมุดถาวร.

**โครง:** `app.js` เขียน `data-theme` ที่ `<html>` เสมอ → CSS ไม่ต้องมี `@media (prefers-color-scheme)` และไม่ต้องก๊อป palette สองรอบ. inline script ใน `<head>` **ก่อน** `<link rel=stylesheet>` ตั้ง attribute ให้ก่อน paint (ไม่งั้นเครื่องที่ตั้ง light จะแฟลชดำ). ย้ายสี hardcode ทุกตัวใน `style.css` เข้า palette (`--glow`, `--scrim`, `--shadow-drawer`, `--ring-*`, `--accent-hi/-line/-press`, `--ico-*`) — เช็คด้วยการ strip บล็อก palette แล้ว grep หา `#hex|rgba(` ต้องไม่เหลือ. ไอคอนไฟล์ใช้ `color-mix()` ผสมจาก hue เดียวต่อสกุล (เบราว์เซอร์ที่ไม่รู้จัก = ทิ้ง declaration เหลือพื้น `--btn` ยังอ่านออก ไม่หาย).

**⚠️ xterm ไม่ได้อ่าน CSS** มี palette ของตัวเอง → ตาราง `THEMES` ใน `app.js` และ **ต้อง `term.refresh(0, term.rows-1)` หลังตั้ง `term.options.theme`** ไม่งั้นแถวที่วาดไปแล้วค้างสีเดิม (ตัวหนังสือเข้มบนพื้นเข้ม = หายทั้งจอ). พิสูจน์ด้วย probe: ก๊อป `ui/` ไป scratchpad ใส่สคริปต์กด `#theme-btn` ที่ 1200ms แล้ว screenshot — ข้อความที่พิมพ์ตอนธีมเก่ายังอ่านออกหลังสลับ = repaint ทำงาน.

**ธีม light กลับด้าน ANSI:** `brightWhite` ต้องเป็นสี**เข้มที่สุด** (โปรแกรมใช้ bright เป็นตัวเน้น `#fff` บนขาว = มองไม่เห็น), accent ลงจาก amber-500 เป็น amber-700 เพราะ #f59e0b contrast ไม่ผ่านบนขาว.

**⚠️ headless Chrome รายงาน `prefers-color-scheme: light`** — ภาพ "dark" ที่ถ่ายใหม่ออกมาสว่างหมดจนกว่าจะใส่ `?theme=dark`. เจอตอน probe (log บอก `before=light` ทั้งที่คิดว่า default ดำ).

**ค้าง/ยังไม่ทำ:** (1) `apple-mobile-web-app-status-bar-style` ยังเป็น `black-translucent` — ใน PWA standalone โหมด light ตัวหนังสือ status bar อาจเป็นสีขาวบนพื้นสว่าง แก้ทีหลังไม่ได้ด้วย JS (iOS อ่านตอน launch) และเปลี่ยนเป็น `default` จะทำให้ `safe-area-inset-top` = 0 layout ขยับ — **รอผู้ใช้ยืนยันจากมือถือจริงก่อนค่อยแก้**. (2) สีที่ส่งมาเป็น 256-palette (`\e[38;5;214m` ใน `profile.sh`, output บางส่วนของ Claude Code) ไม่ได้อยู่ใน palette ไหน เหมือนกันทั้งสองธีม. (3) `manifest.webmanifest` `theme_color`/`background_color` ยังเป็นสีมืดค่าเดียว (ใช้ตอน launch splash เท่านั้น).

**ยังไม่ deploy** — ผู้ใช้กำลังเทสต์อยู่ ห้าม restart container. `ui/` ถูก bake เข้า nginx image แล้ว ต้อง rebuild ถึงจะเห็นบนมือถือ.

## 2026-09-15 (ต่อ) — ปุ่ม Clear in/ out

**โจทย์:** ผู้ใช้ขอปุ่มเคลียร์ไฟล์ทั้งโฟลเดอร์ทั้ง in และ out จากหน้าเว็บ

**API เปลี่ยนรูป:** `upload.py` เดิมผูกกับ `/work/in` อย่างเดียว (`PUT /upload/<name>`) → เป็น `/upload/<dir>/[name]` โดย `dir` allowlist แค่ `in`/`out` (ห้ามถึง share root ที่มี `#recycle`/`@eaDir`). `PUT` ลง `out/` ตอบ 403 (out เป็นของ Claude อัปทับไม่มีความหมาย). `DELETE` ไม่มีชื่อ = เคลียร์ทั้งโฟลเดอร์ ตอบจำนวนที่ลบกลับมาเป็น text. เคลียร์ใช้ `os.scandir` ลบเฉพาะ `is_file(follow_symlinks=False)` ชั้นบนสุด ข้ามชื่อขึ้นต้นจุด → `@eaDir` กับโฟลเดอร์ที่ Claude จัดไว้รอด.

**⚠️ ด่าน traversal เดิมไม่เคยถูกทดสอบจริง** — เทสต์รอบก่อนที่ได้ `405` คือ **nginx** decode `%2F` แล้ว resolve `..` ก่อน match location ทำให้ `/upload/..%2Fetc%2Fx` กลายเป็น `/etc/x` ตกไป `location /` (405) **ไม่เคยถึง `upload.py`**. รอบนี้เพิ่ม path segment = parsing surface ใหม่ เลยเปลี่ยนวิธี: **split raw path ด้วย `/` ก่อน บังคับ 4 ส่วนพอดี แล้วค่อย unquote ทีละส่วน** (encoded separator จึงตกด่านที่ regex ไม่ใช่กลายเป็น step). เพิ่ม `WORK_DIR` env (default `/work`) เพื่อรันทดสอบนอกคอนเทนเนอร์ได้ → รันบน Mac ยิงตรง 7682 ผ่าน **13 เคส**: put in 201 / put out 403 / `..%2F` 400 / `..%5C` 400 / dotfile 400 / `in/sub/x` 404 / `etc/x` 404 / `../x` 404 / delete missing 404 / delete one 204 / clear in = 2 / clear out = 1 / clear ซ้ำ = 0, และยืนยันว่า `.hidden` กับ `@eaDir/keep` รอด ไม่มีอะไรหลุดออกนอก `in`/`out`.

**UI:** ปุ่มอยู่ใน footer ของ drawer (ไกลจากปุ่มรายไฟล์ กันกดพลาด) label ตาม tab. **กด 2 ครั้ง**: ครั้งแรกติดอาวุธเป็นสีแดง "Delete N files for good?" หมดเวลาเอง 4 วิ, ครั้งที่สองลบจริงแล้วโชว์ "Cleared N files" 2 วิ. ใช้ two-tap แทน `confirm()` เพราะ modal บล็อกทั้งหน้าและเทสต์ด้วย headless ไม่ได้.

**⚠️ `[hidden]` ไม่มีผลถ้า CSS ตั้ง `display` ให้** — `.clear-btn { display: inline-flex }` ชนะ UA rule `[hidden] { display: none }` ปุ่มเลยยังโผล่ตอนโฟลเดอร์ว่าง (เห็นจาก screenshot หลังเคลียร์). แก้ด้วย `.clear-btn[hidden] { display: none }` ยืนยันด้วย probe: `visible=false hidden=true`.

**ยังไม่ deploy** (ผู้ใช้สั่งไม่ให้ restart) — `upload.py` อยู่ใน desk image, `ui/` อยู่ใน nginx image ต้อง rebuild ทั้งคู่ถึงจะใช้ได้จริง ตอนนี้ของบน NAS ยังเป็น API เดิม `/upload/<name>`.

## 2026-09-15 — ยก status line ของ workstation มาใส่เดสก์

**โจทย์:** เอา `statusLine` ใน `~/.claude/settings.json` (สคริปต์ `~/.claude/statusline-script.sh`) มาใช้ใน stack นี้ด้วย

**vendor ไม่ใช่ mount:** ก๊อปเป็น `claude-desk/statusline.sh` ในโปรเจกต์ **ตัดสองก้อนทิ้ง** — Jira segment (ต้องมี cred + `jira-status-fetch.py` ที่ไม่ได้ส่งมาด้วย แถม `stat -f %m` เป็นของ macOS Linux ต้อง `stat -c %Y`) และ `dwidth()` ที่ไม่มีใครเรียก (เป็นที่เดียวที่ใช้ perl) เหลือ dep แค่ `bash jq awk git` ซึ่งอิมเมจมีครบอยู่แล้ว (`jq` มาจาก Dockerfile บรรทัด apt เดิม)

**ห้ามวางใน `/home/claude`:** เป็น named volume `claude_desk_home` — docker seed volume จากอิมเมจ**เฉพาะตอน volume ว่าง** deploy ที่มีอยู่แล้วจะไม่เห็นไฟล์เลย (เงียบสนิท ไม่ error). วางที่ `/opt/claude-desk/statusline.sh` แล้วให้ `claude-settings.json` ชี้ path นั้น — merge ตัวเดิมใน entrypoint ติดตั้งคีย์ `statusLine` ให้พร้อมกับ hook ของ rtk. เพิ่มเงื่อนไขข้ามคีย์ที่ขึ้นต้นด้วย `_` ในลูป merge เพื่อเขียนคอมเมนต์ในไฟล์ JSON ได้ (JSON ไม่มีคอมเมนต์) โดยไม่หลุดลง settings จริง

**merge เป็น one-way — จำไว้:** `cur.setdefault(k, v)` แปลว่าคีย์ลงครั้งเดียว แก้ template ทีหลังไม่ไปถึงเดสก์ที่มีคีย์นั้นแล้ว (hook ไม่เป็นเพราะ key ด้วย command string) → ตัวสคริปต์จึงต้องอยู่ในอิมเมจ ส่วนคีย์ใน settings เป็นแค่ path นิ่งๆ

**จอมือถือแคบเกินกว่าจะย่อบาร์อย่างเดียว:** วัดจริง — แถว 5h เต็มรูปแบบ 79 คอลัมน์, หางที่ตายตัว `(bud 61%, -19% → 69%) ✓  ↻ 1h59m` กินไป ~31 คอลัมน์ ไม่ว่าบาร์จะสั้นแค่ไหน (W=10 ยังได้ 53) ส่วนมือถือ 390px ที่ JetBrains Mono 13px ได้ ~47 คอลัมน์ → **ย่อบาร์อย่างเดียวไม่มีทางพอ ต้องตัดหาง**. ทำเป็นโหมด compact ขับด้วยตัวแปรเดิม (`STATUSLINE_BAR_W` < 20 = ทิ้งบาร์ + ทิ้ง budget breakdown เหลือ `42% → 69% ✓ ↻1h56m` = 24 คอลัมน์) ไม่เพิ่ม env ตัวที่สอง. ตั้ง `STATUSLINE_BAR_W=0` ใน compose แบบ**ค่าตรงๆ ไม่ใช่ `${...}`** จะได้ไม่ลาก `secrets.manifest.yaml` + `make secrets` เข้ามาทั้งที่ไม่ใช่ secret

**ที่ 36 เอาต์พุตเท่าเดิมเป๊ะ** — `diff` กับสคริปต์ workstation ผ่าน byte-identical เพื่อให้ก๊อปรุ่นใหม่มาทีหลัง diff สะอาด

**ยังไม่ได้ยืนยัน:** ตัวเลขคอลัมน์ของมือถือจริง (ยังติดด่าน DSM RP WebSocket ตาม 00_INDEX) — headless Chrome บนแมคบีบความกว้างขั้นต่ำ ~500px `term.cols` จะรายงาน ~64 แล้วหลอกว่าพอดี เลยเลือกเลขจาก worst case ไปก่อน

**แก้รอบเดียวกัน — ฟิกความกว้างเป็น env ผิดตั้งแต่แรก:** ลองใช้จริงบนจอกว้างแล้วหลอดหายหมด เพราะ `STATUSLINE_BAR_W=0` ที่ฟิกไว้ใน compose มันคือค่าตายตัวต่อคอนเทนเนอร์ แต่เดสก์ตัวเดียวถูกเปิดทั้งจากมือถือและแล็ปท็อป. **doc ทางการบอกไว้ตรงๆ** ([statusline](https://code.claude.com/docs/en/statusline)): Claude Code จับเอาต์พุตของสคริปต์แทนที่จะต่อ terminal ให้ → `tput cols`/`stty` มองไม่เห็นอะไรเลย **แต่มัน export `COLUMNS`/`LINES` ให้ก่อนรันทุกครั้ง** → เปลี่ยนไปคำนวณ layout จาก `COLUMNS` ทุกรอบ (bar = cols − 43 เพดาน 36, ต่ำกว่า 8 = โหมด phone) ถอด env ออกจาก compose เหลือไว้เป็น override อย่างเดียว. วัดแล้ว: 47 คอลัมน์ → compact 24, 60 → พอดี 60, ≥80 → 79 เต็ม, ไม่มี `COLUMNS` → เหมือนสคริปต์ workstation เป๊ะ

**ยืนยัน `COLUMNS` ถึงสคริปต์จริง (ไม่ใช่เชื่อ doc อย่างเดียว):** วิธีที่ใช้ได้ผลคือรัน claude อีกตัวใน container ด้วย `HOME` แยก (`/tmp/slprobe`) ตั้ง `statusLine` เป็นสคริปต์ dump env+stdin แล้วเปิดใน tmux pane บังคับ `-x 47` — ได้ `COLUMNS=47 LINES=30` และเห็นคีย์ stdin ทั้งหมด **ไม่มีฟิลด์ความกว้างเลย** (`context_window cost cwd effort exceeds_200k_tokens fast_mode model output_style scratchpad_dir session_id thinking transcript_path version workspace`) = `COLUMNS` เป็นทางเดียวจริง. กว่าจะ probe ได้ต้องใส่ `hasCompletedOnboarding` + `bypassPermissionsModeAccepted` + project ที่ trust แล้วใน `$HOME/.claude.json` ไม่งั้น claude ตายที่หน้า prompt ก่อนจะ render (ครั้งแรก Enter ไปโดน "No, exit" ของหน้า Bypass Permissions)

**แถวเตือนกว้างกว่าแถวปกติ ~12 คอลัมน์:** ตอน `hit=1` หางมี ` ⚠ wall -17m` เพิ่ม ทำให้แถวยาว 87 ทั้งที่บาร์คิดจากหางปกติ → ล้นช่วง 80–91 คอลัมน์ (จอกลางๆ). ไม่ลดบาร์ทั้งกระดานเพราะเป็นเคสส่วนน้อย — ตัดเฉพาะ `wall` เมื่อที่ไม่พอ (`WALL_ROOM`) ⚠ กับตัวเลขคาดการณ์ยังอยู่ครบ. วัดหลังแก้: 80→77, 91→87, 47→23 ไม่ล้นสักค่า
