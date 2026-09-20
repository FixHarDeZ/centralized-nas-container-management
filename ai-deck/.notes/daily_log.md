## 2026-09-20 — Editable starter prompts

- Added **Edit prompt** to all three welcome cards. Save per-card templates in `localStorage` (`ai-deck.starter-prompts.v1`), shared by Claude/Codex in this browser. No cross-device sync. Selecting a card fills the composer; never sends automatically.
- Accessible modal supports Save, Cancel/Escape and Restore default (save to apply). Rejects blank/oversized prompts; storage failure keeps edits visible. Prompt text stays literal, existing composer draft is preserved while editing.
- Verification: 144 stack tests passed; browser checks cover persistence across reload/provider change, cancel/reset, storage failure, literal text and mobile layout. JavaScript syntax/diff checks and nginx image build passed; desktop/mobile screenshots inspected. Independent review found no concrete correctness issues.
- No deployment. Git delivery follows this entry; unrelated `secrets/vault.sops.yaml` remains excluded.

# claude-desk — Daily Log

## 2026-09-18 — skills ของ workstation ขึ้นเดสก์ (allowlist + bind mount)

**โจทย์:** อยากให้เดสก์มี skill ชุดเดียวกับที่ใช้บน workstation และอัปเดตตามได้เรื่อยๆ

**ที่เลือก: allowlist + bind mount ไม่ใช่ mirror และไม่ bake ลงอิมเมจ**

- `claude-desk/skills.list` (31 ชื่อ) → `make desk-skills` (`scripts/desk_skills.py`) ก๊อปจาก `~/.claude/skills` deref symlink ไป `~/.agents/skills` ลง `claude-desk/skills/` → `COPY skills/ /opt/user-skills/` (layer สุดท้ายใน Dockerfile) → `entrypoint.sh` symlink ทุก dir ที่มี `SKILL.md` เข้า `~/.claude/skills`
- **ลอง bind ก่อนแล้วไม่ได้ผล (วัดบนเครื่องจริง)**: `./skills:/opt/user-skills:ro` ขึ้น mount ปกติ ไฟล์อยู่ครบที่ `/volume2/docker/claude-desk/skills` (31 dir) แต่ในคอนเทนเนอร์ `stat` = `700` owner uid 1026 → `ls: cannot open directory '/opt/user-skills': Permission denied` = DSM share ACL เหมือนเคสของ `ui/` กับ `work/CLAUDE.md` และ **`sudo chmod -R a+rX` ที่ NAS ไม่ติด** (ACL ชนะ) — โหมดอ่านกลับมาเป็น 700 เหมือนเดิม. โทษของ bug นี้คือ**เงียบสนิท**: deploy เขียวหมด mount มีจริง แต่ agent ไม่เห็น skill สักอัน
- เลย COPY แทน — แพงกว่านิดเดียวเพราะวางเป็น layer สุดท้ายก่อน sanity check (apt/npm/pip/clone cached หมด ~1 นาที) และ deploy recreate container ให้ลูป symlink รันใหม่อยู่แล้ว

**ทำไมไม่ก๊อปทั้งโฟลเดอร์ (ข้อสำคัญที่สุด):** `~/.claude/skills/notebooklm/` = 196 MB มี `data/auth_info.json` + `browser_state/browser_profile/` (session Google ที่ล็อกอินค้าง) + venv patchright — ก๊อปทั้งดุ้น = เอา credential จริงขึ้น repo public. สคริปต์เลย **ปฏิเสธทั้ง skill** เมื่อเจอไฟล์ทรง credential (`auth_info`, `credentials`, `cookies`, `.env`, `id_ed25519`, `keys.txt`) ไม่ใช่กรองไฟล์นั้นทิ้งแล้วส่งที่เหลือ — "กรองความลับให้แล้ว" เป็นนิสัยที่แย่กว่า "อันนี้ไม่ต้องเดินทาง". `tests/test_skills.py` เช็คสำเนาซ้ำอีกชั้น (กันคนแปะไฟล์เข้ามาเองทีหลัง)

**ตัดออกด้วยเหตุผลอื่น:** skill ที่ขับเบราว์เซอร์ (ไม่มี display server/Chrome), skill ที่ต้องใช้ age key / NAS SSH key (กรงนี้ตั้งใจไม่ให้มี), สาย coding (เดสก์ไม่ใช่ที่เขียนโค้ด), `synced/` (ซ้ำกับ `/opt/skills`), skill จาก plugin (คนละกลไก อยู่ `~/.claude/plugins`)

**prune:** `test/ benchmarks/ node_modules/ .venv/ data/ browser_state/ generated/` + `*.png *.zip` + `examples/*.html` — archify 7 MB → 550 KB (ตัวอย่างที่ render แล้ว 4 ไฟล์ ~700 KB/ไฟล์ = 5 ใน 6 ของน้ำหนัก ส่วน spec JSON ที่ instruction สั่งให้อ่านยังอยู่ครบ) ยืนยันว่าสำเนาใช้ได้ด้วย `node skills/archify/bin/archify.mjs doctor` = ready

**กับดักที่ดักไว้:** `ln -sfn` ลงชื่อที่เป็น **directory จริง** (เช่นใช้ skill-creator สร้างบนเดสก์ชื่อชน) จะวาง symlink **ไว้ข้างใน** ไม่ใช่ทับ — `-n` กันได้แค่เคส symlink→dir. entrypoint เลยข้ามพร้อม log, และล้าง symlink ที่ชี้ `/opt/user-skills/*` แบบค้าง (ชื่อที่ถอดออกจาก list) ทุกครั้งที่ start

**ข้อจำกัดที่ยอมรับ:** `archify visual-check` บนเดสก์ใช้ไม่ได้ — มันหา binary chrome ของระบบ (ไม่ได้ bundle puppeteer) อิมเมจไม่มี; `validate`/`deliver` ใช้ได้ปกติ. อยากได้ต้องใส่ chromium ~300 MB

**ผล:** 31 skills, 162 ไฟล์, 2.6 MB, เทสต์ `tests/test_skills.py` 4 ตัวผ่าน

**chromium: ตัดสินใจยังไม่ใส่ (18/09)** — `archify visual-check` ไม่ได้ต้องการ "จอ" มันสั่ง `--headless=new --remote-debugging-pipe --disable-gpu` แล้วคุย CDP ทาง pipe (`bin/visual-check.mjs:249`) ไม่แตะ X11 เลย; ที่ล้มบนเดสก์คือ**หา binary ไม่เจอ** (`google-chrome`/`chromium`/`chromium-browser`). ถ้าจะใส่รอบหน้ามี 3 ด่าน:

1. **sandbox** — โค้ดเติม `--no-sandbox` ให้เฉพาะตอนเป็น root หรือมี env `ARCHIFY_CHROME_NO_SANDBOX=1`; เดสก์เป็น uid 1000 และ DSM kernel มักปิด unprivileged userns (เครื่องเดียวกับที่ไม่มี CFS bandwidth ให้ `cpus:`) → ตั้ง env ตัวนี้ใน compose
2. **`/dev/shm` 64 MB default ของ docker** — headless Chrome ตายเงียบตรงนี้ และ args ชุดนี้ **ไม่มี** `--disable-dev-shm-usage` → ต้อง `shm_size: 512m` ที่ service
3. **ขนาด/หน่วยความจำ** — chromium + deps ~400 MB บนอิมเมจที่มี LibreOffice แล้ว และต้องแบ่งจาก `mem_limit: 3g` ตอน render (host เคย OOM 2 ครั้ง)

เหตุผลที่รอ: `deliver` บนเดสก์ผ่าน 9 artifact checks + composition showcase อยู่แล้ว ที่ขาดคือหลักฐาน containment/readability ในเบราว์เซอร์จริง + screenshot ซึ่งงานจากมือถือส่วนใหญ่ไม่ต้องใช้

## 2026-09-18 — สองคนสองโต๊ะ (แก้ reconnect รัวๆ)

**อาการ:** แฟนเปิดใช้อยู่ก่อน แล้วเราเข้าด้วย basic auth user ของตัวเอง → หน้าเว็บขึ้น `reconnecting` วนไม่หยุด ใช้ไม่ได้เลย

**เหตุ:** `ttyd -m 1` — `--max-clients` เป็นของ ttyd **แต่ละ instance** คนที่สองโดนปฏิเสธ websocket, `ui/app.js:181` `onclose` → `scheduleReconnect()` backoff ถึง 10 วิ วนตลอด. สัญญาณมีที่เดียวคือ log ของคอนเทนเนอร์:

```
W: refuse to serve WS client due to the --max-clients option.
tmux list-clients -t main → /dev/pts/0: main [178x30] (attached)
```

**และ "ให้อีกคนปิดแท็บ" ไม่ใช่ทางแก้** — แท็บ iOS ที่ปิดจอทิ้งไว้ยังถือ slot เพราะเบราว์เซอร์ตอบ ws ping ที่ชั้น network เอง ไม่ต้องปลุกหน้าเว็บ (`-P 30` เลยไม่เก็บกวาด และ `proxy_read_timeout 86400s` ก็ไม่ตัด)

**ทำ:** ttyd ตัวละคน คนละพอร์ต คนละ tmux session
- roster = `DESK_USERS=fixhardez:7681,Pookzii:7684` ใน compose, `entrypoint.sh` spawn ตาม (ตัวแรก = PID 1, ที่เหลือมี respawn loop เหมือน upload.py/chat.py)
- `nginx.conf` `map $remote_user $desk_port` + **`resolver 127.0.0.11`** (ตัวแปรใน `proxy_pass` = resolve ตอน request ไม่ใช่ตอน start ไม่มี resolver = 502 ทุกครั้ง)
- map คือ**สำเนาที่สองของ roster** (nginx อ่าน env ไม่ได้) → `tests/test_desks.py` แดงถ้า drift — เพราะ drift = 502 ของคนเดียว ไม่ใช่ของทั้งสแตก
- **`/api/` ต้อง route ตามคนด้วย** ไม่ใช่แค่ `/ws`: ทุก endpoint ที่นั่นพิมพ์ลง pane — nginx เขียนทับ `X-Desk-User` ด้วย `$remote_user` (`proxy_set_header` ชนะ header ที่เบราว์เซอร์ส่งเอง) แล้ว `upload.py:target_for()` map เป็น tmux target ไม่งั้น **ปุ่ม Quit ของคนหนึ่งยิง Escape+`/exit` เข้าเทิร์นที่อีกคนรันอยู่** ซึ่งแย่กว่าบั๊กเดิม
- `-m 2` ต่อโต๊ะ (คนเดียวกันเปิดมือถือ+แล็ปท็อป, แท็บค้างไม่ล็อกตัวเองออก) + `window-size latest` ใน `tmux.conf` — default ของ tmux ย่อจอตาม client ที่**เล็กสุด** มือถือ ~40 คอลัมน์จะบีบแล็ปท็อป แล้ว `statusline.sh` เด้งเข้าโหมดมือถือบนจอกว้าง (เหตุผลเดียวกับที่ห้ามฟิก `STATUSLINE_BAR_W`)
- `mem_limit` 2g → **3g**: สอง Claude Code TUI + child ของ chat.py + soffice; host เหลือว่าง ~4.3 GB (วัดตอนแก้) cap ยังทำหน้าที่เดิมคือให้คอนเทนเนอร์ตายก่อนเครื่อง

**ยังแชร์กันตั้งใจ** (เขียนไว้ใน README หัวข้อ "Two people, two desks" ไม่ใช่โต๊ะส่วนตัวจริง): chat view (chat.py process เดียว agent เดียว session_id เดียว — stop ของคนหนึ่งตัดเทิร์นอีกคน), quota chip + noti จบเทิร์น (`desk-status.json`/`desk-done.json` ไฟล์เดียวใน home volume เดียว), sessions sheet (`~/.claude/projects/-work/` ที่เดียว), `/work`

**verify หลัง deploy:** ttyd ฟังทั้ง 7681/7684, `nginx -t` ผ่าน, แฟนที่เปิดค้างอยู่เด้งเข้า tmux `pookzii` ทันทีจริง (`tmux ls`), ยิง `/api/sessions` ในคอนเทนเนอร์ด้วย header 3 แบบ → `Pookzii`=pane bash, `fixhardez`=None (ยังไม่มีใคร attach), `nobody`=None (ตกไปโต๊ะ default ถูกต้อง). เทสต์ 96 + 6 ใหม่ ผ่านหมด

## 2026-09-16 (ดึกมาก) — cost/token ต่อเทิร์น + history ใช้กับหน้าแชทได้

**อาการที่แจ้ง:** กด history แล้วแชทเดิมกลับมาใน**หน้าเทอร์มินัล** แต่ใน**หน้าแชทไม่กลับมา** — เพราะ sheet ยิง `/api/resume` ที่พิมพ์ลง tmux อย่างเดียว ไม่ว่าจะเปิดจาก view ไหน

### cost/token — ต้องวัดก่อนว่าเลขหมายถึงอะไร
probe 3 เทิร์น: `total_cost_usd` = **0.0607 → 0.0701 → 0.1049** ไม่เคยลด = **ยอดสะสมทั้ง session ไม่ใช่ค่าเทิร์นนั้น** → **ค่าเทิร์น = ผลต่าง** (ถ้าเอา total มาโชว์ตรงๆ = คิดเงินทั้ง session ใหม่ทุกคำตอบ)
ส่วน `usage` เป็น**ต่อเทิร์น** (`out` = 3, 3, 1011 ตามความยาวคำตอบจริง)

โชว์ใต้คำตอบ `24k ctx · 1.2k out · $0.04 · 48s` + ยอดรวม session บนแถบบน (`ctx` = `input_tokens + cache_read + cache_creation` คือ token ที่เทิร์นนั้นจ่ายจริง)

### history → เปิดในหน้าแชท
- `POST /chat/new {"id": uuid}` = ทิ้ง session ปัจจุบันแล้วเปิดของเก่าด้วย `--resume`
- **`--resume` ไม่ replay อะไรกลับมา** มันแค่รู้ context → ข้อความเก่าต้องอ่านจาก transcript เอง: `GET /chat/history?id=` อ่าน `~/.claude/projects/-work/<id>.jsonl` แปลงเป็นรูปเดียวกับที่ stream ส่ง (you/claude/tool/tool_done) — bound เหมือน session list (`HISTORY_ITEMS` 300 ตัวท้าย, 8 MB, `readline(64KB)`)
- **ตัวเดียวกันนี้แก้เรื่องรีโหลดด้วย**: `GET /chat/state` คืน `session_id` → เปิดหน้าแชทมาแล้ว log ว่าง = วาดกลับจาก transcript ไม่ต้องเก็บ transcript ในหน่วยความจำฝั่ง server ให้ไปเพี้ยนจากที่หน้าเว็บวาด
- **repaint ทำที่ handler ของ event `reset` ที่เดียว** ไม่ทำในตัวที่กดด้วย ไม่งั้นประวัติซ้ำสองรอบ (POST ตอบกลับกับ SSE มาแข่งกัน)
- ยืนยัน: resume แล้ว `session_id` **ตัวเดิม** และถามต่อได้ (ตอบ "TWO" ได้จากบริบทเก่า)

### บั๊กที่เจอระหว่างทำ
- **sheet บล็อกหน้าแชทด้วยสถานะของเทอร์มินัล** — resume ในแชทไม่แตะ tmux เลย แต่ `free` คำนวณจาก `pane_current_command` เหมือนกันหมด = ทุกแถวเทาทั้งที่ควรกดได้ (และเคสปกติคือ `claude` เปิดค้างอยู่อีกฝั่ง) → `free = chatOn || (…)`, ปุ่ม Quit ซ่อนในแชท, `+ New session` ก็แยกตาม view
- **`isinstance(total, int | float)` พังบน python 3.9** ของเครื่อง mac (คอนเทนเนอร์ 3.11 ผ่าน) → ใช้ tuple `(int, float)` ให้ปลอดภัยทั้งคู่
- เทสต์เก่าที่ assert dict ของ `turn` ทั้งก้อนแตกเพราะมีฟิลด์ใหม่ → แก้ให้ assert เฉพาะที่เทสต์นั้นสนใจ

**หมายเหตุ:** ยอด `$ this session` รีเซ็ตเป็น 0 ตอน resume เพราะเป็นยอดของโปรเซสใหม่ — ตรงกับที่ agent รายงานเอง ไม่ได้หายไปไหน

## 2026-09-16 (ดึก) — sessions sheet เป็นทางตัน + default เป็นหน้าแชท

**อาการที่เจอจากการใช้จริง:** กด `+ New session` → `claude` ขึ้นในเทอร์มินัล → กลับมากดดู history อีกที ขึ้น "the terminal is busy" ทุกแถวเทา **ออกจากสถานะนี้ได้ทางเดียวคือไปพิมพ์ในเทอร์มินัล** ซึ่งคือสิ่งที่ sheet มีไว้ให้ไม่ต้องทำ = ด่านที่ทำไว้ถูกแล้วแต่ไม่มีประตูออก

**แก้:** ปุ่ม `Quit "claude"` ใน sheet → `POST /api/quit`

**วิธีปิดที่ใช้ได้จริง (probe ก่อน):**

| ท่า | ที่ prompt ว่าง | ระหว่างเทิร์น |
|---|---|---|
| `/exit` + Enter | ✅ → bash | — |
| **Ctrl-C สองครั้ง** | ❌ **ยังเป็น `claude`** | ❌ |
| Esc → `/exit` + Enter | ✅ | ✅ → bash |

Ctrl-C สองครั้งคือท่าที่ Claude Code บอกเองบนจอ แต่**ส่งผ่าน `send-keys` แล้วไม่ทำงาน** — ใช้ `Escape` ก่อน (เคลียร์ของบนจอ/เทิร์นที่รันอยู่ ให้บรรทัดถัดไปลงในกล่องพิมพ์ว่างๆ ไม่ใช่ต่อท้ายข้อความที่พิมพ์ค้าง) แล้ว `/exit`

รอจน pane รายงานว่าเป็น shell (เพดาน `QUIT_WAIT` 10 วิ, จริง ~0.9 วิ) ไม่เดาผล — เดาแล้ว sheet จะโกหกสถานะตัวเอง. ปิดไม่ลง (เช่น vim ที่ไม่รู้จัก `/exit`) ตอบ `409 busy:<program>` ตามตรง

**verify ทั้งวงจรบนเครื่องจริง:** `bash` → new session → `claude` → resume = `409 busy:claude` → quit = `200 bash` ใน 0.9 วิ → resume = `200` → `claude`

**default view = chat** — ไม่มีค่าใน localStorage = เปิดมาเจอแชท (เก็บเฉพาะตอนเลือก `terminal` ไว้เองถึงจะกลับไปที่เทอร์มินัล). บนมือถือแชทคือสิ่งที่เดสก์มีไว้ทำ เทอร์มินัลห่างไปแท็บเดียว

## 2026-09-16 (เย็น) — chat UI (ADR 0013)

**ทำเป็น view ที่สอง ไม่ใช่ครอบทับเทอร์มินัล** — `chat.py` ขับ Claude Code **ตัวที่สอง** ผ่าน `--input-format stream-json --output-format stream-json` (โปรโตคอลมีสเปก) ไม่ใช่ขูด ANSI จาก xterm.js (= หน้าจอ ไม่ใช่ interface พังทุกครั้งที่ Claude Code เปลี่ยนวิธีวาด และเอาครึ่งที่ใช้งานได้ไปเสี่ยงกับการเปลี่ยนหน้าตาของ upstream)

**เหตุผลที่ต้องมี:** เทอร์มินัลตัดบรรทัดตายที่ `COLUMNS` บนมือถือ = ~40 คอลัมน์ไทย คำตอบยาวๆ อ่านทรมาน — bubble มัน reflow เอง และเป็น HTML เลือกคัดลอกได้ตรงๆ ไม่ต้องผ่าน OSC 52

**transport = SSE + POST 2 เส้น ไม่ใช่ websocket** — ทางหนึ่งสตรีม อีกทางเป็น request ธรรมดา และ SSE ไม่ต้องลง dependency (stdlib ล้วนเหมือนทั้ง stack)

### probe ก่อนเขียน (2.1.273) — ยืนยันทุกข้อก่อนออกแบบ
- multi-turn บนโปรเซสเดียว: ส่งข้อความที่สองได้ โปรเซสไม่ตาย
- `stream_event.content_block_delta` → text ทีละ token
- `assistant.tool_use` + `user.tool_result` → pill
- **interrupt = `control_request` `{"subtype":"interrupt"}` ไม่ใช่ signal** ตอบใน ~1 วิ จบเทิร์นแล้ว**โปรเซสอยู่ต่อ** เทิร์นถัดไปใช้ได้
- รันคู่กับ tmux session ได้ ไม่ตีกัน (OAuth ใบเดียว)

### บั๊กที่เจอตอนรันจริง (เทสต์ปลอมจับไม่ได้)
1. **`say_end` ยิงเกิน** — content_block มี `index` และ **tool block ก็ยิง start/stop ของตัวเอง** → stop ของ tool ไปปิด bubble ที่ text block ยังเขียนอยู่ คำตอบเลยแตกเป็นสองก้อน. แก้ด้วย `self.text_blocks` เก็บ index ที่เป็น text เท่านั้น (เคลียร์ตอน `message_start`) + เพิ่มเทสต์ที่ fake agent ยิง tool block ซ้อนกลาง text block
2. **กด stop แล้วขึ้น "ทำงานไม่สำเร็จ"** — interrupt กลับมาเป็น **error result** ตัวที่แยกจาก failure จริงคือ `terminal_reason`: **`aborted_tools`** ตอนกำลังรัน tool, **`aborted_streaming`** ตอนกำลังพิมพ์ (วัดจริงทั้งคู่) → เช็ค prefix `aborted` ไม่ใช่ค่าเดียว
3. **Grep pill โชว์ path ไม่ใช่ pattern** — เทสต์จับได้ก่อน deploy ลำดับ key ใน `tool_detail()` สำคัญ

### เรื่อง concurrency (ย้อนหลักการเดิม)
**สอง agent อยู่ใน `/work` พร้อมกันได้แล้ว** — ย้อน "ทีละตัว" ที่เป็นเหตุผลว่าทำไม `mimo` ไม่แยก stack. **ไม่กั้น** เพราะสัญญาณเดียวที่มีคือ `pane_current_command` ซึ่งขึ้น `claude` ตั้งแต่แค่**เปิดค้างไว้** กั้นตรงนั้น = บล็อกเคสปกติ ฟีเจอร์ดูเหมือนพัง → แถวบนของ chat บอกว่าเทอร์มินัลมี agent เปิดอยู่ด้วย แล้วปล่อยให้คนตัดสิน

### SSE ผ่าน proxy
`proxy_buffering off` **จำเป็นแต่ไม่พอ** — ต้อง `proxy_read_timeout 86400s` ด้วย (default 60 วิ) + **heartbeat `: ping` ทุก 20 วิ** เพราะสตรีมที่ไม่มีอะไรไหลดูเหมือน idle ทั้งกับ nginx และ DSM RP. app ยิง `X-Accel-Buffering: no` ซ้ำอีกชั้น
**verify จากนอกบ้านจริง**: ถือสตรีมผ่าน `https://<domain>:15072` ครบ 100 วิ ได้ ping 5 ครั้ง ไม่หลุด (container-local ผ่านแม้เส้น RP พังก็เลยไม่นับ)

### อื่นๆ
- agent spawn **ตอนข้อความแรก ไม่ใช่ตอน boot** — เดสก์ว่างไม่ควรถือ node ตัวที่สองไว้ใน cap 2 GB, `POST /chat/new` ทิ้งได้
- **child ต้องพก `--dangerously-skip-permissions` เอง** — ในเทอร์มินัลแฟล็กนี้มาจาก alias ของ shell
- **ไม่เก็บ transcript** ฝั่ง server — รีโหลด = เริ่มดูใหม่ของ session เดิม, `GET /chat/state` บอกแค่ว่ามีเทิร์นค้างอยู่ไหม (หน้าเว็บกลับมากลางเทิร์นจะได้โชว์ปุ่ม stop ไม่ใช่ปุ่มส่ง)
- markdown ในหน้าเว็บทำเองแค่ fenced block + inline code — parser เต็มตัวคือ dependency + บั๊ก escaping
- **`font-size: 16px` ในช่องพิมพ์** ต่ำกว่านี้ iOS ซูมหน้าทั้งหน้าตอน focus
- header 390px ล้นเพราะสวิตช์ view กิน ~70 cells → ≤430px ย่อ `.icon-btn` 36→32, `.view` 32→28, ซ่อนปุ่ม keybar ใน chat view. วัดใน iframe 390 (headless Chrome บน mac clamp ~500px)
- เทสต์ใหม่ `tests/test_chat.py` ใช้ **fake agent ที่พูดโปรโตคอลเดียวกัน** (`CHAT_COMMAND` override) = ไล่ translation ทั้งเส้นโดยไม่กินโควตาทุกครั้งที่รันเทสต์

## 2026-09-16 (บ่าย) — `make desk-latest` + บั๊ก desk-status.json ถูกเขียนทับด้วย null

**โจทย์:** "claude code / mimo code มี update จะอัปยังไง ให้ latest ตลอดได้ไหม"

**self-update ใช้ไม่ได้ในกรงนี้ (probe แล้ว):** ทั้งคู่ลง `npm install -g` เป็น root ที่ `/usr/local/lib/node_modules` แต่คอนเทนเนอร์รันเป็น uid 1000 → `touch` = `Permission denied` ตัวอัปเดตในตัวเขียนทับตัวเองไม่ได้ และต่อให้ได้ก็หายตอน deploy (recreate container). watchtower ก็ช่วยไม่ได้ — อิมเมจ `build:` เอง ไม่ได้ pull จาก registry

**เลือกทางที่ 2 จาก 3 ทาง** (1 = pin มือ, 2 = สคริปต์ดึงเลข latest มาเขียน ARG, 3 = `@latest` ตรงๆ) — ข้อ 3 ตกเพราะ **layer `npm install -g` cache ด้วย command string ไม่มี cachebust = build ได้ของเก่าเงียบๆ** + ไม่รู้ว่ารันเวอร์ชันไหน + รีลีสที่พัง TUI (copy path / statusline) ถอยกลับจากมือถือไม่ได้ ส่วน pin ใน git `git revert` ทีเดียวจบ

**`scripts/desk_latest.py` + `make desk-latest`** (`ARGS=-n` = รายงานเฉยๆ): อ่าน npm dist-tag `latest` ของ `@anthropic-ai/claude-code` + `@mimo-ai/cli` และ `anthropics/skills@main` จาก GitHub API → เขียนทับ pin. **`MIMO_CODE_VERSION` อยู่ใน Dockerfile ไม่ใช่ compose** (compose ส่งแค่ `CLAUDE_VERSION`/`SKILLS_REF`) จุดที่พลาดง่าย. regex บังคับเจอ pin **พอดี 1 ที่ต่อไฟล์** ไม่งั้นโยน error — ไฟล์เปลี่ยนรูปแล้วต้องรู้ ไม่ใช่เขียนผิดบรรทัดเงียบๆ. ไม่รวม ttyd/rtk (pin ด้วย sha256 ด้วย ต้องโหลดไฟล์มา hash; ปีละครั้ง). dry-run **exit 0** ไม่ใช่ 1 — ไม่งั้น `make` พิมพ์ `*** Error 1` ใส่คนที่ได้คำตอบที่ต้องการพอดี

อัป claude 2.1.272 → **2.1.273** แล้ว (mimo 0.1.14 = latest, skills ref = HEAD อยู่แล้ว) · ทดสอบ write path ครบทั้ง 3 pin บน tree ชั่วคราว

### ⚠️ บั๊กที่เจอตอน verify: `desk-status.json` ถูกเขียนทับด้วย null

ไปดูไฟล์เจอ `{"model":"Opus 5","five_hour":null,"seven_day":null}` ทั้งที่ก่อนหน้ามี `pct 75`

**เหตุ:** Claude Code **ยังไม่มีตัวเลข rate limit จนกว่าจะได้ API response แรก** (statusline.sh คอมเมนต์ไว้เองว่า "absent until first API response") → **ทุกครั้งที่เปิด `claude`** จะ render statusline ที่ไม่มี limit ออกมาก่อน แล้ว block ที่ผมเขียนก็เอา null ไปทับค่าดีทิ้ง = **chip หายทันทีที่เปิดเดสก์** ซึ่งเป็นจังหวะเดียวที่อยากเห็นมันพอดี

**แก้:** เติม `| select(.five_hour != null or .seven_day != null)` ท้าย jq → render ที่ไม่มี limit **ไม่แตะไฟล์เลย** (ไม่เขียน ไม่ touch) ค่าเก่าอยู่ต่อแล้วค่อยๆ จางเป็น stale ตาม mtime ซึ่งตรงความจริง: เราไม่มีเลขใหม่

verify บนเครื่องจริง: วางค่าดีไว้ → ยิง statusline ที่ไม่มี rate_limits → ไฟล์เหมือนเดิมเป๊ะ (PASS)

## 2026-09-16 — sessions sheet + rate-limit chip (หยิบจากคลิป UI ของ Codex)

**โจทย์:** คลิป PWA ฐาน Codex (แชท bubble, การ์ดโควตา, ลิสต์ session, cost/token ต่อ session) — "ครอบแบบนี้ได้ไหมโดยไม่เสียของเดิม"

**ตอบ: ได้ แต่เป็น view ที่สอง ไม่ใช่ครอบทับเทอร์มินัล** ครอบทับ = ขูด ANSI จาก xterm.js มาประกอบ bubble พังทุกครั้งที่ Claude Code เปลี่ยนหน้าตา — นั่นคือทางที่ *ทำให้เสียของเดิม*

**probe บน NAS (claude 2.1.272, read-only)** — `claude -p --output-format stream-json --verbose` คายทุกอย่างที่ UI ในคลิปต้องใช้: `rate_limit_event.unifiedWindows.{five_hour,seven_day}.utilization` (0.39/0.54), `result.total_cost_usd`, `usage.*`, `tool_use`/`tool_result`, `system/init.session_id`; มี `--input-format stream-json`, `--include-partial-messages`, `--session-id`, `-r/--resume`, `--bg` + `claude agents|attach|logs|stop`. **รันคู่กับ tmux session ที่เปิดอยู่ได้ ไม่ตีกัน** (OAuth ใบเดียว)

**แต่ของดีส่วนใหญ่ไม่ต้องรอ chat UI** — ลงมือ 2 อันแรกก่อน ทั้งคู่เป็นของ *เพิ่ม* เทอร์มินัลไม่ถูกแตะสักบรรทัด:

### 1. Sessions sheet

ปุ่ม history → ลิสต์ `~/.claude/projects/-work/*.jsonl` newest first → แตะ = resume

- **ชื่อแถว**: `summary` record ก่อน → ไม่มีก็เอา user message แรกที่คนพิมพ์จริง. **ต้องกรอง**: probe พบว่า 11 session ที่มีอยู่ 4 อันขึ้นต้นด้วย `<local-command-caveat>` (slash command ที่ replay) และ tool_result ก็มาเป็น user turn — ทั้งคู่ขึ้นต้น `<` เลยใช้เป็นด่านได้. อีก 4 อันชื่อ `'hi'` จริงๆ → เลยโชว์วันที่ + id สั้นเสมอ ไม่ได้พึ่งชื่ออย่างเดียว. ยังไม่เจอ `summary` record สักไฟล์ (grep = 0) แต่รองรับไว้
- **งบการอ่านเป็นไบต์ ไม่ใช่บรรทัด**: `d45e192a.jsonl` = 4.6 MB และ `file-history-snapshot` หนึ่ง record ใหญ่เป็น MB ได้ → `readline(64KB)` + เพดาน 256KB/ไฟล์ + 30 ไฟล์ล่าสุด. บรรทัดที่โดนตัดกลางทาง = JSON พัง = ข้ามไปเอง
- **⚠️ resume ต้องยิงผ่าน tmux ไม่ใช่ websocket ของหน้าเว็บ** — คีย์ที่ส่งลง ws ไปโผล่ตรงที่ pane โฟกัสอยู่ ซึ่งปกติคือ **กล่องพิมพ์ของ Claude Code** → `claude --resume <uuid>` จะกลายเป็น*ข้อความถาม Claude* ไม่ใช่คำสั่ง (บนมือถือกู้ยาก). `upload.py` อยู่ในคอนเทนเนอร์ที่ถือ tmux server อยู่แล้ว (`docker exec` = uid 1000 = เจ้าของ socket) → `tmux send-keys`. ยืนยันแล้ว: `tmux display-message -p '#{pane_current_command}'` คืน `bash` ตอนว่าง และ **`claude` (ไม่ใช่ `node`)** ตอน Claude Code รัน → ไม่อยู่ใน `SHELLS` = ตอบ `409 busy:claude` ไม่ยิงอะไรเลย
- uuid regex กั้นก่อนถึง shell (สตริงนี้กำลังจะถูกพิมพ์ลง interactive bash)
- `+ New session` = ทางเดียวกัน ส่ง `claude` เปล่า. alias จาก `profile.sh` ติดมาเองเพราะคนพิมพ์คือ login shell

### 2. Rate-limit chip บน header

2 บรรทัด `5h 72% ↻2h6m` / `wk 58% ↻6h16m` — 80% เหลือง 95% แดง

- **โชว์เวลา reset ด้วย** (ขอเพิ่มรอบสอง): นับถอยหลังคือครึ่งที่ตัดสินว่าจะรอหรือหยุด — คำนวณจาก `resets_at` ในหน้าเว็บเอง เลยเดินต่อระหว่าง poll และเดินแม้เดสก์ว่าง (% หยุดนิ่งแต่เวลาไม่หยุด), ฟอร์แมตเดียวกับ `fmt_reset` ของ statusline (`2d` / `2h6m` / `14m`) สองที่จะได้ไม่ขัดกัน
- **2 บรรทัดไม่ใช่บรรทัดเดียว** — 4 ค่าเรียงขวางไม่พอบนมือถือ; ต่ำกว่า 430px ซ่อนชื่อ `claude-desk` กับป้าย `live` คืนที่ให้ chip (จุดเขียวบอกสถานะอยู่แล้ว). **วัดที่ 390px จริงด้วยการยัดหน้าเว็บใน iframe** เพราะ headless Chrome บน mac clamp หน้าต่างขั้นต่ำ ~500px (screenshot 390 = crop ไม่ใช่ layout จริง)

- **ตัวเลขมีที่เดียวคือ status line** — Claude Code ส่ง rate limit ให้ statusLine hook เท่านั้น → `statusline.sh` เขียน `~/.claude/desk-status.json` เพิ่ม, `GET /api/status` เสิร์ฟพร้อม `age`
- **ทำไมต้องมีทั้งที่ status line มีอยู่แล้ว**: โหมดมือถือของ `statusline.sh` (< 51 คอลัมน์) ตัดบาร์ limit ทิ้งเพื่อให้พอ 24 คอลัมน์ = **จอเล็กคือจอที่มองไม่เห็นโควตา**
- เขียนเฉพาะตอนค่าเปลี่ยน ไม่งั้นแค่ `touch` — ไม่เอา write ต่อเฟรมลง volume แต่ยังบอก "live vs stale" ได้จาก mtime. เขียนผ่าน temp + `mv` เพราะ `upload.py` อ่านพร้อมกัน
- ไม่มี session รัน = ตัวเลขหยุดนิ่ง → เกิน 20 นาที chip จางลง ไม่แกล้งทำเป็นสด
- units: `.rate_limits.*.used_percentage` เป็น **0–100** (ยืนยันจาก `limit_row()` ที่ `printf "%.0f"` แล้วต่อ `%`) — **คนละสเกลกับ `utilization` ใน stream-json ที่เป็น 0–1** อย่าสลับ

**verify บนเครื่องจริง** (deploy แล้ว): `/api/sessions` ไม่มี auth = 401, มี auth ผ่าน nginx = 1173 bytes/11 sessions; `statusline.sh` render เหมือนเดิม + เขียนไฟล์ + touch ตอนค่าเดิม; `/api/status` คืน `age`; resume จริง pane `bash → claude` แล้วรอบสองตอบ `409 busy:claude`; `503 no tmux pane` ตอนไม่มี server; `400 bad id` ตอน id ไม่ใช่ uuid. 23 เทสต์ใหม่ที่ `claude-desk/tests/`

### 3. แจ้งเตือนตอนงานเสร็จ — เลือก in-page (ไม่เอา Telegram)

เสนอ 2 ทาง พี่เลือก in-page พอ **รู้ตัวว่าปิดจอแล้วไม่เด้ง** (iOS suspend JS ของ PWA ที่ backgrounded) — Telegram จะรอดเคสนั้นแต่ต้องเพิ่ม bot token ใน vault, Web Push จริงต้อง VAPID + push service = งานแยกก้อน

- **จบเทิร์นอ่านจาก websocket ไม่ได้** — ws ส่ง terminal bytes ล้วน "Claude พูดจบ" เป็นรูปร่างในภาพที่ Claude Code วาด ไม่ใช่ event → ใช้ **`Stop` hook** (`done-hook.sh`) เขียน `~/.claude/desk-done.json` แล้ว `/api/status` (poll เดิม 15 วิ) พ่วงมาด้วย ไม่ต้องเปิด endpoint ใหม่
- hook **exit 0 เสมอ** — Stop hook ที่ตอบ non-zero ถูกรายงานกลับเข้า session แจ้งเตือนไม่คุ้มให้ไปขัดจังหวะคน
- ปุ่มเปิด/ปิดอยู่ท้าย sessions sheet เพราะ **Safari ให้ permission เฉพาะตอนอยู่ใน tap** จะขอตอนโหลดหน้าไม่ได้
- poll แรกหลังรีโหลดแค่**ตั้งนาฬิกา** (เทิร์นที่มันรายงานจบไปก่อนหน้าเว็บนี้เกิด) และไม่เด้งตอนหน้าเว็บมองเห็นอยู่ เพราะมองจอก็เห็นแล้ว
- **`hooks` เป็นส่วนเดียวของ `claude-settings.json` ที่ไปถึงเดสก์ที่มีอยู่แล้ว** — `entrypoint.sh` merge แบบ key ด้วย command string ต่อ event ไม่ใช่ `setdefault` (ยืนยันแล้ว: `Stop` ลงใน volume ที่มี `PreToolUse` อยู่ก่อน)
- verify ด้วยเทิร์นจริง: `desk-done.json` = `{"at":1789527004,"session_id":"dab3fc78…"}`, `/api/status` คายทั้ง quota + done

## 2026-09-16 — copy จาก `mimo` (MiMoCode) ด้วย: `allow-passthrough`

**โจทย์:** copy ที่ claude ได้แล้ว อยากให้ฝั่ง mimo ได้ด้วย

**MiMoCode ก๊อปคนละท่ากับ Claude Code:** grep ไบนารี (`@mimo-ai/cli/bin/.mimocode`, bun bundle 134 MB) เจอฟังก์ชัน

```js
function UR0(A){ if(!process.stdout.isTTY) return;
  let B=`\x1B]52;c;${Buffer.from(A).toString("base64")}\x07`,
      F=process.env.TMUX||process.env.STY ? `\x1BPtmux;\x1B${B}\x1B\\` : B;
  process.stdout.write(F) }
```

= **ยิง OSC 52 เอง** (ไม่ผ่าน `tmux load-buffer` แบบ Claude Code) และเมื่อเห็น `$TMUX` จะ **ห่อด้วย DCS passthrough** — ซึ่ง **tmux 3.3 ทิ้งทิ้งหมดถ้า `allow-passthrough` เป็น off (ค่า default)**. ตัวเรียกคือ `q6()` ผูกกับ `onMouseUp` → **ก๊อปตอนปล่อยเมาส์ทันที ไม่ต้องกดปุ่ม** (ปิดได้ด้วย `MIMOCODE_EXPERIMENTAL_DISABLE_COPY_ON_SELECT`)

**วัด A/B ด้วย pty harness ตัวเดิม** (ยิงซีเควนซ์ DCS ที่ MiMoCode เขียนเป๊ะๆ เข้า tmux แล้วอ่านฝั่ง pty):
- conf เดิม (`allow-passthrough off`) → **ไม่มี OSC 52 ออกมาเลย** = ก๊อปแล้วเงียบหาย ไม่มี error ให้เห็นทั้งสองฝั่ง
- conf ใหม่ (`allow-passthrough on`) → ได้ `mimo-copy-works` ครบ

`ui/app.js` ไม่ต้องแก้อะไร — handler ตัวเดิมรับต่อได้เลย รวมเป็น 3 ทางที่ปลายทางเดียวกัน: xterm selection (shell) / tmux buffer (Claude Code) / OSC 52 ตรง (MiMoCode)

**ราคาที่จ่าย:** `allow-passthrough on` = โปรแกรมใน container ยิง escape sequence ตรงเข้าเทอร์มินัลของเบราว์เซอร์ได้ ซึ่งในกรงนี้ไม่ได้เพิ่มความเสี่ยงจริง (ทั้ง `claude` และ `mimo` รันโดยปิด permission prompt อยู่แล้ว = bash เชื่อใจเต็มที่อยู่ก่อนแล้ว)

## 2026-09-16 — copy ออกจาก Claude Code ยังไม่ได้ (ปุ่ม Copy รอบแรกแก้ไม่ตรงจุด)

**อาการ:** ใส่ปุ่ม ⧉ Copy ไปแล้ว แต่ copy ข้อความออกจากหน้าจอ Claude Code ยังไม่ได้ ในรูปที่ส่งมามีบรรทัด **`copied 30 chars to tmux buffer · paste with prefix + ]`** อยู่มุมขวา — นั่นคือเบาะแสทั้งหมด

**สาเหตุจริง (คนละอันกับรอบแรก):** Claude Code **เปิด mouse tracking** ตอนรัน TUI → การ drag ในนั้นไม่เคยกลายเป็น selection ของ xterm เลย แอปกินอีเวนต์เมาส์ไปเก็บ selection ของตัวเอง แล้วก๊อปด้วย `tmux load-buffer -w` (grep จากไบนารี `claude` เจอโค้ด `clipboard: tmux load-buffer -w -` และ branch `osc52`) → `term.getSelection()` ที่ปุ่มเรียกจึงคืนค่าว่างเสมอ. ปุ่มรอบแรกใช้ได้เฉพาะตอนอยู่ที่ shell prompt ธรรมดา

**ต้องต่อท่อ 2 ข้อ:**
1. **`set-clipboard on` ใน `tmux.conf`** — ของเดิมเป็น default `external` ซึ่งส่งต่อเฉพาะ OSC 52 ที่ **แอป** ยิงเอง ไม่ยิง buffer ที่ **tmux** ถือ. ตรวจแล้ว: `terminal-features` มี `clipboard` และ terminfo มี `Ms` อยู่แล้ว ขาดแค่ option นี้
2. **`ui/app.js` ดัก OSC 52 เอง** — `term.parser.registerOscHandler(52, ...)` เพราะ **xterm.js ไม่ได้ handle OSC 52 ให้** (ต้องมี `allowProposedApi: true` ซึ่งมีอยู่แล้ว) แล้ว decode base64 → `navigator.clipboard.writeText()`; iOS เขียนนอก user gesture ไม่ได้ → เก็บไว้ในตัวแปรแล้วขึ้นป้าย `tap to copy` ปุ่มเดิมกดแล้ว fallback ไปใช้ค่านี้

**วัดจริง 2 ชั้น ไม่ได้เดา:**
- **ฝั่ง tmux:** เขียนสคริปต์ `pty.fork()` เปิด tmux จริงในคอนเทนเนอร์ แล้วสั่ง `printf 'hello-osc' | tmux load-buffer -w -` → อ่านไบต์จาก pty เจอ `ESC]52;;aGVsbG8tb3Nj` = ยิงออกจริงหลังเปลี่ยน option. **kind ว่าง ไม่ใช่ `c`** (tmux 3.3a) handler เลยต้องรับทั้ง `;c;<b64>` และ `;;<b64>`
- **ฝั่งเบราว์เซอร์:** เสิร์ฟ `ui/` ด้วย `python3 -m http.server` แล้วเปิดหน้า `?demo=1` ใน iframe จาก headless Chrome (extension ต่อไม่ติด) — เพิ่ม `if (DEMO) window.term = term;` ไว้ให้ทดสอบยิง escape sequence เข้าไปได้ (live ไม่ expose). **ต้อง stub `navigator.clipboard.writeText` ก่อน** เพราะ headless ไม่มี user activation แล้ว promise ค้างไม่ settle เลย (อาการตอนแรก: handler ทำงานแต่ป้ายปุ่มไม่เปลี่ยน ดูเหมือน handler ไม่ยิง) → ผลลัพธ์ `clipboardGot=[hello-from-tmux] btn=[✓ copied]` ทั้งรูปแบบ `;c;` และ `;;`

**ทดสอบของใหญ่ ไม่ใช่แค่ 15 ไบต์:** ของจริงคือก๊อปโค้ดทั้งบล็อก → ยิงซ้ำทั้งสองฝั่งที่ 2K/16K/64K — tmux ส่งออกครบทุกขนาด (64,000 ไบต์ → base64 85,336 ตัวอักษรในซีเควนซ์เดียว) และ handler decode ครบทุกขนาด. เพิ่ม error path ด้วย: payload เสีย/โดนตัด เดิม `catch` แล้ว `return true` **เงียบสนิท** = หน้าตาเหมือนบั๊กเดิมเป๊ะ และ `oscClip` ค้างค่าเก่าไว้ กดปุ่มแล้วได้ selection เก่าไปแปะ → ตอนนี้ขึ้น `copy failed` + ล้างค่าเก่า (ทดสอบด้วย payload ที่ไม่ใช่ base64 แล้ว: `label=copyfailed, wrote=none`)

**⚠️ กับดักที่ใหญ่กว่าตัวบั๊ก — แคช 7 วัน:** `nginx.conf` เสิร์ฟ `.js/.css/.svg/.png/.webmanifest` ด้วย `public, max-age=604800` ทั้งก้อน แปลว่า **ปุ่ม Copy ที่ deploy ไปเมื่อวานอาจไม่เคยถึงมือถือเลย** (หน้านี้ถูก Add to Home Screen เป็น PWA ยิ่งไม่ยอม refetch) — อ่านออกมาเหมือน "แก้แล้วยังไม่หาย" ทุกประการ. แยกเป็น: `vendor/` + `fonts/` (ไฟล์ pin เปลี่ยนเฉพาะตอน build ใหม่) คงแคช 7 วัน, ที่เหลือ = `no-cache` revalidate ทุกครั้ง. ยืนยันหลัง deploy: `app.js → no-cache`, `vendor/xterm.min.js → max-age=604800`

**ที่เสียเวลา:** grep หา `cli.js` ไม่เจอ เพราะ claude 2.1.272 ลงเป็น **native binary 227 MB** (`node_modules/@anthropic-ai/claude-code-linux-x64/claude`) ไม่ใช่ JS bundle แล้ว — ต้อง `grep -a` บนไบนารี

## 2026-09-16 — เปลี่ยน harness เป็น MiMoCode (`mimo`) + คำสั่งถามครั้งเดียวเปลี่ยนชื่อเป็น `ask`

**โจทย์:** อยากได้ harness เป็น `XiaomiMiMo/MiMo-Code` แทน opencode

**ชื่อชนกันก่อนเลย:** binary ของ MiMoCode ชื่อ **`mimo`** ซึ่งเป็นชื่อที่เราเพิ่งใช้กับคำสั่งถามครั้งเดียวไปเมื่อวาน → ยกชื่อ `mimo` ให้ upstream (เอกสารเขาทั้งหมดเรียกชื่อนี้) แล้วเปลี่ยนของเราเป็น **`ask`** (ไฟล์ยังเป็น `ask.py` อยู่แล้ว) — `mimo-code.sh` + `opencode.json` + opencode ถอดออกทั้งชุด

**MiMoCode = fork ของ opencode** config หน้าตาเดียวกัน (`npm: @ai-sdk/openai-compatible`, `options.baseURL/apiKey`, `model: "<provider>/<model>"`) แต่ **ห้ามเชื่อว่าเหมือนกันหมด** เจอต่างจริง 2 จุด:
1. **`"_comment"` ใช้ไม่ได้** — MiMoCode validate schema แล้วตีตกทันที `Error: Configuration is invalid ... Unrecognized key: "_comment"` ทำให้ `mimo models` และทุก session ตาย (opencode ปล่อยผ่านมาตลอด). ไฟล์เป็น `.jsonc` อยู่แล้ว → ย้ายไปใช้คอมเมนต์ `//` ทดสอบแล้วผ่าน
2. **`limit.output` มันไม่สน** — จับ body จริงได้ `max_tokens: 128000` ของมันเอง (opencode ส่ง 32000 ตามที่ตั้ง). ไม่เป็นไร กฎที่แคร์คือห้ามส่งค่าเล็ก

**ที่เหมือนกันและตรวจซ้ำแล้ว (ไม่ได้อนุมานจาก opencode):** `reasoningEffort` camelCase ออกไปเป็น `reasoning_effort: low` จริง — ยิงผ่าน echo server เหมือนเดิม และรอบสุดท้ายยิงด้วย **config ตัวที่ deploy จริง** (sed เปลี่ยนแค่ baseURL) ไม่ใช่ไฟล์ทดสอบ

**path ของ config:** `MIMOCODE_HOME=/tmp/x` แล้ววาง `mimocode.jsonc` ที่ root ของมัน → provider ไม่โผล่ใน `mimo models`. ที่อ่านจริงคือ **`$HOME/.config/mimocode/mimocode.jsonc`** ซึ่งอยู่ใน home volume = กับดัก seed เดิม → `entrypoint.sh` เขียนทับจาก `/opt/claude-desk/mimocode.jsonc` ทุกครั้งที่ start พร้อม **แทนคีย์ด้วย `sed`** (ไฟล์ใน git เก็บ placeholder `__MIMO_API_KEY__`, ไฟล์ที่ render แล้ว `chmod 600`)

**pin ไม่ใช้ latest:** ที่บอกว่า "ท่าเดียวกับ claude คือ latest เสมอ" — จริงๆ claude ใน stack นี้ **pin** (`ARG CLAUDE_VERSION=2.1.272`) เหมือน `SKILLS_REF`/`TTYD_VERSION`/`RTK_VERSION` และ watchtower ปิดไว้ทั้ง stack ท่าของ claude จึงคือ pin → `ARG MIMO_CODE_VERSION=0.1.14` (dist-tag latest ตอนนี้ = 0.1.14 พอดี) อัปเกรดคือแก้ ARG แล้ว deploy

**permission:** MiMoCode มี `--dangerously-skip-permissions` + `MIMOCODE_DANGEROUSLY_SKIP_PERMISSIONS=1` ของตัวเอง → ใช้ flag ใน alias อย่างเดียว ไม่เขียน rule ซ้ำในไฟล์ config. alias ยังเคลียร์ `CLAUDE_CODE_OAUTH_TOKEN` ด้วย เพราะ first-run auth ของมัน**เสนอ import credential ของ Claude Code** (เอกสาร upstream บอกเอง) — เป็นสุขอนามัย ไม่ใช่กำแพง (bash เปิด, ttyd uid เดียวกัน)

**alias ใช้ flag ไม่ได้ (จับได้ตอนทดสอบท่าที่คนพิมพ์จริง):** ทุกรอบที่เทสต์ก่อนหน้านี้ยิง `mimo run --dangerously-skip-permissions "..."` = flag อยู่**หลัง** subcommand ผ่านหมด แต่ alias มันแตกเป็น `mimo --dangerously-skip-permissions run "..."` = flag อยู่**หน้า** → yargs พ่น help ออกมาเฉยๆ ไม่รันอะไรเลย (MiMoCode มี default command ที่กิน positional). เปลี่ยนไปใช้ **`MIMOCODE_DANGEROUSLY_SKIP_PERMISSIONS=1`** ใน alias แทน ไม่ขึ้นกับตำแหน่ง argv. **บทเรียน: `bash -lc` ไม่ขยาย alias** (non-interactive) และ `timeout <cmd>` ก็ไม่ขยายด้วย (มันรัน binary) — ต้อง `bash -lic` และไม่ห่อ timeout ถึงจะเทสต์ของจริง

**ซ่อน catalog `xiaomi/*` ที่ไม่มี credential:** `only_configured_models: true` **ไม่พอ** (มันคุมเฉพาะ provider ของเราเอง วัดแล้วยังเห็น 3 รายการ) ต้อง **`disabled_providers: ["xiaomi"]`** ที่ระดับบนสุด — หลังใส่ `mimo models` เหลือ `mimo/mimo-v2.5-pro` กับ `mimo/mimo-v2.5` เท่านั้น ไม่งั้นกดเลือกในตัวสลับโมเดลแล้วพังหรือเด้ง OAuth บนมือถือ

**แทนคีย์ด้วย python ไม่ใช่ sed:** คีย์ที่มี `&` หรือ `|` จะโดน sed ตีความเป็นไวยากรณ์แล้วเขียน placeholder กลับไปเงียบๆ ตอน rotate คีย์

**verify หลัง deploy:** `which ask mimo` ครบ · `~/.config/mimocode/mimocode.jsonc` render แล้ว mode 600 มี base url จริง · `mimo models` เห็น `mimo/mimo-v2.5-pro` + `mimo/mimo-v2.5` · `mimo run "reply READY"` → `> build · mimo-v2.5-pro` แล้ว `READY` · `ask "3+4"` → `7` · body จาก config จริง = `reasoning_effort: low`

## 2026-09-15 — clipboard: copy ออกไม่ได้ (paste เข้าได้)

**อาการที่แจ้ง:** paste ข้อความเข้าไปในแชทของ claude ได้ปกติ แต่ copy ข้อความ**ออก**มาแล้วไป paste ที่ editor ไม่ได้ + แปะรูปจากข้างนอกเข้าไปก็ไม่ได้

**สาเหตุ copy ออกไม่ได้:** `ui/app.js` มีแต่ `paste-btn` (`navigator.clipboard.readText()`) **ไม่มีทาง copy เลย** — xterm วาดจอลง canvas/WebGL selection ที่ลากในเทอร์มินัลจึงไม่ใช่ DOM selection เบราว์เซอร์กด Cmd/Ctrl+C ไปก็ไม่มีอะไรให้หยิบ. เพิ่มปุ่ม **⧉ Copy** ข้างๆ Paste: `term.getSelection()` → `navigator.clipboard.writeText()` (การกดปุ่มคือ user gesture ที่ iOS บังคับ, หน้าเว็บเป็น https อยู่แล้ว = secure context) พร้อมฟีดแบ็กบนตัวปุ่มเอง (`✓ copied` / `select first` / `blocked`) เพราะบนมือถือไม่มี toast ให้ดู

**รูป: ทำให้ได้ไม่ได้ ไม่ใช่ยังไม่ได้ทำ** — Claude Code อ่านรูปจาก clipboard ของ**เครื่องที่มันรันอยู่** ซึ่งคือคอนเทนเนอร์: ไม่มี display server ไม่มี clipboard และ websocket ของ ttyd ส่งแต่คีย์สโตรก ไม่ได้ส่ง clipboard object. ไม่เกี่ยวกับ harness ที่ใช้ (เปลี่ยนไป MiMoCode ก็เหมือนเดิม). ทางที่มีอยู่แล้วคือ drawer → Add files → ไฟล์ลง `/work/in/` แล้วพิมพ์พาธในพรอมป์

**verify:** `node --check ui/app.js` ผ่าน, deploy แล้ว `docker exec claude-desk-nginx grep copy-btn` เจอทั้ง `app.js` และ `index.html` ในอิมเมจที่รันอยู่ (nginx COPY `ui/` เข้าอิมเมจ ไม่ได้ bind mount — ต้อง rebuild ทุกครั้งที่แก้หน้าเว็บ)

## 2026-09-15 — `mimo-code`: agent harness สมอง mimo (ต่อจาก one-shot)

**ฟีดแบ็ก:** one-shot `mimo` "ไม่ตอบโจทย์" — อยากได้ mimo ขับ **harness** แบบ agent จริง และถามว่าต้องแยก stack `mimo-desk` ไหม

**ตอบเรื่องแยก stack: ไม่แยก** — เดสก์เป็น single-session โดยโครงสร้างอยู่แล้ว (`ttyd -m 1` ปฏิเสธเบราว์เซอร์ตัวที่สอง + `tmux new -A -s main` จอเดียว) สอง agent จึงรันพร้อมกันไม่ได้อยู่ดี = isolation ที่ได้มาใช้ไม่ได้จริง ขณะที่ต้องซ้ำ nginx sidecar + `.htpasswd` + DSM RP entry ตัวที่สอง (ตัวแรกยังค้างเรื่อง WebSocket header) + share + `ui/` key bar ทั้งชุด. **จะแยกก็ต่อเมื่อ**อยากให้ mimo รันงานยาวไปพร้อมกับใช้ `claude` อยู่ — ซึ่งต้องรื้อ `-m 1` ด้วย

**เลือก harness ด้วยการลองจริง ไม่ใช่เลือกจาก README** — ทดสอบในคอนเทนเนอร์ที่รันอยู่ (`docker exec`) ไม่ rebuild image เลย เพราะ `MIMO_API_KEY`/`MIMO_BASE_URL` อยู่ใน env ของมันอยู่แล้ว:
- **aider** (venv ใน /tmp): ผ่าน — `--model openai/mimo-v2.5-pro --reasoning-effort low` แก้ไฟล์สำเร็จ แต่เป็น edit loop ไม่ใช่ tool loop (ไม่มี read/bash/glob เป็นเครื่องมือของตัวเอง)
- **opencode** (`npm i -g --prefix /tmp/oc opencode-ai`): ผ่านแบบเต็ม — provider `@ai-sdk/openai-compatible` + `baseURL`/`apiKey` ชี้ mimo แล้วสั่ง "create hello.py that prints hi, then run it" → เห็น `Write hello.py` แล้ว `$ python hello.py` → `hi` **tool call จริง + รัน bash เอง** = ตรงกับที่ขอ
- **ไม่เอา claude-code-router**: ข้อดีเดียวคือได้ skills pptx/docx กลับมาใช้ ซึ่ง coding agent ไม่ใช้ แลกกับ Node proxy แปลง wire เพิ่มใน container `mem_limit: 2g` ที่มี Claude Code + LibreOffice อยู่แล้ว (โฮสต์ swap เต็ม 2047/2047 เหลือ available 4.4 GB)

**ที่ทำ:** `opencode-ai@1.18.31` pin `ARG OPENCODE_VERSION` ใน npm global บรรทัดเดียวกับ claude + `opencode.json` ที่ `/opt/claude-desk/` (ไม่ใช่ `/home/claude` — บทเรียน seed named volume) + wrapper `/usr/local/bin/mimo-code` (`mimo-code.sh`) ตั้ง `OPENCODE_CONFIG`, เช็ค env, `cd /work` ถ้าอยู่นอก, `unset CLAUDE_CODE_OAUTH_TOKEN` ก่อน exec (agent permission เปิดหมด ไม่มีเหตุให้เห็น subscription token). alias `m` ในแบนเนอร์เพราะพิมพ์บนมือถือ

**config ที่สำคัญ:** `reasoning_effort: low` ใน `models.*.options` (default เผา 10,457 tokens/161 วิ vs 3,796/79), `limit.output: 32000` ใหญ่ไว้เพราะ cap เล็กถูกเผาไปกับการคิดก่อนแล้วได้ turn ว่าง, `permission: allow` ทุกอัน (ปุ่มอนุมัติรายเครื่องมือบนมือถือ = ใช้ไม่ได้จริง คอนเทนเนอร์คือกรง)

**สะดุดระหว่างทาง:** opencode มองไดเรกทอรีนอก project เป็น `external_directory` แล้ว auto-reject (เทสต์ใน `/tmp` เลยเขียนไฟล์ไม่ได้) — ของจริง cwd = `/work` ไม่เจอปัญหานี้

**กับดักที่เกือบหลุด — `reasoning_effort` ไม่เคยถูกส่งเลย:** ตั้ง `"reasoning_effort": "low"` ใน `models.*.options` ตามสัญชาตญาณ แล้ว **config รับเฉยๆ แต่ไม่ส่งออกไป**. จับได้เพราะไปไล่ดู body จริง: log ของ opencode (แม้ `--log-level DEBUG`) ไม่ดัมป์ request body → เลยเขียน echo server stdlib ฟัง `127.0.0.1:8899` ตอบ chat.completion ปลอม แล้วรัน `MIMO_BASE_URL=http://127.0.0.1:8899/v1 mimo-code run hi` อ่านไฟล์ที่มันบันทึกไว้. ผลรอบแรก: มี `max_tokens: 32000` (มาจาก `limit.output`) แต่ **ไม่มี `reasoning_effort` เลย**. ลอง 3 แบบด้วย echo server ตัวเดิม: `provider.options.reasoning_effort` → ไม่ส่ง, `models.*.options.providerOptions.mimo.reasoning_effort` → ส่ง, **`models.*.options.reasoningEffort` → ส่ง** (AI SDK แปลง camelCase→snake_case เอง) เลือกอันหลังเพราะสั้นสุด. **อาการถ้าพลาด = ทุกเทิร์นวิ่งที่ effort default** (10,457 tokens/161 วิ vs 3,796/79) ซึ่งอ่านออกมาเหมือน "mimo ช้าเป็นปกติ" พอดี — และเป็นประโยคที่เพิ่งเขียนลง doc ไปเองด้วย

**`instructions: ["/work/CLAUDE.md"]`:** opencode อ่าน `AGENTS.md` ไม่ใช่ `CLAUDE.md` → ถ้าไม่ตั้ง harness จะไม่รู้กฎ in/out ที่ `entrypoint.sh` ก๊อปลงไป ทั้งที่เปิด edit+bash อยู่ในแชร์เดียวกัน. ยืนยันแล้วว่าเข้าจริง: system prompt ที่จับได้ 14,387 ตัวอักษร มีบรรทัดจาก `/work/CLAUDE.md` ครบ

**แบนเนอร์:** ตัดเหลือ `claude | r = resume | m = mimo agent` + `mimo <ask> = one answer` เพราะบรรทัดเดิม ~70 คอลัมน์ ล้นจอมือถือที่วัดไว้ ~47

**verify หลัง deploy:** `which mimo-code opencode` ครบ, `opencode --version` = 1.18.31, `mimo-code run "reply OK"` → `> build · mimo-v2.5-pro` แล้วตอบ `OK` = config จาก `/opt` โหลดจริง provider/model resolve ผ่าน

**ยังไม่ได้วัด:** TUI เต็มจอของ opencode ผ่าน key bar บนมือถือ (Esc/⇧Tab/Ctrl) ใช้ดีแค่ไหน — ต้องลองจากเครื่องจริง ถ้าฝืดค่อยใช้ `mimo-code run "<task>"` แทน

## 2026-09-15 — `mimo <ask>` ในเดสก์ (คำถามครั้งเดียว ไม่ใช่ agent ตัวที่สอง)

**โจทย์:** "ทำให้ support ใช้ mimo ด้วยได้ไหม" — mimo คือ endpoint OpenAI-wire ที่ shorts-factory/news-feed/ops-bot ใช้อยู่

**probe ก่อนออกแบบ** (รันในคอนเทนเนอร์ `shorts-factory` บน NAS เพราะ workstation ยิงออกไม่ได้ ดู memory `sandbox_outbound_blocked`): สองข้อที่คิดว่าจะบล็อก **ไม่บล็อก** — ส่ง `tools:[...]` แล้วได้ `finish_reason=tool_calls` + `tool_calls` ที่ถูกต้องกลับมาใน 27.8 วิ, ส่ง `max_tokens=64` แล้วได้ content จริง (`'Hi there, friend! 👋'`) ใน 2.8 วิ ไม่ใช่ `''`. **แต่พรอมป์นั้นคือ "Say hi in 3 words"** = โมเดลแทบไม่ได้คิด 64 tokens เลยไม่มีวันหมดไปกับ reasoning — **ไม่ได้ทดสอบข้ออ้างจริงของ `shared/mimo.py`** (budget ถูกเผาไปกับการคิดก่อนแล้ว content กลับมาว่าง) `ask.py` จึงยังไม่ส่ง `max_tokens` เหมือนเดิม

**แต่ตัวเลขที่ตัดสินคือ latency:** tool call ที่ไม่มี context เลยยัง 28 วิ = พื้น ไม่ใช่ค่าเฉลี่ย. เวลาของ mimo โตตาม token ที่คิด (~30 tok/s) และลูปของ Claude Code มี context โตทุกเทิร์น → งาน pptx หนึ่งชิ้น (หลายสิบเทิร์น) = หลายสิบนาทีบนมือถือ. **ตัดทาง claude-code-router ทิ้ง** (ต้องยัด Node proxy แปลง Anthropic↔OpenAI เข้าคอนเทนเนอร์ `mem_limit: 2g` ที่ถือ Claude Code + LibreOffice อยู่แล้ว บนโฮสต์ที่ OOM มาสองครั้ง) และตัด opencode/aider ทิ้งด้วยเหตุผลเดียวกัน + dependency ของ agent ตัวที่สอง

**ที่ทำ:** `ask.py` → COPY เป็น `/usr/local/bin/mimo` (stdlib urllib ล้วน ไม่ใช้ `openai` — อิมเมจไม่มี และไม่ต้องมี). รับ prompt จาก argv, จาก stdin, หรือทั้งคู่ (argv = คำถาม, stdin = วัตถุดิบ ต่อท้ายด้วย `---`). คำตอบออก **stdout** ตัวนับวินาทีออก **stderr** (ไพป์/redirect ได้สะอาด, มือถือไม่นึกว่าค้าง). ไม่ส่ง `max_tokens`, `reasoning_effort=low`, deadline `MIMO_ASK_TIMEOUT_SECONDS` default 300. **ไม่ stream** (คำตอบเดียวกัน stream 400 วิ vs 137 วิ) **ไม่ retry** (stall เป็น window ไม่ใช่ราย request — บอกให้รอสักครู่แล้วถามใหม่)

**ที่วางไฟล์:** `/usr/local/bin` ในอิมเมจ ไม่ใช่ใต้ `/home/claude` — บทเรียนเดียวกับ `statusline.sh`: docker seed named volume จากอิมเมจ**เฉพาะตอน volume ว่าง** เดสก์ที่ deploy ไปแล้วจะไม่เห็นไฟล์เลย

**secrets ฟรี:** `MIMO_API_KEY` → `shared.llm.mimo_api_key` **มีใน vault อยู่แล้ว** (bots ใช้ร่วมกัน) + literal `MIMO_BASE_URL`/`MIMO_MODEL` → ไม่ต้อง `make edit-vault` เลย เลี่ยงกับดักลำดับ (ใส่คีย์ใน manifest ก่อนมีค่าใน vault = `render_env.py` โยน `missing vault path` แล้ว `make secrets` พังทั้ง repo)

**verify บน NAS หลัง deploy:** `mimo "ตอบสั้นๆ: 2+2"` → `4`; `printf ... | mimo "บรรทัดนี้แปลว่าอะไร"` → คำแปลไทยของ error ffmpeg. banner ใน `profile.sh` เพิ่ม `mimo <ask> = one-shot answer`

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

## 2026-09-17 — what the Relay spec was worth taking

Read `.refinventory/.claude-desk/relay-ai-workspace-build-spec-v1.md` (a build
spec for a multi-tenant Next.js/Postgres AI workspace) against this desk, wrote
the verdict to `.notes/relay-spec-harvest.md`, and built the eight items worth
having. Most of the spec does not apply and the note says so out loud — the
whole stack (Next/React/Tailwind/shadcn/Drizzle/Better Auth/S3/pgvector) is dead
on arrival in a 2 GB container whose UI is vendored xterm.js with no bundler,
and multi-tenancy has no meaning behind one basic-auth door.

**The find.** `app.js` appended each delta to a string and re-ran the markdown
pass over the whole answer — every token threw away and recreated every node of
the reply. Quadratic over a turn, worst exactly where this view exists to help:
a long Thai answer on a phone. It also read `scrollHeight` per delta to decide
whether to follow the bottom. Spec §11 forbids both; §13.5 says the test must
*fail* on it. The server was already right — `chat.py` emits `text_delta` only.

**Shipped** (f827a01, b843a16, dec0d73, 57b4c2d, eb12c78):

- `ui/stream.js` — paragraph-tail writes, markdown once at `say_end`, one commit
  per frame, sentinel + `IntersectionObserver` instead of measuring.
- Numbered events with `id:`, a 4000-event ring, `Last-Event-ID` replay, and a
  snapshot when the ring has rolled past. iOS suspends a backgrounded PWA, so
  this is the ordinary path on a phone, not an edge case.
- A reloaded page asks from zero and gets the snapshot; `since(0)` deliberately
  refuses to replay, which would redraw every past turn.
- Jump-to-latest, ✓/✕ on finished pills, `:focus-visible`, reduced motion,
  composer drafts per conversation, and a failure that says its
  `terminal_reason` and offers the message back.

**Tests** went from 26 to 90. Two browser harnesses under `tests/`: one drives
`stream.js` directly, one frames the real page in demo mode through a
demo-only `window._chat` hook. Both were mutation-checked — against the old
per-delta shape the first reports 311 commits and 622 layout reads for 311
deltas (32 and 32 now), and dropping the dedup or the repaint's `clearLog()`
turns three of the second's assertions red.

**Two traps worth remembering.** Headless Chrome produces one frame and then
stops, so a chained `requestAnimationFrame` stalls — both harnesses drive frames
from a timer. And the fake agent finishes a turn in milliseconds, so anything
that has to be observed *mid-answer* is driven straight through `_translate`
rather than raced against a child.

Not deployed. `python3 -m pytest claude-desk/tests` → 90 passed.


## 2026-09-18 — AI Desk redesign and Codex support

User chose **AI Desk** and ChatGPT-account login for Codex. Implemented provider
selection, device-auth launcher, native Codex histories and JSONL chat adapter,
per-user/provider live chat ownership, shared skill discovery and AGENTS.md work
instructions. Preserved existing deployment and volume names. Updated Homepage
label and version updater. Added a responsive welcome/task-starter UI and fixed
hidden drawer shadows. Hardened upload completion/temp files and download scope.

Workstation migration installed 23 adapted/validated skills into ~/.codex/skills;
48 existing shared skills were retained. Claude-only tool skills were excluded,
Codex's built-in skill-creator retained, and NotebookLM auth/profile data excluded.

Validation uses fake-agent subprocesses plus real Chrome at desktop/mobile sizes;
no live ChatGPT login or paid agent turn, and no NAS deployment. See
[review](ai-desk-review.md) for scope, remaining work and validation boundaries.

## Verification completed — 2026-09-19

- **124 tests passed, zero failures/errors/skips**, including real Chrome UI and streaming/reconnect tests.
- Native Mac/arm64 image build passed with Claude Code 2.1.276 and Codex 0.155.0.
- Credential-free, network-disabled container startup smoke passed: CLI binaries,
  Codex Chat state API, sessions API, skill discovery and generated AGENTS.md.
- nginx image build and `nginx -t` passed. Real HTTP probes returned 200 for
  `/files/in/probe.svg`, 404 for a workspace file outside in/out, and 403 for
  a symlink out of the download directories. Download prefixes use `^~` so the
  UI asset regex cannot intercept uploaded SVG/PNG/JS files.
- JavaScript/Python syntax, shell syntax, YAML parsing and `git diff --check` passed.
- Screenshots: `screenshots/ai-desk-desktop.png`, `screenshots/ai-desk-mobile.png`.
- **Not verified on NAS:** amd64 cross-build on this Mac crashed at the existing
  `claude --version` smoke step (Bun memory assertion under QEMU, before Codex).
  Native build with the same CLI versions passed. Build/run on the NAS's native
  amd64 host is still required before claiming production readiness.
- No deployment, real ChatGPT sign-in or live/paid Codex turn was performed.

## 2026-09-19 — ตรวจคำถามเรื่อง Codex sign-in หลังปิดจอ

**คำถามผู้ใช้:** Codex ต้อง sign in ใหม่ทุกครั้งเมื่อปิดจอแล้วกลับมาหรือไม่.

**สิ่งที่ตรวจ:** อ่าน `ui/app.js`, `Dockerfile`, `entrypoint.sh` และ
`docker-compose.yml`. ตัว container ใช้ `HOME=/home/claude` ซึ่ง mount จาก
named volume `claude_desk_home`; startup สร้าง `~/.codex` โดยไม่ได้ลบข้อมูลเดิม.
ตาม configuration การปิดจอหรือแท็บจึงไม่ควรทำให้ข้อมูลล็อกอินหาย.

**พบปัญหา UI:** ปุ่ม `agent-login` ถูกซ่อนเฉพาะเมื่อ provider ไม่ใช่ Codex
(`loginButton.hidden = provider !== 'codex'`). ยังไม่มีการตรวจ authentication
ก่อนแสดงปุ่ม จึงแสดง “Sign in to Codex” แม้เคยล็อกอินแล้ว และชวนให้เข้าใจว่า
ต้องล็อกอินซ้ำ. อธิบายให้ผู้ใช้ลองส่งข้อความได้โดยไม่ต้องกดปุ่มซ้ำ หากเพียงเห็นปุ่ม.

**สถานะค้าง:** ถามผู้ใช้แล้วว่าเพียงเห็นปุ่ม หรือส่งข้อความแล้วระบบบังคับกรอกโค้ด
ล็อกอินใหม่จริง ๆ; ยังไม่มีคำตอบแยกอาการ. ไม่ได้ยืนยันปัญหา token/session หมดอายุ
และยังไม่ได้แก้ปุ่มหรือเพิ่ม auth-status endpoint. งานต่อไปหากได้รับมอบหมายคือ
ตรวจสถานะล็อกอินจาก backend และแสดง UI ตามสถานะ โดยไม่ส่ง credential/token
ไปยัง browser.

**การเปลี่ยนแปลงครั้งนี้:** บันทึกผลตรวจใน daily log และอัปเดต `00_INDEX.md`
ตามคำขอผู้ใช้ โดยใช้โฟลเดอร์ `.notes/` ที่มีอยู่เดิม. ไม่มีการแก้ runtime code,
commit, deploy หรือทดสอบล็อกอินบัญชีจริงเพิ่มเติม.


## 2026-09-20 — Auth, model/effort and real AI Deck rename

Implemented the user-approved login status and chat settings changes, then renamed source directory/Compose project/services/runtime paths/branding to ai-deck. Updated deploy registry, updater/vendor scripts, active docs and Homepage. Kept legacy home volume explicitly external, provider secret keys, work bind, browser drafts/preferences and public port. Startup migrates old stack-owned hooks/statusLine idempotently. MIGRATION.md covers backup, verified volume, old-project stop without -v, future deployment and rollback.

Validation: 135 stack tests and 49 relevant repo tests passed with zero failures/errors/skips. Real Chrome checks cover signed-in/signed-out/unknown buttons, model/effort payloads and phone layout. Native arm64 app/nginx builds, offline startup and actual CLI catalog/auth checks, nginx -t, Compose rendering, syntax and doc-drift checks passed. Independent read-only review found no concrete correctness issue. Screenshots reviewed. No NAS deployment, real login, paid turn, native amd64 build, commit or push; existing uncommitted work preserved.


## 2026-09-20 — Previous task closed; status-bar follow-up opened

User requested notes/index completion. Login/model-effort and ai-deck rename work recorded above; 184 tests passed, no deployment/commit/push. User then reported Claude Code status bar not working and Codex status bar absent in AI Desk. Investigation opened; preserve no-deploy constraint.


## 2026-09-20 — Web quota stuck: diagnosis and local fix

User clarified web header, not Terminal status line: Claude numbers frozen despite starting Chat, Codex header absent. Read-only SSH inspection found ai-deck already deployed, old Claude snapshot age325160s, and both provider routes returning the same Claude data. No live config changes/restarts/deployment performed.

Connected Claude native rate_limit_event/unifiedWindows to atomic per-window Chat snapshots and quota SSE updates, merging freshest Terminal/Chat readings through the API. Added Codex native account/rateLimits/read metadata with bounded requests/cache and provider isolation. Verified actual read-only Codex response (40% 5h,45% week at inspection); no paid model call. Stale/expired data now shows a dash plus stale, missing/error data is explicit, and a partial update cannot make another old window look fresh. Added mobile clipping regression after screenshot review.

Validation: 143 stack tests, native app/nginx image builds, offline container startup/Claude quota persistence/API/Codex unavailable-isolation checks, JS/Python/shell syntax and diff checks. Real Chrome tests cover both providers, changing values, staleness/expiry and header controls at390px. Independent review found no concrete issue. README, index and screenshots updated. Fix remains local; no deploy/commit/push. Unrelated vault edits left untouched.


## 2026-09-20 — ปิดงานและเพิ่มกฎบันทึก memory

ผู้ใช้สั่งจบงาน: อัปเดต daily log และ index memory ของ ai-deck เรียบร้อย งานแก้โควตาหน้าเว็บผ่าน 143 tests ตามผลตรวจล่าสุด; ชุดแก้ยังอยู่ในเครื่อง ไม่ได้ deploy/commit/push โดยผู้ช่วย และไม่ได้แก้ข้อมูล NAS งานถัดไปหากผู้ใช้สั่งคือ deploy ชุดแก้และตรวจหน้าเว็บจริง

เพิ่มกฎถาวรใน root CLAUDE.md และ AGENTS.md: เมื่อผู้ใช้บอก “จบงาน” ให้อัปเดต `<stack>/.notes/daily_log.md` และ `<stack>/.notes/00_INDEX.md` เสมอก่อนตอบปิดงาน แม้ไม่มี structural change ไม่ต้องขอให้ผู้ใช้ย้ำ และห้ามลง root .notes หากทำหลาย stack ต้องอัปเดตทุก stack ที่เกี่ยวข้อง ตรวจเนื้อหา/ตำแหน่งกฎและบันทึกแล้ว การปิดงานรอบนี้เปลี่ยนเฉพาะเอกสาร ไม่รันชุดทดสอบแอปซ้ำ


## Git delivery — 2026-09-20

- Implementation commit `0f1d3c1` pushed to `origin/main`; remote HEAD verified with `git ls-remote`.
- Fresh pre-commit verification: 143 stack tests + 49 relevant repository tests = 192 passed, zero failures/errors/skips. Staged diff checked; no runtime credentials or unrelated vault change included.
- No deployment performed. The web-quota fix still requires a separately authorized NAS deployment.
- `secrets/vault.sops.yaml` remains modified locally from unrelated work and was intentionally left uncommitted.

User requested commit + push. Delivered AI Deck rename/features/quota fixes and closing-memory rules in `0f1d3c1` (`feat(ai-deck)!: rename stack and fix chat status`). This follow-up memory entry records the verified push result.
