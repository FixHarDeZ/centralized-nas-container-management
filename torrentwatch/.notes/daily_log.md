### 2026-08-02 — ประวัติ H&R + แก้ relogin fail บางรอบ

**relogin fail (สาเหตุจริง)**: APScheduler รัน job คนละ event loop กับ app connection ใน pool ของ `httpx.AsyncClient` ตัวเดิมจึงตายในลูปนั้น (`RuntimeError: unable to perform operation on <TCPTransport closed=True ...>`) เดิม `relogin()` ลองครั้งเดียวแล้วคืน False ทำให้ scheduler ยกเลิกทั้งรอบ (0s, 0 entries)
- ใหม่: ล้ม 1 ครั้ง = ทิ้ง client เก่า (`aclose()`) สร้างใหม่ด้วย `_new_client()` แล้วลองอีกรอบ
- ที่ล้มเป็นบางรอบ (ไม่ใช่ทุกรอบ) เพราะขึ้นกับว่ายังมี keepalive connection จาก loop ของ app ค้างใน pool ตอน job เริ่มหรือเปล่า — ไม่แตะ `keepalive_expiry` (default 5s สั้นกว่าที่จะไปตั้งเอง)
- เก็บเหตุผลไว้ที่ `scraper.last_login_error()` แล้วใส่ลง `box["error"]` หน้า "รอบทำงาน" จะขึ้น `relogin failed — scrape aborted (RuntimeError: ...)` ไม่ต้องไปเปิด docker logs
- self-check ใหม่ใน `scraper.py` (`__main__`): stub `_login` ให้ล้มครั้งแรก ต้องได้ True และ client ต้องถูกเปลี่ยนตัว

**ประวัติ H&R**: แท็บ H&R เพิ่มปุ่มสลับ 2 มุมมอง (`#hr-view`) — "กำลัง seed" (ของเดิม, ดึงสด) กับ "ประวัติ" อ่าน `GET /api/hr/history?limit=` (= `db.hr_fix_recent`, cap 500)
- แบ่งเป็น "รอพี่กดใน Telegram" (`pending`/`del_asked`/`del_confirm`) กับ "จบแล้ว"
- `_hrFixRow` แสดง `note` แล้ว (มีใน DB มานานแต่ UI ไม่เคยโชว์) — `note` นี่แหละที่แยก "รอยืนยันลบ" ออกจาก "แจ้งเฉยๆ เพราะโหลดจากมือถือ"
- แก้ที่มาของ note ว่าง: `hr_fix_set_status()` ถ้าไม่ส่ง note จะ **ล้างของเดิม** ตอนนี้ทุก branch ใน `check_vanished`/`check_cleared` เขียน note เสมอ รวมถึง 2 branch ที่ยังไม่ตัดสิน (`ถาม Download Station ไม่ได้ — รอรอบหน้า`, `ไม่มีชื่อเรื่องให้เทียบกับ DS — รอรอบหน้า`)
- chip `note` ตัดที่ 60 ตัวอักษร (ข้อความเต็มอยู่ใน tooltip) — `_hrFixRow` ใช้ร่วมกับแท็บรอบทำงาน ชื่อไฟล์ .torrent ยาวๆ จะกลืนทั้งแถวบนมือถือ
- `hr_fixes` ไม่โดน cleanup 7 วัน (`cleanup_old_records` ลบแค่ `torrents`, `cleanup_old_runs` ลบ `runs`) ประวัติจึงอยู่ยาว

verify: self-check `scraper.py` และ `hr_fix.py` ผ่านบน image จริง, deploy แล้ว, `/api/hr/history` คืนข้อมูลจริงพร้อม note

### 2026-07-31 (เพิ่มเติม 5) — verify path ใหม่บน production

- trigger รอบอ่าน myhr เองไม่รอ 21:10 → `2378096` seed ครบหลุดจากหน้า, ไม่มี task ใน DS, ส่ง Telegram แจ้งให้ลบที่ client อื่น, ไม่มีคำถามลบ. DB: status `cleared` note `"ไม่มี task ใน Download Station — แจ้งให้ลบที่ client อื่น"`
- **วิธี trigger เอง**: endpoint `POST /api/hr/notify` ติด basic auth (`BASIC_AUTH_USER/PASS`) เรียกจากใน container ก็โดน 401 → รัน scheduler ตรงแทน แต่ต้อง `await scraper.init()` ก่อน ไม่งั้น global `_client` เป็น None แล้ว login พังด้วย `'NoneType' object has no attribute 'get'`:

```
docker exec torrentwatch python -c "
import asyncio,scraper,scheduler
async def m():
    await scraper.init(); print(await scheduler.check_hr(force=True)); await scraper.close()
asyncio.run(m())"
```

- ยังไม่เคยรันจริง: path ลบจริง (เจอ task ใน DS → ปุ่มยืนยัน 2 จังหวะ → `FileStation.Delete` ลบถาวร)

### 2026-07-31 (เพิ่มเติม 4) — เคส "ไม่มี task ใน DS" เปลี่ยนจากเงียบเป็นแจ้ง Telegram

- เดิม: ไม่เจอ task = set `cleared` แล้วเงียบ ผู้ใช้ไม่รู้ว่าต้องไปลบเองที่ client อื่น
- ใหม่: ส่ง Telegram แบบไม่มีปุ่ม (`telegram_notify.notify_hr`) ว่า seed ครบพ้น H&R แล้ว ไม่มี task ใน Download Station โหลดจาก client อื่น (เช่นมือถือ) ให้ลบที่ client นั้น
- note ใน `hr_fixes` เปลี่ยนเป็น `"ไม่มี task ใน Download Station — แจ้งให้ลบที่ client อื่น"` และนับรวมใน `done` เพราะไฟล์ถือว่าจบรอบแล้วจริง
- ส่ง Telegram อย่างเดียว ไม่ส่ง LINE (ตามที่ผู้ใช้ขอ) และไม่เช็คผลส่ง — ไม่มี action ค้างให้ retry snapshot ถูกลืมทันที ต่างจากเคส `prompt_delete` ที่ต้องเก็บไว้ retry
- self-check: `hr_fix self-check OK: 4 prompt(s), 2 notice(s)` EXIT=0 บน image จริง, deploy แล้ว

### 2026-07-31 (เพิ่มเติม 3) — กันเคส snapshot ไม่มีชื่อเรื่อง

- `check_vanished` ใช้ `title = snap["title"] or (fix["title"] if fix else site_id)` ถ้า snapshot ไม่มี title และไม่มีแถวใน `hr_fixes` จะได้ `title == site_id` ซึ่ง `dsm.find_task` ไม่มีทาง match → ไฟล์ถูกตัดทิ้งเป็น "ไม่ได้อยู่ใน DS" แล้วลืม snapshot = หายเงียบแบบเดียวกับบั๊กที่ path นี้เกิดมาเพื่อแก้
- แก้: ถ้า `title == site_id` ให้ทำเหมือนเคส DS ติดต่อไม่ได้ — ไม่ตัดสิน เก็บ snapshot ไว้รอบหน้า (ไม่มีชื่อให้เทียบ = miss ไม่ได้พิสูจน์อะไร)
- self-check เพิ่มเคส title ว่าง: รอบนั้น return 0 และแถวยังอยู่ใน `hr_seen` (`hr_fix self-check OK: 4 prompt(s), 1 notice(s)` EXIT=0 บน image จริง)
- deploy แล้ว container ขึ้นปกติ (`import dsm` ไม่พัง), `hr_seen` ยัง 6 แถว, `hr_fixes` ยัง 9 แถว `fixed` ค้างเดิม

### 2026-07-31 (เพิ่มเติม 2) — ไม่ถามลบไฟล์ที่ไม่ได้โหลดผ่าน Download Station

- โจทย์จากผู้ใช้: บาง torrent โหลดจากมือถือ ไม่ได้ผ่าน DS ของ NAS พอ seed ครบไม่ควรถามลบ (เราไม่มี task และไม่มีไฟล์ให้ลบ)
- `check_vanished` เช็ค DS **ก่อนถาม** ด้วย `dsm.find_task()` ตัวเดียวกับที่ `_resolve` ใช้ (ต้องตรงกัน ไม่งั้น skip ผิดตัว) ดึง task list ครั้งเดียวต่อรอบ ผ่าน `hr_fix.ds_tasks()` และเฉพาะตอนมีแถวที่ครบจริง
- 3 ทาง ไม่ใช่ 2: **เจอ task** = ถามตามเดิม / **ไม่มี task** = set `cleared` + note "ไม่มี task ใน Download Station — ไม่ถามลบ" ไม่ถาม ลืม snapshot / **DS ต่อไม่ได้ (`DsmError`)** = ไม่ตัดสินอะไร คา snapshot ไว้รอบหน้า (fail-open ไม่ได้ เพราะ prompt จะไปจบที่ `del_failed` ซึ่ง terminal อยู่นอก retry set = ไฟล์ที่อยู่ใน DS จริงจะไม่ถูกถามอีกเลย)
- **ไม่ยัด logic นี้เข้า `prompt_delete`** เพราะ `check_vanished` อ่านค่า `False` ว่า "คา snapshot ไว้ retry" ไฟล์จากมือถือจะค้างวนตลอดกาล
- guard นี้ **ใช้เฉพาะ flow ลบ**: `hr.fix_candidates()` ใช้สัญญาณ "tracker ไม่เห็น client" เดียวกันเป็น trigger auto-fix ห้ามให้ guard ไปโดน
- self-check ใน `hr_fix.py` เพิ่ม 3 เคส (ไม่มี task / DS ล่ม / มี task) stub `ds_tasks` แบบเดียวกับ `telegram_notify.send_buttons`. รันบน image จริง: `hr_fix self-check OK: 4 prompt(s), 1 notice(s)`
- ข้อมูลจริงตอนนี้: 6 แถวใน `hr_seen` ไม่มี task ใน DS สักอัน และ 3 แถวค้างที่ ~38.4 ชม. เท่ากัน = ตรงกับที่ผู้ใช้บอก (โหลดจากมือถือ หยุด seed) ไม่ใช่ความผิดปกติที่ต้องตาม

### 2026-07-31 (เพิ่มเติม) — ตรวจ match task ใน DS + กัน prompt หลุด

- **ตรวจว่า flow ลบใช้ได้จริงกับไฟล์ที่ไม่เคยผ่าน auto-fix หรือเปล่า** (`_resolve` match ด้วย `dsm.find_task(tasks, title, db.torrent_filename(title))` ซึ่งเดิมออกแบบมาสำหรับไฟล์ที่ `apply_fix` เขียน .torrent เอง). ผลบน NAS: `hr_seen.title` **ตรงเป๊ะ** กับ `torrents.title` และ scraper เขียนไฟล์ลง `/downloads` ด้วย `db.torrent_filename(t["title"])` เดียวกัน → DS echo กลับมาเป็น `uri` ตัวเดียวกัน ⇒ key ที่มีอยู่ใช้ได้ ไม่ต้องเพิ่ม match key ใหม่
- แต่ 6 แถวที่ snapshot ไว้ตอนนี้ **MISS ทั้งหมด** เพราะ DS ไม่มี task พวกนี้แล้วจริงๆ (`SYNO.DownloadStation.Task list` คืน `total=20` ทั้ง default และ `limit=-1` — ไม่ใช่ pagination). เคสนั้นจบที่ `del_failed` ตามตั้งใจ ไม่เดา path
- **แก้ bug ที่จะทำให้ไฟล์หลุดถาวร**: เดิม `check_vanished` เรียก `hr_seen_forget()` ก่อนตัดสิน ถ้า `prompt_delete` ส่ง Telegram ไม่ผ่าน (คืน `False`) snapshot หายไปแล้ว status ค้างที่ `cleared` และไม่มี path ไหนวนกลับมาอีก = bug เดิมกลับมาเงียบๆ. ย้าย `hr_seen_forget()` ไปอยู่เฉพาะ branch ที่จบงานจริง (ไม่เข้าเกณฑ์ / ผ่านด่านไปแล้ว / prompt สำเร็จ) และเปิดให้ status `cleared` retry ได้ (`_PRE_CLEAR + ("cleared",)`) โดยไม่ส่ง notice ซ้ำ
- self-check เพิ่มเคส Telegram ล่ม → ยังไม่ลืม snapshot, รอบถัดไปถามซ้ำสำเร็จ, รอบที่สามเงียบ. รันบน image จริงบน NAS: `check_vanished self-check OK: 3 prompt(s), 1 notice(s)`, `hr self-check OK`. deploy แล้ว

# TorrentWatch — Daily Log

## 2026-07-31 — Fix: ไม่มีคำถามลบไฟล์หลัง seed ครบ (แถวหายจาก myhr.php ก่อนถูก sample)

**อาการ (user):** ระบบไม่เคยถามลบไฟล์เลย ทั้งที่ `hr_delete_enabled=1`

**Root cause (verify บน NAS):**
- `hr_fixes` มี 9 แถว ค้างที่ `fixed` ทั้งหมด ไม่มีแถวไหนถึง `cleared`; ไม่มี site_id ไหนเหลืออยู่บน myhr.php แล้ว
- runs job `hr`: total 20 → 20 → 16 → 13 → 10 → 6 โดย `risky=0, hits=0` = แถวทยอยหายเพราะ seed ครบ (bearbit ลบแถวทันทีที่ครบภาระ)
- `check_cleared()` เจอ `row is None` แล้ว `continue` (ตั้งใจไว้ว่า "แถวหาย ≠ พิสูจน์ว่าสำเร็จ") → ค้าง `fixed` ตลอดกาล ไม่เข้า `stalled` ด้วย เพราะ `continue` ยิงก่อน
- ชั้นที่สอง: `prompt_delete` ถูกเรียกจาก `check_cleared` ที่วน `hr_fix_by_status("fixed")` เท่านั้น → ไฟล์ที่ seed ครบเองไม่เคยเข้าตาราง `hr_fixes` เลย ไม่มีวันได้คำถามลบ
- อ่านหน้า myhr วันละ 2 รอบ ส่วนสถานะ 48/48 โผล่แค่ช่วงสั้นๆ ก่อนแถวหลุด = sample ไม่ทันแทบทุกครั้ง

**Implementation:**
- `db.py`: ตาราง `hr_seen` (site_id PK, title, seeded_h, target_h, remaining_h, state, seen_at) + `hr_seen_snapshot/hr_seen_vanished/hr_seen_forget` + `hr_fix_add_cleared()` (แถว `cleared` สำหรับไฟล์ที่ไม่เคยผ่าน auto-fix)
- `hr.py`: `was_cleared(snap, tolerance_h=2.0)` — ครั้งสุดท้ายที่เห็นขาด ≤2 ชม. (หรือครบแล้ว) และ state ไม่ใช่ `hit` = ถือว่าพ้น H&R; tolerance ชดเชย sampling gap 12 ชม.
- `hr_fix.py`: `check_vanished(rows, settings)` — เทียบ snapshot กับหน้าปัจจุบัน, แถวที่หายและผ่านเกณฑ์ → set/insert `cleared` แล้วยิง `prompt_delete`; แถวที่หายทั้งที่ยังขาดเยอะ → log ทิ้ง; จบด้วย `hr_seen_snapshot(rows)`. `rows == []` (fetch fail — `parse_hr` คืน `[]` เหมือนกัน) return 0 ทันที กันอ่านเป็น "ครบทั้งหน้า"
- แจ้ง LINE/Telegram "พ้น Hit & Run" เฉพาะไฟล์ที่ผ่าน auto-fix (`fixed`/`stalled`) เท่านั้น ไฟล์ที่ seed ครบเองไปที่คำถามลบตรงๆ ไม่งั้นวันละสิบ push
- `scheduler.py`: เรียก `check_vanished` ต่อจาก `check_cleared` (อยู่เหนือ dedup `hr_last_digest` เหมือนเดิม)

**Verify:** `python hr.py` self-check ผ่าน + throwaway container test (`docker run --rm -v /tmp/twtest/torrentwatch:/app`) ครอบ 5 เคส: หน้าว่างไม่ถือว่าครบ, ขาด 20 ชม. ไม่ถาม, `hit` ไม่ถาม, ไฟล์ auto-fix ได้ทั้ง notice+prompt, สถานะ `deleted` ไม่ถูกถามซ้ำ

**ค้างไว้:** 9 แถว `fixed` เดิมยังค้างอยู่ (ไม่มี snapshot ย้อนหลัง) — ไฟล์พวกนี้ต้องลบเองใน DS ถ้าอยากลบ


## 2026-07-06 — Feature: แสดงผู้ปล่อยไฟล์ (uploader) บน card

**งาน:** user อยากเห็นเจ้าของ torrent ที่ปล่อยบน dashboard พร้อม design สวยๆ

**Implementation (end-to-end):**
- `scraper.py`: เปิดใช้ `COL_UPLOADER = 11` (เดิม note ไว้ unused) — parse anchor text ของ td col 12, fallback → img alt/title → cell text, cap 60 chars, เพิ่ม `"uploader"` ใน dict ที่ `_parse_row` คืน
- `db.py`: เพิ่มคอลัมน์ `uploader TEXT DEFAULT ''` ใน CREATE TABLE + migration (`ALTER TABLE torrents ADD COLUMN`) + INSERT/UPDATE ใน `upsert_torrent`. UPDATE ใช้ `COALESCE(NULLIF(?, ''), uploader)` กันเขียนทับชื่อเดิมด้วยค่าว่างถ้า parse พลาดรอบถัดไป. `get_torrents`/`history`/`search` เป็น `SELECT *` อยู่แล้ว → ไหลไป API ฟรี
- `static/app.js`: `uploaderHTML` chip (`bi-person-badge` + ชื่อ) render ใต้ stats row ใน `cardHTML` (แสดงเฉพาะเมื่อมี `t.uploader`)
- `static/style.css`: `.tw-card-uploader` pill chip (accent-dim bg / accent text, rounded 999px, ellipsis overflow) — ใช้ CSS vars ปรับตาม theme

**Verify:** parse logic ผ่าน throwaway test 4 เคส (username+icon, image-only→alt, anonymous ว่าง). Live NAS verify ผ่าน `/api/debug/html` หลัง deploy

## 2026-07-05 — Fix: card size badge showed "N คน" instead of file size

**อาการ:** thumbnail overlay badge โชว์ "0คน"/"45คน" แทนขนาดไฟล์ (GB/MB)

**Root cause (probe live บน NAS ผ่าน authed scraper session — sandbox บล็อก bearbit):** bearbit เพิ่มคอลัมน์ `ผู้ปล่อยไฟล์` (uploader) ต่อท้าย table แล้วดันทุกคอลัมน์ตั้งแต่ `วันลง` เป็นต้นไปเลื่อนซ้าย 1 ช่อง (col 6→11 แทน 7→11 เดิม) — `COL_SIZE` เดิม (8) จริงๆ ชี้ไปที่ col `เสร็จ` ("N คน" = completed count) แทน `ขนาด`, ส่งผลกระทบ `COL_COMPLETED`/`COL_SEEDS`/`COL_LEECHES` ด้วยเช่นกัน (ผิดทั้งชุด ไม่ใช่แค่ size)

**Fix (`scraper.py`):** เลื่อนค่าคงที่ `COL_DATE/COL_SIZE/COL_COMPLETED/COL_SEEDS/COL_LEECHES` ลง 1 (7→6, 8→7, 9→8, 10→9, 11→10) ที่จุดเดียว — แก้ root cause ครอบทั้ง 4 field พร้อมกัน ไม่ใช่ patch เฉพาะ size

**Verify:** probe script (`docker exec` python ยิง `viewbrsb.php` ผ่าน authed session) ยืนยัน column header ตรงกับ index ใหม่ + trigger manual scrape (`scheduler.trigger_now()` ตรงๆ ในคอนเทนเนอร์ ข้าม nginx basic auth) → 47 entries รีเฟรช → user ยืนยัน dashboard โชว์ขนาดไฟล์ถูกแล้ว

**Gotcha ใหม่:**
- Synology sshd ไม่รองรับ scp subsystem — ใช้ `ssh nas "cat > file" < local_file` แทน
- `sudo` ผ่าน SSH ต้อง `-t` (allocate pty) ไม่งั้น "a terminal is required to read the password" แม้ pipe password เข้า stdin ก็ตาม (harness ไม่มี real TTY — ต้องส่งคำสั่งให้ user รันเองผ่าน `!`)
- container internal `localhost:5070` HTTP call จาก `docker exec` python เจอ `OSError: Cannot assign requested address` — เลี่ยงด้วยเรียก `scheduler.trigger_now()` ตรงๆ แทนยิง HTTP เข้าตัวเอง
- Non-fatal bug พบระหว่างทาง (ไม่ได้แก้ ไม่อยู่ใน scope): `sync_stickies error: 'sqlite3.Connection' object has no attribute 'rowcount'` ใน scheduler.py — sticky sync fail เงียบๆ ทุกรอบ scrape ที่มี sticky, ควรดูเพิ่มทีหลัง

## 2026-06-30 — Docker healthcheck
- **Healthcheck** เพิ่มใน `docker-compose.yml` (service `torrentwatch`): stdlib urllib ยิง `GET http://localhost:8000/api/status` (public endpoint) `interval 30s / timeout 10s / retries 3 / start_period 30s`. Hung uvicorn → Docker auto-restart. Deploy + verified `(healthy)` บน NAS.
- **⚠️ Regression แก้แล้ว:** PR #8 ลบ `torrentwatch/notify.py` ผิด (เข้าใจผิดว่า dead code). จริงๆ `line_notify.py` + `telegram_notify.py` ทำ `from notify import Notifier, LineCreds/TgCreds` (ดู INDEX banner) → **เป็น live dependency**. ตอน deploy รอดเพราะ build ใช้ cached `COPY` layer (ไฟล์ Jun 25 ยังอยู่ใน container) แต่ clean rebuild จะ ImportError. **Restore จาก git** (`git checkout b751a37 -- torrentwatch/notify.py`, identical กับ `shared/notify.py`). บทเรียน: เช็ค import ภายใน `line_notify`/`telegram_notify` เองด้วย ไม่ใช่ grep แล้ว filter ชื่อไฟล์ทิ้ง.
- หมายเหตุ: torrentwatch ยังไม่มี test suite → ไม่อยู่ใน CI matrix ใหม่ (`.github/workflows/tests.yml`).

---

## 2026-06-24 — Candidate 5: add SQLite backup via shared sqlite_backup module

เพิ่ม `_backup_job` ใน scheduler — ทุกวัน 03:00 สำรอง `/data/torrentwatch.db` ไป `/data/backups/torrent-*.db.gz`
(Online Backup API + gzip, retention 30 วัน). torrentwatch ไม่มี backup มาก่อน — นี่เป็น backup แรก.

## 2026-06-24 — ใช้ shared Notifier ใน _push/_send (transport-only)

ส่วนหนึ่งของงานรวม transport ข้าม stack → `shared/notify.py` (stdlib `urllib`, vendored ด้วย
`make sync-shared`, กัน drift ด้วย `tests/test_shared_sync.py`).

**torrentwatch:** สลับเฉพาะ body ของ `line_notify._push` และ `telegram_notify._send` →
`await asyncio.to_thread(_N.send, text)` (Notifier เป็น sync urllib รันนอก event loop).
สร้าง `_N` ระดับ module: LINE channel ใน line_notify, Telegram channel (plain text) ใน
telegram_notify. **ไม่ merge 2 module** — toggle LINE/Telegram แยกอิสระใน scheduler ยังทำงานเดิม.
`send_test_message`/`get_updates` คง httpx ไว้เพราะต้องคืน diagnostics ให้ dashboard.
vendored copy = `torrentwatch/notify.py` (`COPY . .` พามาอยู่แล้ว). import-smoke ผ่าน (stack ไม่มี test).

หมายเหตุ: formatter ที่ซ้ำกันระหว่าง line_notify/telegram_notify ยังเหลืออยู่ — เป็น candidate แยก ยังไม่แตะ.

⚠️ verify ถึงแค่ transport seam; ของจริงพิสูจน์ตอน scrape เจอ match ครั้งแรกหลัง deploy.

---

### Session Log Entry
**Timestamp:** 2026-06-17
**Title:** feat — free-leech % + multiplier columns + sitewide-free notify

- **Scrape:** `_parse_row` now reads `COL_FREE=3` (ฟรี → `free_leech`, keeps "NN%" text, drops "No") and `COL_MULTIPLIER=4` (คูณ → `multiplier`, keeps "xN", drops "No"). Other column indices unchanged (verified against existing FILES=5/DATE=7/SIZE=8/COMPLETED=9/SEEDS=10/LEECHES=11).
- **DB:** added `free_leech TEXT` + `multiplier TEXT` to `torrents` (CREATE + ALTER migration). `upsert_torrent` refreshes both on UPDATE (free status changes during sitewide events) and sets on INSERT. New generic `get_meta`/`set_meta` helpers for internal flags.
- **UI:** green `FREE NN%` badge + amber multiplier badge in card meta row (`app.js` + `.tw-badge-free`/`.tw-badge-mult` in `style.css`).
- **Sitewide-free notify:** `_parse_listing`/`scrape_source` return pre-filter `today_total`/`today_free` counts (ALL today non-sticky rows, before seed/threshold filter — avoids the high-seed/freeleech bias of the stored subset). Scheduler aggregates across sources; `_maybe_notify_all_free` pushes LINE+Telegram once/day when `today_free == today_total > 0`, deduped via `set_meta("free_all_notified_date", today)`.
- **UI:** click logo / "TorrentWatch" brand → กลับหน้าวันนี้ (listener บน `.tw-logo` ยิง click ของ today nav-item; `cursor:pointer`).
- **Deployed** 2026-06-17 (`./scripts/deploy.sh -s torrentwatch -y`) — rebuilt, clean boot, columns verified live in `/data/torrentwatch.db`.

### Session Log Entry
**Timestamp:** 2026-06-08
**Title:** fix — retention cleanup ไม่รัน หลัง restart

**Issue:** เก็บประวัติ > 7 วัน (พบ records 2026-05-31 ในขณะที่วันนี้ 2026-06-08)

**Root cause:** `_cleanup_job` schedule = `CronTrigger(day_of_week="sun", hour=3)` — รัน weekly Sun 03:00 เท่านั้น. Container restart วันนี้ 04:50 → ข้าม slot Sun 06-07 ไปแล้ว, ต้องรออีกถึง Sun 06-14.

**Fix (`scheduler.py`):**
1. เปลี่ยน cleanup cron จาก weekly → daily 03:00
2. รัน `_cleanup_job()` ทันทีหลัง `_scheduler.start()` ครอบ try/except — กัน restart ทำให้พลาด slot

**Verify:**
- DB หลัง restart: ไม่มี records < 2026-06-01 แล้ว (273 entries ของ 2026-05-31 ถูกลบ)
- ขอบเขต: keep 7 วันล่าสุด (2026-06-01 ถึง 2026-06-08)

**Docs sync:** `CLAUDE.md` + `.notes/00_INDEX.md` ปรับ schedule description (Sunday → ทุกวัน + startup)

---

### Session Log Entry
**Timestamp:** 2026-05-27
**Title:** fix — Local Download + NAS filename + dropdown font

**งานที่ทำ:**

**1. Cover image fix** ✅
- `.tw-card-thumb { object-fit: contain }` (was `cover`)

**2. Local Download fix** ✅ (หลายรอบ)
- Root cause: DSM Application Portal reverse proxy block/drop binary response
- Fixed: `StreamingResponse(iter([data]))` + `application/octet-stream` (ไม่ใช่ `x-bittorrent`) + ASCII-only Content-Disposition (ไม่มี RFC 5987 `filename*=UTF-8''...`)

**3. NAS filename Thai → `_`** ✅
- `db.torrent_filename()`: เปลี่ยนจาก strip non-ASCII → เก็บ Thai ไว้ strip แค่ path-unsafe chars (`\/:*?"<>|`)

**4. History dropdown cramped text** ✅
- `.tw-date-select`: เปลี่ยน `font-family: var(--font-mono)` → `var(--font-body)` เพราะ Geist Mono ไม่รองรับ Thai

**ไฟล์ที่แก้:**
- `static/app.js`: download handler (fetch+blob+AbortController 30s)
- `static/style.css`: object-fit contain + dropdown font
- `static/index.html`: bump cache versions
- `main.py`: StreamingResponse + octet-stream + simplified Content-Disposition
- `db.py`: torrent_filename() keep UTF-8

---

### Session Log Entry
**Timestamp:** 2026-05-21
**Title:** fix — sticky notify ไม่ทำงานเมื่อ enable หลัง scrape ไปแล้ว

**งานที่ทำ:**
- **Root cause:** `scheduler.py` เช็ค `is_new AND is_sticky` — แต่ sticky entries ถูก scrape เข้า DB ก่อน enable `notify_sticky` ทำให้ `is_new=False` ตลอด ไม่มี notification ออก
- เพิ่ม column `sticky_notified INTEGER DEFAULT 0` ใน `torrents` table (migration auto-run)
- เพิ่ม `db.get_unnotified_stickies(source_id)` + `db.mark_stickies_notified(ids)`
- เปลี่ยน scheduler ให้ query `is_sticky=1 AND sticky_notified=0` แทนพึ่ง `is_new` → จับ entries เก่าที่มีอยู่ก่อน enable notify, entries ที่ถูก promote โดย sync_stickies, และ entries ใหม่จริงๆ

**ไฟล์ที่แก้:**
- `db.py` (sticky_notified column + 2 new functions)
- `scheduler.py` (notify logic refactor)

---

### Session Log Entry
**Timestamp:** 2026-05-20 (session 4)
**Title:** feat — Sticky notification toggle

**งานที่ทำ:**
- เพิ่ม setting `notify_sticky_enabled = "0"` ใน `db.py` `_DEFAULT_SETTINGS`
- เพิ่ม `notify_sticky_new(source_url, entries)` ใน `line_notify.py` + `telegram_notify.py`
- `scheduler.py`: เก็บ `new_sticky_entries` เมื่อ `is_new AND is_sticky` แล้ว call notify เมื่อ setting เปิด
- UI: toggle "📌 Sticky Notify" ใน Notification card (index.html + app.js), version → 20260520c

**ไฟล์ที่แก้:**
- `db.py`, `scheduler.py`, `line_notify.py`, `telegram_notify.py`, `static/index.html`, `static/app.js`

---

### Session Log Entry
**Timestamp:** 2026-05-20 (session 3)
**Title:** Bug fix — Auto Sticky rows from viewno18sbx.php ไม่ถูก scrape

**Root Cause:**
`_parse_row()` detect sticky โดยดู `<img src>` ที่ match regex `sticky\.gif|heart\.gif|pinned\.gif` เท่านั้น แต่ `viewno18sbx.php` ใช้ text label **"Auto Sticky:"** แทน image → `is_sticky = False` → rows ถูก filter ออกด้วย date filter (sticky entries มี date เก่า)

**Fix (scraper.py:510):**
อัปเดต `is_sticky` detection เพิ่ม 3 check:
1. `img[src]` match `autosticky` (เผื่ออนาคต)
2. `img[alt]` match `sticky` (case-insensitive)
3. `NavigableString` match `auto\s*sticky` (จับ text node "Auto Sticky:")

**ไฟล์ที่แก้:**
- `scraper.py:510` — triple-check sticky detection

**หมายเหตุ:** ควรยืนยัน fix ด้วย `GET /api/debug/html?source_id=<id>` เพื่อดู HTML จริงของ sticky row บน viewno18sbx.php ว่าเป็น text node หรือ element อื่น

---

### Session Log Entry
**Timestamp:** 2026-05-20 (session 2)
**Title:** Clean up untracked dev artifact files

**งานที่ทำ:**
- ตรวจสอบ 5 untracked files ที่ค้างอยู่ใน working tree
- ยืนยันว่าไม่มีไฟล์ที่ tracked อ้างถึงเลย
- ลบทั้งหมด:
  - `torrentwatch/preview.html` — dev preview ที่สร้างช่วง redesign
  - `torrentwatch/bootstrap-icons-inline.css` — referenced เฉพาะ preview.html
  - `torrentwatch/check.png` — ไม่มี reference
  - `torrentwatch/preview-today.png` — ไม่มี reference
  - `maid-tracker/static/style.css.original` — backup ก่อน redesign
- Working tree clean หลังลบ

---

### Session Log Entry
**Timestamp:** 2026-05-20
**Title:** 6 Features — Cover Proxy, History Search, Global Search, Watched/Skip, Configurable Schedule, Stats Page

**Feature 1: Cover Image Proxy**
- **`scraper.py`**: `fetch_cover_bytes(cover_url)` — fetches image through authenticated session with Referer header + re-login retry on failure
- **`main.py`**: `GET /api/cover/{torrent_id}` — proxies cover bytes with `Cache-Control: max-age=3600`; guesses content-type from URL extension
- **`static/app.js`**: `cardHTML()` — added `data-proxy="/api/cover/{id}"` attribute + `onerror` fallback: try direct URL first, retry via proxy only on failure (zero overhead normally, transparent recovery on session expire)

**Feature 2: History Tab Search (within date) + Feature 9: Global Search (across all dates)**
- **`static/index.html`**: added `<input id="history-search-input">` search row in History panel (same style as Today tab)
- **`static/app.js`**:
  - `state.searchHistory` added to state
  - `loadHistory(date)` refactored: if `date=null` AND `q.length >= 2` → calls `GET /api/search?source_id=X&q=TEXT` (global); if `date=null` AND no query → shows placeholder; if date selected → filters client-side by `state.searchHistory`
  - Source chip click in history tab resets `state.searchHistory` + clears input
  - `history-date-select` onChange now calls `loadHistory(date || null)`
  - `history-search-input` input event calls `loadHistory(state.historyDate || null)`
- **`main.py`**: `GET /api/search?source_id=ID&q=TEXT&limit=50` — SQLite LIKE search, keyword-flagged, max 200 results
- **`db.py`**: `search_torrents(source_id, q, limit)` — `LIKE '%q%'` ordered by date DESC, seeds DESC

**Feature 3: Mark as Watched / Skip**
- **`db.py`**:
  - `watched_status INTEGER DEFAULT 0` added to CREATE TABLE + migration in `init_db()`
  - `mark_torrent_status(torrent_id, status)`: 0=none, 1=watched, 2=skip
- **`main.py`**: `POST /api/torrents/{id}/status` body `{status: 0|1|2}` → 204
- **`static/app.js`**:
  - `cardHTML()`: renders `tw-badge-watched` / `tw-badge-skipped` in `tw-card-dl-badges`; always renders the badges div (not conditional); card class includes `tw-card-watched` / `tw-card-skipped`; watch/skip buttons in actions row (eye + x-circle icons)
  - `attachCardActions()`: `.btn-watch` and `.btn-skip` handlers toggle status via API, sync badge + card class + sibling button state in-DOM (no re-render)
  - `_syncWatchBadge(card, status)`: removes old badge, appends new one

**Feature 4: Configurable Scheduler**
- **`db.py`**: added `scrape_interval_night: "30"` and `scrape_interval_day: "60"` to `_DEFAULT_SETTINGS`
- **`scheduler.py`**: `_minute_pattern(interval)` maps 15→"0,15,30,45", 20→"0,20,40", 30→"0,30", 60→"0"; `reload_scrape_job()` reads intervals from DB settings
- **`main.py`**: `PUT /api/settings` now calls `scheduler.reload_scrape_job()` after saving
- **`static/index.html`**: replaced static schedule text in Schedule card with two `<select class="tw-select-sm">` for night/day interval (options: 15/20/30/60 min)
- **`static/app.js`**: `loadSettings()` populates selects; save payload includes `scrape_interval_night` and `scrape_interval_day`

**Feature 7: Stats Page**
- **`db.py`**: `get_stats(source_id)` — aggregate query: total, dl_local, dl_nas, watched, skipped, by_category (top 20), by_date (last 14 days), by_source
- **`main.py`**: `GET /api/stats?source_id=ID` (optional source filter)
- **`static/index.html`**: Stats panel (`#panel-stats`) + 5th nav tab (สถิติ / bi-bar-chart-line)
- **`static/app.js`**: `loadStats()` + `_statsCard()` + `_statsBar()` helpers; renders summary grid (5 stat cards), 14-day activity bar chart, category breakdown, source breakdown — all CSS bars with dynamic widths

**CSS (`static/style.css`)**:
- `.tw-card-watched` / `.tw-card-skipped` — opacity dim + colored border overlay via `::after`
- `.tw-badge-watched` / `.tw-badge-skipped` — green/red badge tokens
- `.tw-action-btn.done-watch` / `.done-skip` — tinted action button states
- `.tw-select-sm` — styled `<select>` for schedule intervals
- Stats panel styles: `.tw-stats-scroll`, `.tw-stats-grid`, `.tw-stat-card`, `.tw-stats-section`, `.tw-stats-header`, `.tw-stats-bars`, `.tw-stats-bar-row`, `.tw-stats-bar-track`, `.tw-stats-bar-fill`, `.tw-stats-bar-count`

**Files Changed:** `db.py`, `scraper.py`, `main.py`, `scheduler.py`, `static/index.html`, `static/app.js`, `static/style.css`

---

### Session Log Entry
**Timestamp:** 2026-05-20
**Title:** Fix card thumbnail zoom (object-fit: cover → contain)

**ไฟล์ที่แก้ไข:**

- `static/style.css` — `.tw-card-thumb` เปลี่ยน `object-fit: cover` → `object-fit: contain` ให้รูปแสดงพอดีช่องแทนการ crop/zoom
- `static/index.html` — bump cache version `v=20260520a`

**หมายเหตุ:** เคยแก้แล้วครั้งก่อน (commit 366579e) แต่ redesign รอบล่าสุด revert กลับเป็น cover

---

### Session Log Entry
**Timestamp:** 2026-05-19
**Title:** UI Bug Fixes — Toast, Logo, Download Local

**ไฟล์ที่แก้ไข:**

- `static/index.html` — revert logo to Bootstrap icon `bi-broadcast`, bump cache version `v=20260519f`
- `static/style.css` — toast: `opacity+visibility` แทน `translateY`-only; logo: `flex-shrink:0`; `.tw-logo-icon` color accent
- `static/app.js` — download local: ลบ `pointer-events:none` (บล็อก `.click()`), blob size guard, DOM 30s cleanup, แสดง KB ใน toast

**Bugs แก้:**

1. Toast ค้างใน nav bar — translateY(80px) ไม่พอซ่อน (nav สูง 70px), แก้ด้วย opacity+visibility transition
2. Logo หาย — SVG/::before render ไม่ได้ cross-browser, revert เป็น Bootstrap icon ที่พิสูจน์แล้วว่าทำงาน
3. Download Local ไม่โหลดไฟล์ — `pointer-events:none` บน anchor บล็อก `.click()` dispatch

**Release:** v2.19.1

---

### Session Log Entry
**Timestamp:** 2026-05-18
**Title:** Database Schema — sort_order Migration for Source Reordering

**ไฟล์ที่แก้ไข:**

- **`db.py`**: 
  - `init_db()`: เพิ่ม migration `"ALTER TABLE sources ADD COLUMN sort_order INTEGER DEFAULT 0"` เข้าไป
  - `init_db()`: backfill `UPDATE sources SET sort_order = id WHERE sort_order = 0` สำหรับ existing sources
  - `get_sources()`: เปลี่ยน `ORDER BY id` → `ORDER BY sort_order ASC, id ASC`
  - `get_enabled_sources()`: เปลี่ยน `ORDER BY id` → `ORDER BY sort_order ASC, id ASC`
  - `add_source()`: คำนวณ `max_order = MAX(sort_order)` ก่อนแล้ว insert ด้วย `sort_order = max_order + 1` (new sources เข้าท้ายลิสต์)
  - `reorder_source()` (ใหม่): Swap sort_order กับ neighbor ตามทิศทาง "up"/"down"

**Verification:** test script ผ่านสี่ assertions:
1. Initial order [('a', 1), ('b', 2), ('c', 3)] ✓
2. Move first down: ['b', 'a', 'c'] ✓
3. Move last up: ['b', 'c', 'a'] ✓
4. All assertions passed ✓

**Commit:** `c40a36b` — feat(torrentwatch): add sort_order to sources — migration, backfill, reorder_source()

---

### Session Log Entry
**Timestamp:** 2026-05-18
**Title:** Frontend Redesign — Modern Minimal UI + Bottom Navigation

**ไฟล์ที่แก้ไข:**

- **`static/style.css`** (rewrite): Design system ใหม่ทั้งหมด — color palette เปลี่ยนจาก purple (`#818cf8`) เป็น indigo (`#6366f1`), bottom nav classes (`tw-bottom-nav`, `tw-nav-item`), card thumb ใช้ `object-fit: cover` + `box-shadow`, stats row ใหม่ (`tw-card-stats`, `tw-stat-val`, `tw-stat-sep`), kw-star badge absolute, settings ใช้ `tw-settings-scroll` + `tw-settings-body`, toast/go-top offset ใช้ `calc(var(--nav-h) + 12px)`
- **`static/index.html`** (rewrite): ย้าย nav จากด้านบน (`tw-tabs`) ไปด้านล่าง (`tw-bottom-nav`), search input ห่อใน `tw-search-wrap` พร้อม icon, settings รวม LINE + Telegram + Auto-DL เป็น Notification card เดียว, section title เปลี่ยนจาก `<div>` เป็น `<h2>` (accessibility), version bump → `v=20260518b`
- **`static/app.js`** (targeted edits): เปลี่ยน nav selector `.tw-tab` → `.tw-nav-item`, rewrite `cardHTML()` ใช้ stats row แทน badge row + `★ kw` absolute badge + detail link เป็น action ที่ 3, status badge แสดง `● scraping...` / `◉ idle`, `fmt()` helper สำหรับ k-format

**Bugs fixed ระหว่าง review:**
- `--surface1` stale CSS variable ใน Telegram result panel → แก้เป็น `--bg-elevated`
- Bottom nav ใช้ `position: sticky` ไม่ติดตอน scroll ลง → เปลี่ยนเป็น `position: fixed` + `calc(var(--nav-h) + 12px)` padding ใน list/settings
- `.tw-badge-cat` color `#818cf8` (old accent) → `#a5b4fc`
- `.tw-stat-sep` สี `var(--border)` มองไม่เห็น → `var(--text-dim)`
- `fmt()` ไม่ handle null/undefined/NaN → guard ด้วย `+n` + isNaN check

**Deploy:** `torrentwatch` container rebuilt + restarted บน NAS สำเร็จ

**Hotfix (หลัง deploy):** `object-fit: cover` → `object-fit: contain` บน `.tw-card-thumb` — ให้เห็นภาพทั้งหมดไม่ถูก crop (commit `366579e`)

---

### Session Log Entry
**Timestamp:** 2026-05-18
**Title:** Feature — Telegram Notification Support

**ไฟล์ที่แก้ไข:**

- **`telegram_notify.py`** (ใหม่): Telegram Bot API — `_send()`, `notify_keyword_matches()`, `send_test_message()`, `get_updates()` (ช่วย discover chat_id)
- **`config.py`**: เพิ่ม `TORRENTWATCH_TELEGRAM_BOT_TOKEN` + `TORRENTWATCH_TELEGRAM_CHAT_ID` env vars
- **`db.py`**: เพิ่ม `telegram_notify_keyword_enabled = "0"` ใน `_DEFAULT_SETTINGS`
- **`scheduler.py`**: import `telegram_notify`; อ่าน `telegram_notify_enabled` จาก settings; push Telegram หลัง LINE notify; เพิ่ม `telegram_configured` ใน `status()` dict
- **`main.py`**: import `telegram_notify`; เพิ่ม `POST /api/telegram/test` และ `GET /api/telegram/get-chat-id`
- **`static/index.html`**: เพิ่ม Telegram settings card (toggle, test button, get-chat-id button + result div); bump version string → `v=20260518`
- **`static/app.js`**: load/save `telegram_notify_keyword_enabled`; Telegram status hint; event handlers สำหรับ test + get-chat-id
- **`.env`**: เพิ่ม `TORRENTWATCH_TELEGRAM_BOT_TOKEN` (token ใส่แล้ว) + `TORRENTWATCH_TELEGRAM_CHAT_ID` (ต้องกรอก)

**วิธี Test:**

1. ใส่ Bot Token ใน `.env` แล้ว (เพิ่มแล้ว)
2. เปิด Settings → "ค้นหา Chat ID" → ส่งข้อความหา bot ก่อน → กดปุ่ม → copy chat_id มาใส่ `.env`
3. กด "ทดสอบส่ง Telegram" ตรวจสอบใน Telegram
4. เปิด toggle "เปิดใช้งาน" + บันทึก → จะส่งทุกครั้งที่พบ keyword match

---

### Session Log Entry
**Timestamp:** 2026-05-15
**Title:** Clean Code — Import hygiene, deduplication, private API elimination

- **`db.py`**: เพิ่ม `torrent_filename()` (shared utility), `clear_source_today()`, `clear_source_all()` (public API แทน `_conn()` ตรงๆ); เพิ่ม `import re` ที่ top
- **`main.py`**: ย้าย `re`, `quote`, `datetime`, `ZoneInfo` ขึ้น top; ลบ lazy imports ใน function body; ลบ `_torrent_filename` → `db.torrent_filename()`; `api_clear_*` ใช้ `db.clear_source_*`; `filter` param + `# noqa: A002`
- **`scraper.py`**: เพิ่ม `urlencode, parse_qs, urlunparse` ใน top import; ลบ lazy import ใน `_page_url`; fix COL alignment; extract `_is_torrent_content()` helper ลด duplicated logic 2 จุด
- **`scheduler.py`**: จัด import order (stdlib → third-party → local); ย้าย `urlparse` ออกจาก loop body; ลบ `import re` ที่ไม่ใช้; ลบ `_nas_filename` → `db.torrent_filename()`

---

### Session Log Entry
**Timestamp:** 2026-05-15
**Title:** Feature — Image Lightbox + Completed Downloads Sort

**Feature 1: Image display (bearbit style)**
- `style.css`: Changed `.tw-card-thumb` from `object-fit: cover` → `object-fit: contain` + `background: #000` — จะเห็นภาพทั้งหมดไม่ถูกครอป
- `style.css`: เพิ่ม lightbox overlay CSS (`.tw-lightbox`, `.tw-lightbox-img`, `.tw-lightbox-close`)
- `index.html`: เพิ่ม `<div id="lightbox">` overlay + close button
- `app.js`: เพิ่ม lightbox JS — click รูป (`[data-lightbox]`) → เปิด fullscreen; click overlay/close/Escape → ปิด
- `app.js`: เพิ่ม `data-lightbox` attribute บน `<img class="tw-card-thumb">` เพื่อ trigger lightbox

**Feature 2: Completed downloads (คนที่โหลดจบ) + sort**
- `scraper.py`: เพิ่ม `COL_COMPLETED = 9` — parse column 9 ของ bearbit (น่าจะเป็น completed/snatches count)
- `scraper.py`: parse และ return `completed` ใน dict ของ `_parse_row`
- `db.py`: เพิ่ม column `completed INTEGER DEFAULT 0` ใน CREATE TABLE + migration `ALTER TABLE`
- `db.py`: อัปเดต `upsert_torrent` — UPDATE และ INSERT รวม `completed`
- `db.py`: เพิ่ม `"completed": "completed DESC"` ใน `_sort_order()`
- `index.html`: เพิ่มปุ่ม sort "โหลดจบ" (data-sort="completed") ทั้ง Today และ History toolbar
- `app.js`: เพิ่ม `completedBadge` ใน `cardHTML()` — แสดงเมื่อ `completed > 0`
- `style.css`: เพิ่ม `.tw-badge-completed` (สีฟ้า #38bdf8) และ `.tw-completed-icon`

**หมายเหตุ**: COL_COMPLETED = 9 เป็น best guess จาก column ordering ของ bearbit — ถ้า scrape แล้วค่าเป็น 0 ทั้งหมด ให้เปลี่ยน column index ใน scraper.py

---

### Session Log Entry
**Timestamp:** 2026-05-12 11:19
**Title:** Sticky/Pinned Bug — Root Cause Analysis
**Details:**
- User reported newly pinned sticky torrents not being scraped (site shows 3, only 2 appear)
- Traced full flow: `scheduler → scraper.scrape_source → _parse_listing → _parse_row → db.upsert_torrent → db.sync_stickies`
- Found 4 distinct bugs causing sticky loss

---

### Session Log Entry
**Timestamp:** 2026-05-12 11:22
**Title:** Fix 1 — Default scrape_sticky changed from "0" to "1"
**Details:**
- [`db.py:13`](torrentwatch/db.py:13): Changed `_DEFAULT_SETTINGS["scrape_sticky"]` from `"0"` to `"1"`
- [`db.py:87-88`](torrentwatch/db.py:87): Added forced migration `UPDATE settings SET value='1' WHERE key='scrape_sticky' AND value='0'` — existing DBs with old default won't be updated by `INSERT OR IGNORE`

---

### Session Log Entry
**Timestamp:** 2026-05-12 11:23
**Title:** Fix 2 — Stickies now bypass seed/leech thresholds
**Details:**
- [`scraper.py:365-371`](torrentwatch/scraper.py:365): When `is_sticky=True`, entry is added to results immediately with `keyword_match` set, skipping `seeds==0` and `seed_min/leech_min` threshold checks
- Rationale: stickies are site-pinned for prominence — should not be filtered by arbitrary thresholds

---

### Session Log Entry
**Timestamp:** 2026-05-12 11:45
**Title:** Fix 3 — upsert_torrent UPDATE missing is_sticky/date_posted
**Details:**
- Discovered that a torrent previously scraped as non-sticky would never get promoted when bearbit later pins it
- [`db.py:206-213`](torrentwatch/db.py:206): UPDATE now includes `date_posted` and `is_sticky` columns (was only `seeds, leeches, last_updated_at`)
- [`db.py:166-172`](torrentwatch/db.py:166): Added promotion safety net in `sync_stickies` — entries in `seen_sticky_ids` with `is_sticky=0` get promoted

---

### Session Log Entry
**Timestamp:** 2026-05-12 11:55
**Title:** Fix 4 — Sticky detection regex typo: stickyt.gif → sticky.gif
**Details:**
- Original regex `stickyt\.gif` had an extra 't' — would only match `stickyt.gif`, not `sticky.gif`
- This explained why exactly 1 of 3 stickies was missing (2 used `heart.gif`, 1 used `sticky.gif`)
- [`scraper.py:400`](torrentwatch/scraper.py:400): Fixed to `sticky\.gif|heart\.gif|pinned\.gif`

---

### Session Log Entry
**Timestamp:** 2026-05-12 13:31
**Title:** Fix 5 — sync_stickies demotion tolerance for 1-time detection misses
**Details:**
- After fixes 1-4, all 3 stickies appeared on first scrape, but an old sticky disappeared on subsequent scrape
- Root cause: `sync_stickies` demoted immediately on single miss (set `date_posted=yesterday`)
- [`db.py:193-196`](torrentwatch/db.py:193): Demotion now only clears `is_sticky=0` without backdating `date_posted` — entry survives 1-2 missed detections, ages out naturally if truly un-pinned
- Added comprehensive debug logging in `_parse_row`, `_parse_listing`, `sync_stickies`, and scheduler for tracing

---

### Session Log Entry
**Timestamp:** 2026-05-12 14:38
**Title:** Created .notes/00_INDEX.md and daily_log.md
**Details:**
- Created `torrentwatch/.notes/` directory with project blueprint and daily log
- `00_INDEX.md` covers: overview, stack, file map, architecture decisions, known technical debt
- Formatted per Memory & Notion Sync Protocol for future Notion integration

---

### Session Log Entry
**Timestamp:** 2026-05-13 13:33
**Title:** Wired LINE Notifications — keyword match alerts now live
**Details:**
- [`config.py:18-20`](torrentwatch/config.py:18): Added `LINE_ACCESS_TOKEN` / `LINE_USER_ID` from env vars (`TORRENTWATCH_LINE_ACCESS_TOKEN`, `TORRENTWATCH_LINE_USER_ID`)
- [`scheduler.py:16`](torrentwatch/scheduler.py:16): Imported `line_notify` module
- [`scheduler.py:82-86`](torrentwatch/scheduler.py:82): `_do_scrape()` now captures `is_new` from `db.upsert_torrent()` and collects entries where `is_new=True AND keyword_match=True`
- [`scheduler.py:96-97`](torrentwatch/scheduler.py:96): Calls `line_notify.notify_keyword_matches()` per source when new keyword-matched entries are found
- [`scheduler.py:110-111`](torrentwatch/scheduler.py:110): Calls `line_notify.notify_round_summary()` at end of scrape cycle when `total_found > 0`
- [`env.example:122-126`](.env.example:122): Added `TORRENTWATCH_LINE_ACCESS_TOKEN` / `TORRENTWATCH_LINE_USER_ID` env var examples
- `line_notify.py` already had fully working `notify_keyword_matches()` and `notify_round_summary()` — just needed to be connected
- Docker compose already uses `env_file: ../.env`, so new vars are picked up automatically on next deploy

---

### Session Log Entry
**Timestamp:** 2026-05-13 14:05
**Title:** Added LINE toggle + test button in Settings UI
**Details:**
- [`db.py:15`](torrentwatch/db.py:15): Added `line_notify_keyword_enabled` to `_DEFAULT_SETTINGS` (default `"0"` — user must opt-in)
- [`line_notify.py:64-72`](torrentwatch/line_notify.py:64): Added `send_test_message()` — sends a test LINE message, returns `{"ok": True/False}`
- [`scheduler.py:57`](torrentwatch/scheduler.py:57): `_do_scrape()` now reads `line_notify_keyword_enabled` setting; both `notify_keyword_matches()` and `notify_round_summary()` are gated behind it
- [`main.py:17`](torrentwatch/main.py:17): Imported `line_notify`; added `POST /api/line/test` endpoint at line 330
- [`index.html:127-142`](torrentwatch/static/index.html:127): Added "LINE Notification" settings card with toggle switch + test button
- [`app.js:369`](torrentwatch/static/app.js:369): `loadSettings()` sets toggle state; save payload includes `line_notify_keyword_enabled`
- [`app.js:506-519`](torrentwatch/static/app.js:506): Test button handler — calls `POST /api/line/test`, shows toast on success/failure
- [`style.css:610-627`](torrentwatch/static/style.css:610): Added `.tw-btn-secondary` style for the test button

---

---

### Session Log Entry
**Timestamp:** 2026-05-14
**Title:** Fix scrape stuck-running bug + better progress display + category chip counts

**Scrape stuck-running bug fix (`scheduler.py`)**

- Root cause: `_do_scrape()` ไม่มี `try/finally` → ถ้า crash นอก per-source loop, `_scrape_status` ค้างที่ `"running"` ตลอด ทำให้ทุก click ตอบ `"already_running"` โดยไม่ทำอะไร
- [`scheduler.py`]: ครอบ body ของ `_do_scrape()` ด้วย `try/finally` → reset `_scrape_status="idle"` และ `_scrape_progress={}` เสมอ ไม่ว่าจะ crash

**Better scrape progress (`scheduler.py` + `app.js`)**

- [`scheduler.py`]: เปลี่ยน `source_label` จาก URL path fragment → ใช้ `source["label"]` (ชื่อจริงที่ user ตั้ง) เป็น fallback
- [`scheduler.py`]: `_scrape_progress` เพิ่ม field `source_idx` / `source_total` สำหรับแสดง N/M
- [`scheduler.py`]: `_update_progress()` รับ `source_idx` / `source_total` เพิ่ม
- [`scheduler.py`]: lambda `on_page` ใช้ default args (`_lbl`, `_idx`, `_tot`) แก้ closure bug ใน loop
- [`app.js`]: status badge แสดง `⟳ ชื่อ Source (1/2) — หน้า 3 พบ 15 รายการ`
- [`app.js`]: กด Scrape button → เรียก `updateStatusBadge()` ทันที → fast-poll 1.5s เริ่มเลย
- [`app.js`]: ลบ `setTimeout(() => btn.classList.remove("spinning"), 1500)` ออก → button spinning sync กับ status จริง (หยุดเมื่อ status = idle)

**Category chips with counts (`app.js`)**

- [`app.js`] `renderCategoryChips()`: นับ count per category จาก input list แสดงใน chip เช่น `JP ไม่เซ็น (8)`
- [`app.js`] `loadToday()`: restructure filter order — apply keyword/sticky/search ก่อน, ส่ง pre-category list ให้ `renderCategoryChips()`, แล้วจึง apply category filter → counts สะท้อน filter ที่ active อยู่จริง

---

---

### Session Log Entry
**Timestamp:** 2026-05-14
**Title:** Fix multi-source scrape: source 4 (Anime) ไม่เคย scrape ได้เลย

Root cause: `db.upsert_torrent`, `db.sync_stickies`, `line_notify.notify_keyword_matches` อยู่นอก per-source try/except → ถ้า source 1 (18+) throw ที่ขั้นตอนเหล่านี้ (เช่น LINE API timeout, DB error), loop หยุดเลย source 4 ไม่เคยเริ่ม

Diagnostic: เพิ่ม `GET /api/debug/parse-test/{source_id}` ชั่วคราว → confirm scraper parse ถูก (`entries_real_settings: 8`), `details.php` link มีอยู่, column mapping + date ถูกทุกอย่าง → ปัญหาอยู่ที่ scheduler loop ไม่ใช่ scraper

Fix (`scheduler.py`):

- wrap `db.upsert_torrent` per-entry ด้วย try/except → error ของ entry หนึ่งไม่กระทบ entries อื่น
- wrap `db.sync_stickies` ด้วย try/except แยก
- wrap `line_notify.notify_keyword_matches` ด้วย try/except แยก
- ผล: แต่ละ source ทำงาน independently ไม่ว่า source 1 จะ fail ที่ขั้นไหน source 4 ก็ยังวิ่งต่อได้

Fix (`scraper.py`):

- เพิ่ม fallback selector สำหรับ title link — ถ้าไม่เจอ `details\.php` จะหา anchor ที่มี `<b>` child และ `?id=\d+` ใน href (รองรับ listing pages อื่นที่ใช้ PHP filename ต่างกัน)
- viewno18sbx.php ใช้ `details.php` เหมือนกัน แต่ fallback ป้องกัน future sources

---

---

### Session Log Entry
**Timestamp:** 2026-05-14
**Title:** Fix first-scrape-of-day returning 0 items — stale connection after overnight idle

Root cause: `_fetch` จะ return `None` ทันทีเมื่อ connection exception เกิดขึ้น โดยไม่มี retry ทำให้ scrape รอบแรกหลัง pause 01:00-06:00 (5 ชั่วโมง idle) fail เงียบๆ 0 items ทั้งที่ bearbit มี torrent ใหม่ผ่าน filter เพียบ

Fix (`scraper.py`):

- `_fetch`: เมื่อเกิด transport exception → re-login แล้ว retry request 1 ครั้ง แทนที่จะ return `None` ทันที
- เพิ่ม `relogin()` function (`global _login_ok = await _login()`) สำหรับ scheduler เรียก

Fix (`scheduler.py`):

- `_do_scrape()`: เรียก `await scraper.relogin()` ทุกครั้งก่อนเริ่ม loop sources เพื่อ establish fresh session ก่อน scrape แต่ละรอบ
- ถ้า relogin fail → return ภายใน try block (finally ยัง reset `_scrape_status = "idle"` เสมอ)

---

---

### Session Log Entry
**Timestamp:** 2026-05-18
**Title:** Feature — Source Reorder (↑↓) + File Size Colored Badge

**Feature 1: Source Reorder**

- **`db.py`**:
  - `CREATE TABLE sources`: เพิ่ม `sort_order INTEGER DEFAULT 0` ใน DDL
  - migration loop: เพิ่ม `"ALTER TABLE sources ADD COLUMN sort_order INTEGER DEFAULT 0"`
  - backfill: `UPDATE sources SET sort_order = id WHERE sort_order = 0`
  - `get_sources()` + `get_enabled_sources()`: เปลี่ยน `ORDER BY id` → `ORDER BY sort_order ASC, id ASC`
  - `add_source()`: คำนวณ `max_order = MAX(sort_order)` insert ด้วย `sort_order = max_order + 1`
  - `seed_default_sources()`: เพิ่ม `sort_order` ใน INSERT ด้วย `enumerate(urls, start=1)`
  - `reorder_source(source_id, direction)` (ใหม่): swap sort_order กับ nearest neighbor ทิศ "up"/"down"
- **`main.py`**:
  - `from typing import Literal` เพิ่ม import
  - `SourceReorder(BaseModel)` model ใหม่: `direction: Literal["up", "down"]`
  - `POST /api/sources/{source_id}/reorder` endpoint ใหม่ — returns updated sources list
- **`static/app.js`**:
  - `renderSourcesList()`: เปลี่ยน `.map(s =>` → `.map((s, i) =>` + เพิ่ม ↑↓ chevron buttons
  - ↑ disabled เมื่อ `i === 0`, ↓ disabled เมื่อ `i === sources.length - 1`
  - event handler `.src-reorder`: เรียก `POST /api/sources/{id}/reorder` → `await loadSources()` → `loadSettings()`

**Feature 2: File Size Colored Badge**

- **`static/style.css`**:
  - `.tw-badge-size` — `font-size: 12px; font-weight: 700; padding: 2px 7px` (companion class กับ `.tw-badge`)
  - `.tw-badge-size-sm` — gray `rgba(107,114,128,0.15)` / `#9ca3af` (MB หรือ <1 GB)
  - `.tw-badge-size-md` — amber `rgba(245,158,11,0.15)` / `#f59e0b` (1–4.9 GB)
  - `.tw-badge-size-lg` — red `rgba(239,68,68,0.15)` / `#ef4444` (≥5 GB)
  - `.tw-btn-icon:disabled` — `opacity: 0.3; cursor: not-allowed; pointer-events: none` (bonus fix)
- **`static/app.js`**:
  - `sizeClass(s)` helper (ก่อน card renderer section): parse GB จาก string → return tier class
  - `cardHTML()`: เปลี่ยน `tw-stat-sep + tw-stat-lbl` → `<span class="tw-badge tw-badge-size ${sizeClass(...)}">`

**Commits:**
- `c40a36b` feat(torrentwatch): add sort_order to sources — migration, backfill, reorder_source()
- `53b1b1b` fix(torrentwatch): seed_default_sources with sort_order + add sort_order to CREATE TABLE DDL
- `f6592a6` feat(torrentwatch): add POST /api/sources/{id}/reorder endpoint
- `8110d2b` fix(torrentwatch): use Literal type for direction + explicit status_code=200
- `2c85ea0` feat(torrentwatch): source reorder ↑↓ buttons in Settings
- `50b5fc3` feat(torrentwatch): file size colored badge — gray/amber/red by tier

**Pushed to:** `origin/main` (15cbe43 → 50b5fc3)

---

### Pending / Next Steps

- [ ] Cover image โหลดตรงจาก bearbit CDN — ถ้า session expire รูปแตกพร้อมกัน

---

## 2026-06-30 — Fix: download button broken (bearbit unread-PM gate)

**อาการ:** ปุ่ม Download Local/NAS คืน `502 {"detail":"Failed to fetch torrent file from site"}`

**Root cause (diagnose จาก container logs + live probe บน NAS):**
- bearbit เปลี่ยน endpoint: `download.php?id=X` เดิม **ตาย → 404**
- ลิงก์ใหม่ในหน้า detail = `downloadnew.php?id=X&genid=..&dltm=..&dlt=<token>&filename=..` (token สดต่อ session, `resolve_download_url` หาเจออยู่แล้วผ่าน fallback regex)
- แต่ `downloadnew.php` คืน **`200 text/html charset=windows-874`** = หน้า HTML block ไม่ใช่ไฟล์ .torrent
- เนื้อหา block page (ไทย): "คุณมีจดหมายใหม่ยังไม่ได้อ่าน กรุณาอ่านจดหมายก่อนดาวน์โหลด" → **bearbit gate การโหลดไว้หลัง inbox PM ที่ยังไม่อ่าน** (PM broadcast VIP/Donate)
- ยืนยัน: `GET inbox.php` (เคลียร์ unread flag) แล้วยิง `downloadnew.php` ซ้ำ → `application/x-bittorrent` len 78421 ✅

**Fix (`scraper.py` `fetch_torrent_bytes`):** เมื่อ resolved URL คืนไม่ใช่ torrent → `GET /inbox.php` เคลียร์ gate แล้ว retry resolved URL อีก 1 ครั้ง. self-heal ทุกครั้งที่ bearbit ส่ง PM ใหม่

**Verify:** `GET /api/download/local/11339` ผ่าน basic auth ใน container → `len 78421 magic d8:announce` (valid bittorrent) ✅

**Gotcha ใหม่:** stored `torrent_url` (`download.php?id=`) ใช้ไม่ได้แล้ว — โหลดต้องผ่าน resolve detail page เพื่อเอา token `dlt` สด เสมอ. inbox PM ที่ยังไม่อ่าน block การโหลดทั้งหมด.

### Cover image 502 (same session)

**อาการ:** `/api/cover/{id}` คืน 502 — รูปปกแตกทั้งหน้า
**Root cause:** `cover_url` ห่อด้วย proxy `images.weserv.nl?url=...img.messi-bearbit.xyz...`. weserv เพิ่งบล็อก domain นั้น → `400 {"status":"error","message":"Domain or TLD blocked by policy"}`. host จริง `img.messi-bearbit.xyz` เสิร์ฟตรงได้ (`200 image/jpeg`)
**Fix:** `_unwrap_weserv()` ใน scraper.py — ถ้า cover_url เป็น weserv ดึง inner `url=` param มา fetch ตรง (แก้ที่ `fetch_cover_bytes` จุดเดียว ครอบทั้ง row เก่า+ใหม่)
**Note:** inner เสิร์ฟรูป full-size (~1.2MB) — weserv เคย resize 200x280 ให้. หนักขึ้นแต่ใช้ได้. ถ้า bandwidth สำคัญค่อยหา proxy resize อื่น

---

## 2026-07-03 — Fix: download 502 อีกรอบ (bearbit ad-gate interstitial ใหม่)

**อาการ:** ปุ่ม Download Local คืน `502 {"detail":"Failed to fetch torrent file from site"}` (อาการเดิม, สาเหตุใหม่)

**Root cause (diagnose live บน NAS ผ่าน probe reuse authed session ของ scraper):**
- bearbit เพิ่ม **ad-gate interstitial** ครอบ `downloadnew.php` — resolve URL คืน `200 text/html charset=windows-874` (~26KB) หน้า countdown แทน .torrent
- หน้านั้นมีปุ่มเขียว `a#bbDlBtn` href = `downloadnew.php?...&adok=1&adt=<unlock_ts>.<hmac>` (token สดต่อ view)
- countdown 5 วิ (Script 20) เป็น client-side อย่างเดียว **แต่ server บังคับ delay จริง** ผ่าน cookie `bb_vlast=<uid>|<ts>` ที่ตั้งตอนดูหน้า interstitial
- ยิง adok URL ทันที (< 5 วิ) → คืน HTML หน้าเดิมซ้ำ. **รอ ≥5 วิ ระหว่าง GET interstitial กับ GET adok** → `application/x-bittorrent` len 1084159 `d8:announce` ✅
- **adt timestamp เชื่อไม่ได้** — ทดสอบรอจน `now > adt` ก็ยัง fail ถ้า wall-clock ระหว่าง 2 request ห่างไม่ถึง 5 วิ. เกตคือ delta เวลา ไม่ใช่ absolute adt

**Fix (`scraper.py`):** เพิ่ม helper `_fetch_via_gate(url, referer, allow_inbox=True)` + const `AD_GATE_WAIT_S = 7`. flow: GET resolved URL → ถ้าไม่ใช่ torrent หา `#bbDlBtn`/`a[href*=adok=1]` → `asyncio.sleep(7)` → GET ปุ่ม (Referer=interstitial URL) → torrent. ถ้าไม่เจอ ad-gate ตกไป inbox-gate เดิม (retry ครั้งเดียว allow_inbox=False กันลูป). `fetch_torrent_bytes` เรียก helper แทน block resolve+inbox เดิม

**Verify:** deploy จริง → `GET /api/download/local/12184` (authed) ใน container → `HTTP 200 application/octet-stream size 19296 d8:announce` ✅ + function-level probe `fetch_torrent_bytes` → 1084159 bytes ✅

**Gotcha ใหม่:** ดาวน์โหลดตอนนี้ **ช้าลง ~7 วิ/ไฟล์** เพราะต้องรอ ad-gate countdown. ทุก download ผ่าน interstitial แล้ว (ไม่ใช่ edge case). ถ้า bearbit ขยับ selector `#bbDlBtn` หรือเพิ่มเวลา countdown ต้อง re-probe live (sandbox บล็อก bearbit)

---

## 2026-07-26 — Feature: Hit & Run monitor (แจ้ง LINE + Telegram)

**บริบท:** bearbit เปิดระบบ H&R — ทุกไฟล์ที่โหลดต้อง seed **48.0 ชม.** ภายในกรอบ 168 ชม. (24 ชม.แรก = ผ่อนผัน → เตือน → ผิด). ค้างผิดครบ **18 ไฟล์ = ล็อกการโหลด**. บัญชีตอนเริ่มงาน: ผิดแล้ว 2, เตือน 12, กำลัง seed 3

**Root cause ที่ทำให้โดน (ไม่ใช่บั๊ก torrentwatch):** Download Station (transmission) บน NAS ตั้ง `"ratio-limit": 0` + `"ratio-limit-enabled": true` → task หยุด seed ทันทีที่โหลดเสร็จ, `idle-seeding-limit-enabled`/`interval-seeding-limit-enabled` = false, DS `download_seeding_interval=-1`, `resume/` ว่าง = ไม่มีอะไร seed อยู่เลย. **ฝั่ง DSM ผู้ใช้จัดการเอง** (ตั้ง seeding interval ~3000 นาที ผ่าน DSM UI ไม่ใช่แก้ settings.json ตรงๆ เพราะ transmission เขียนทับตอน stop package)

**ที่ทำในรอบนี้ — monitor ฝั่ง torrentwatch:**
- `hr.py` (ใหม่): `parse_hr()` อ่าน `table.t` ของ myhr.php → td0 ชื่อ+`details.php?id=` · td1 เวลาโหลดเสร็จ · td2 `"3.0 ชม. / 48.0 ชม."` · td3 ที่ยังขาด · td4 `"180.4 ชม. ที่แล้ว"` · td5 `span.bd.<state>` (`hit`/`warn`/`ok`/`pause`)
- **slack** = `(finished_at + 168h - now) - remaining_h` = เวลาเหลือจริง ติดลบ = ต่อให้เริ่ม seed เดี๋ยวนี้ก็ไม่ทัน. `summarize()` ตัด `ok` ออกเสมอ, `warn`/`pause` เตือนเฉพาะ slack < `hr_slack_hours` (default 24) — ถ้าเตือนตาม state เฉยๆ 12 แถวจะยิงซ้ำทุกวัน 5 วันติดจนโดนมองข้าม
- `scraper.fetch_hr_html()` — แยกจาก `_fetch()` เพราะ **myhr.php เสิร์ฟ windows-874 แต่ httpx รายงาน encoding=utf-8** → `resp.text` เป็น mojibake. ต้อง `resp.content.decode("cp874")` (**Python ไม่รู้จักชื่อ `windows-874`** → `LookupError`). หน้า listing เดิม decode ปกติอยู่แล้ว จึงไม่แตะ `_fetch()`
- `scheduler.check_hr()` + job `hr_check` 09:10/21:10 — dedup ด้วย `hr_last_digest` (sha1 ของ set `site_id:state`) ยิงเฉพาะตอน set เปลี่ยน
- `line_notify.notify_hr()` / `telegram_notify.notify_hr()` — body ร่วมจาก `hr.format_message()` แนบ `ระบบเห็นล่าสุด` ต่อไฟล์ (เป็นตัวยืนยันว่า client announce อยู่จริงไหม)
- settings ใหม่ `hr_notify_enabled` / `hr_slack_hours` + toggle ในแท็บตั้งค่า + ปุ่ม "ส่งสรุป H&R เดี๋ยวนี้"
- API: `GET /api/hr`, `POST /api/hr/notify`
- Self-check: `python hr.py` — หน้าเทียม cp874 ครบ 4 state, assert `remaining == target - seeded` (จับ column สลับ) + assert ว่า `ok`/`pause` ไม่เข้า risky

**Verify (บน NAS จริง):** parse myhr.php สด → `17 rows, hit 2, risky 3, seeding 3` ข้อความไทยถูกต้อง ✅ · `POST /api/hr/notify` → `{"ok":true,"total":17,"risky":3,"hits":2,"seeding":3,"sent":true}` ส่งเข้า LINE+Telegram จริง ✅ · เปิด `hr_notify_enabled=1` ไว้บน NAS แล้ว

**Follow-up รอบเดียวกัน (hardening หลัง review):**
- **cross-event-loop:** job cron รันใน thread ของ APScheduler ผ่าน `asyncio.run()` = คนละ loop กับที่สร้าง `scraper._client` → `fetch_hr_html()` attempt 1 ตาย `Event loop is closed` (retry ใน loop ช่วยกู้ได้ แต่กินโควตา retry ฟรีๆ). เพิ่ม `await scraper.relogin()` ต้น `check_hr()` ให้ตรงกับ `_do_scrape()` ที่ทำแบบนี้อยู่แล้ว. **พิสูจน์ด้วย `asyncio.run()` สองรอบซ้อนในคอนเทนเนอร์** (รอบแรก `scraper.init()` รอบสองเรียก fetch) = จำลอง app-loop→scheduler-loop เป๊ะ
- `float(settings.get("hr_slack_hours", 24))` → `float(... or 24)` ทั้งใน `check_hr` และ `/api/hr` — ล้างช่องตัวเลขแล้วกดบันทึกจะเก็บ `""` ไม่ใช่ค่าหาย, `.get` default ไม่ทำงาน, `float("")` โยน แล้วโดน try/except ของ `_hr_job` กลืน = แจ้งเตือนเงียบไปเฉยๆ. verify ด้วยการ PUT ค่าว่างจริงแล้วยิง `/api/hr` (ยังคืน 200) ก่อนคืนค่า 24

**ตั้งใจไม่ทำ:** ไม่ให้ monitor ปิด `auto_download_nas` เองเมื่อใกล้ครบ 18 — เงียบๆ ไปแก้ setting ให้ผู้ใช้ไม่ใช่หน้าที่ตัวเอง แสดงเลข `ผิดแล้ว N/18` ในข้อความแทน. ยังไม่มีแท็บ H&R บน dashboard (มี `/api/hr` รอไว้แล้ว ถ้าอยากได้ค่อยต่อ)

---

## 2026-07-27 — Feature: H&R auto-fix (Telegram confirm) + แจ้งเตือนตอนพ้น H&R

**สิ่งที่ทำ**
- `hr.py`: เพิ่มฟิลด์ `seeding_now` (`"กำลังนับ" in td4`) แยกจาก `last_seen_h=None` — เพราะ None ยังหมายถึง "parse ไม่ได้" ด้วย ถ้าเอา None มาแทน "หลุดแล้ว" วันไหน site เปลี่ยน format จะยิง fix มั่วเงียบๆ. เพิ่ม `fix_candidates()` (state=warn + ไม่ announce + last_seen > stale_h + remaining > 0, เรียงตาม slack, cap) และ `is_cleared()` (seeded >= target)
- `hr_fix.py` (ใหม่): `scan_and_prompt()` ส่ง InlineKeyboard ถาม Telegram (สูงสุด 3 ต่อรอบ), `apply_fix()` re-check row สดก่อนแล้วโหลด .torrent ผ่าน ad-gate เขียนลง `/downloads` (= watch folder `/volume1/homes/<user>/Torrents_Watch` mount อยู่แล้ว ไม่ต้องแก้ compose), `check_cleared()` ยิง LINE+Telegram เมื่อ seed ครบ, `poll_loop()` long-poll getUpdates
- `db.py`: ตาราง `hr_fixes` + settings `hr_autofix_enabled`, `hr_fix_stale_hours`; prompt ค้างเกิน 12 ชม. กลายเป็น `expired` (ปุ่มเก่าห้ามยิงโหลด)
- `scheduler.py`: เรียก `check_cleared()` + `scan_and_prompt()` **ก่อน** บรรทัด dedup `hr_last_digest`
- `main.py`: start poller ใน lifespan; `/api/telegram/get-chat-id` ปฏิเสธเมื่อ poller ทำงาน (getUpdates มี consumer เดียว ชนกันได้ 409 + offset หาย)
- Dashboard: toggle "H&R Auto-fix" + ช่อง "ถือว่าหลุดเมื่อไม่เห็นเกิน (ชม.)"

**กับดักที่เจอ/กันไว้**
- **dedup ฆ่าฟีเจอร์เงียบ:** ถ้าวาง scan ไว้หลัง `if db.get_meta("hr_last_digest") == fingerprint: return` จะไม่เคยรันจริง เพราะ set เสี่ยงนิ่งเป็นวันๆ — ทดสอบด้วย force=True จะผ่าน แต่ production ตายสนิท. ยืนยันของจริง: รอบทดสอบวันนี้ `risky:0` แต่ prompt ยังส่งได้ 3 ใบ = ลำดับถูก
- **callback = trust boundary:** flow นี้เขียนไฟล์ลง NAS ใครก็ยิง callback ใส่บอทได้ ถ้ารู้ชื่อบอท — เช็ค `chat_id == TELEGRAM_CHAT_ID` ทุกครั้ง และปุ่มใช้ได้ครั้งเดียว (`status != pending` = ปฏิเสธ)
- **หายจากหน้า ≠ seed ครบ:** `parse_hr()` คืน `[]` เมื่อ table หาย — `check_cleared()` เลยนับเฉพาะ row ที่ยังอยู่และ `seeded >= target` เท่านั้น
- **re-check ตอนกด:** เวลาระหว่างส่ง prompt กับกดปุ่มอาจหลายชั่วโมง — `apply_fix()` ดึง myhr.php ใหม่ทุกครั้ง ถ้ากลับมา announce เองแล้ว/seed ครบแล้ว จะไม่โหลดซ้ำ

**Verify (บน NAS จริง)**
- `python hr.py` self-check ผ่าน (เพิ่มเคส `กำลังนับอยู่` + stale warn + fully-seeded)
- deploy แล้ว log ขึ้น `[hr_fix] telegram callback poller started`
- เปิด `hr_autofix_enabled=1`, `hr_fix_stale_hours=24` บน NAS แล้ว
- `POST /api/hr/notify` → `{"ok":true,"total":15,"risky":0,"hits":0,"seeding":6}` + log `[hr_fix] 3 auto-fix prompt(s) sent` = prompt เข้า Telegram จริง 3 ใบ
- ตัวเลข risky ลดจาก 3 เหลือ 0 และ seeding เพิ่มจาก 3 เป็น 6 หลัง fix ฝั่ง DSM

**ยังไม่ได้ทำ — ลบ torrent ใน DSM หลังพ้น H&R (ที่ขอไว้)**
ติดของจริง 2 อย่าง: (1) vault ไม่มี DSM API credential เลย มีแต่ `shared.nas.*` (ssh key + sudo password) (2) `sudo -n /usr/syno/bin/synowebapi` บน NAS ตอบ `sudo: a password is required` — passwordless sudo ครอบแค่ `/usr/local/bin/docker`. ต้องรู้ก่อนว่า DS task list ให้ `destination` + key อะไรผูกกับไฟล์จริง (title ล้วนๆ ใช้ตัดสินใจ `rm` ไม่ได้) ค่อยออกแบบ — ทางที่จะไปคือ SSH + paramiko แบบ ops-bot ไม่ใช่ DSM API (CLAUDE.md มีเคส container โดน DSM auto-block)

### 2026-07-27 (รอบ 2) — hardening auto-fix หลัง review

- **ยืนยัน mount จริง**: `docker exec torrentwatch sh -c "echo hi > /downloads/.mount-check"` แล้วเห็นไฟล์ที่ `/volume1/homes/fixhardez/Torrents_Watch/.mount-check` บน host (ลบทิ้งแล้ว) — พิสูจน์ว่า `apply_fix` เขียนลง watch folder จริง ไม่ใช่เขียนลม (ทดสอบด้วยไฟล์ `.torrent` ไม่ได้ เพราะแยกไม่ออกว่า DS ดูดไปหรือ mount พัง)
- **บั๊ก `is_cleared`**: `(row["remaining_h"] or 0) <= 0` ทำให้ `remaining_h=None` (cell parse ไม่ได้) กลายเป็น "seed ครบ" → ยิง noti ผิด. แก้เป็นเช็ค `is not None` ก่อน
- **บั๊ก sort ใน `fix_candidates`**: key `(slack is None, slack)` ถ้ามี 2 แถว slack=None จะเทียบ `None < None` → `TypeError` แล้ว `_hr_job` กลืน exception = รอบ H&R ตายเงียบทั้งรอบ. แก้เป็น `float("inf")`
- **self-check เพิ่ม 3 แถว** (รวม 10): 2 แถว finished parse ไม่ได้ (slack=None ทั้งคู่) + 1 แถว remaining parse ไม่ได้ → คุมทั้งสองบั๊กข้างบน
- **`fixed` ไม่เคย escalate**: ถ้า DS ไม่รับ .torrent (watch folder ปิด / task error) แถวจะค้าง `fixed` ตลอด ไม่ถูกถามซ้ำ (`scan_and_prompt` ข้าม pending/fixed/skipped) แล้วไหลไป `hit`. เพิ่มใน `check_cleared`: `fixed` + ไม่ seeding + `decided_at` เก่ากว่า 24 ชม. → `stalled` (รอบถัดไปถามใหม่)
- **ทดสอบ callback path จริง** (ก่อนหน้านี้ไม่เคยรัน — ปุ่ม 3 อันยังไม่ถูกกด): ยัด row ปลอม `999999999` แล้วเรียก `_handle_callback` ใน container ได้ครบ 3 กรณี → `['ไม่ได้รับอนุญาต', 'ข้ามแล้ว', 'ปุ่มนี้ใช้ไปแล้ว (skipped)']` = chat_id guard ทำงาน, transition pending→skipped ทำงาน, ปุ่มใช้ซ้ำไม่ได้. ลบ row ปลอมออกแล้ว (เหลือ 3 pending ของจริง)
- Deploy: `✔ All done (330s)` · log ยืนยัน `[hr_fix] telegram callback poller started`

**หมายเหตุ deploy**: `deploy.sh` ที่รันแบบ background ผ่าน `&`/`nohup` ตายกลางคัน (log ค้างที่ "Uploading project files") — ต้องรัน foreground พร้อม timeout ยาว


### 2026-07-27 (รอบ 3) — Feature C: ถามลบ torrent หลังพ้น H&R (double confirm)

**สิ่งที่ทำ**
- `dsm.py` ใหม่ — DSM WebAPI client ขั้นต่ำ: login/logout ต่อ operation, `SYNO.DownloadStation.Task list/delete` (v1 **ผ่าน HTTP** ไม่ใช่ CLI), `SYNO.FileStation.List getinfo` + `SYNO.FileStation.Delete`
- `hr_delete.py` ใหม่ — state machine 2 จังหวะ `cleared → del_asked → del_confirm → deleted`
- ต่อเข้า `hr_fix.check_cleared()` (รับ `settings` เพิ่ม) + router `hrdel:` ใน `_handle_callback`
- setting `hr_delete_enabled` (default `"0"`) + toggle ในแดชบอร์ด
- vault keys `stacks.torrentwatch.dsm.{url,username,password}` + manifest → `TORRENTWATCH_DSM_*`

**การค้นพบสำคัญ (แก้ dead end ของรอบก่อน)**
- `synowebapi` CLI เสิร์ฟเฉพาะ core API — `SYNO.DownloadStation.Task` v1 เลย 102 ตลอด และ `DownloadStation2.Task` v2 ไม่คืน `destination`
- **HTTP WebAPI v1 คืน `additional.detail.destination` + `uri`** ครบ → เป็น join key ที่ต้องการ
- `/usr/syno/etc/packages/DownloadStation/download/` ไม่มี task DB (มีแต่ 3 ไฟล์ config) — ทางตัน
- **ไม่ต้อง mount media path เพิ่ม** เพราะ FileStation ลบให้ฝั่ง DSM (ตอนแรกคิดว่าต้อง mount rw + copy pattern ของ dupe-sweeper)
- `SYNO.FileStation.Delete` **ลบถาวร ไม่เข้า #recycle** — ข้อความยืนยันเขียนตามนี้

**กับดักที่เจอ**
- `Dsm._call(self, path, **params)` ชนกับ FileStation param ชื่อ `path` → `TypeError: got multiple values for argument 'path'` แก้เป็น `endpoint`
- python บน workstation เป็น 3.9 รัน self-check ที่ใช้ `dict | None` ไม่ได้ — ต้องรันใน container (3.12)
- `scp` เข้า NAS ตาย (`subsystem request failed`) — ใช้ `tar | ssh` เหมือนเดิม

**ที่ verify แล้ว (read-only ไม่ได้ลบอะไรจริง)**
- `python dsm.py` self-check ผ่านใน container
- login DSM สำเร็จ, list 6 tasks, **ทั้ง 6 ตัว** `task_payload_path()` resolve เป็น real_path ได้จริง (รวมชื่อไทย/CJK/`[ ]`/หลายชั้นโฟลเดอร์)
- dry-run callback ด้วย row ปลอม: `ask` → `del_confirm` (ข้อความโชว์ real path จริง), กดซ้ำ = `ปุ่มนี้ใช้ไปแล้ว (del_confirm)`, `no` → `del_skipped`, `go` หลังยกเลิก = ปฏิเสธ. ลบ row ปลอมทิ้งแล้ว

**ค้างไว้**
- `hr_delete_enabled` ยัง off — เปิดเองในแดชบอร์ดเมื่อพร้อม
- path ลบจริงยังไม่เคยรัน (ตั้งใจ) — จะรันจริงครั้งแรกตอนผู้ใช้กดยืนยันรอบสอง
- DSM account ที่ใช้ = ตัวเดียวกับ homepage widget ตอนนี้มีสิทธิ์ลบไฟล์ผ่าน torrentwatch ด้วย

### 2026-07-27 (รอบ 4) — hardening ทางลบจริง

Review เจอ 4 จุดบนเส้นทาง destructive ที่ dry-run รอบก่อนจับไม่ได้ (เพราะหยุดก่อนกด `go`):

1. **target เป็น snapshot ไม่เคยเช็คซ้ำ** — `_resolve` stat ตอนกดปุ่มแรก แล้ว `_do_delete` ลบตาม path เดิมเลย ไม่มีอะไร expire `del_confirm` (มีแค่ `hr_fix_expire_pending` ที่แตะ `pending`) ปุ่มค้างใน Telegram 3 สัปดาห์ก็ยังยิงได้ → `_do_delete` re-stat ก่อนลบ ถ้า `real_path`/`size` ไม่ตรงกับตอนยืนยัน ตอบ "ไฟล์เปลี่ยนไปจากตอนยืนยัน — ไม่ลบ"
2. **จับแต่ `DsmError`** — `httpx.ReadTimeout` หลุดไปถึง `poll_loop` ที่ `except Exception` แล้วเงียบ สถานะค้าง `del_confirm` ผู้ใช้ไม่เห็นอะไร กดซ้ำได้บนต้นไม้ที่ลบไปครึ่งหนึ่งแล้ว → `_call`/`__aenter__` ห่อ `httpx.HTTPError` เป็น `DsmError`
3. **`FileStation.Delete` เป็น synchronous variant** — โฟลเดอร์หลาย GB เกิน timeout 20s → `_DELETE_TIMEOUT = 300` เฉพาะ call นั้น
4. **408 = ไม่มีไฟล์แล้ว** ถูกรายงานเป็น `del_failed` ทั้งที่ DS อาจลบ payload ไปพร้อม task = สำเร็จอยู่แล้ว → กลืน 408 เท่านั้น error อื่น raise ต่อ

Verify (ไม่ลบอะไรจริง):
- `python /app/dsm.py` → `dsm self-check OK` (self-check เพิ่ม fake `_call` พิสูจน์ 408 กลืน / 407 raise)
- `_do_delete` ยิงจริงบน task ตัวแรกใน DS 2 เคส: size เพี้ยน 1 byte และ path ปลอม → ทั้งคู่ตอบ `(False, 'ไฟล์เปลี่ยนไปจากตอนยืนยัน — ไม่ลบ')` ไม่แตะ `delete_task`/`delete_path`
- settings round-trip: `PUT /api/settings {"hr_delete_enabled":"1"}` → GET คืน `1` → คืนค่าเดิม `0` (ผ่าน basic auth ใน container, app มี middleware เอง ไม่ใช่แค่ nginx)

ยังไม่เคยรันเส้นทางลบจริงสักครั้ง — `hr_delete_enabled` ยัง off default

เช็คเพิ่ม (read-only): stat ซ้ำสองรอบทั้ง 6 task ใน DS ค่าตรงกันหมดรวม payload ที่เป็นโฟลเดอร์ (getinfo คืน size ของ inode ไม่ใช่ recursive จึงนิ่ง) แปลว่า guard ไม่ false-trip ตอนกดยืนยันจริง. เพิ่มข้อความกรณีลบครึ่งทาง (ลบ task สำเร็จ แต่ลบไฟล์พัง) ให้บอก path ที่ต้องไปลบเอง เพราะกดปุ่มซ้ำไม่ได้แล้ว (task หายไปแล้ว)

### 2026-07-27 (รอบ 5) — แท็บ Run Detail ในแดชบอร์ด

โจทย์: "เพิ่ม run detail ใน dashboard ออกแบบให้สวยและมีประโยชน์"

ของเดิมมีแค่ `status()` (last_scrape/next_scrape/progress) ที่เป็น **module global** — deploy ทีนึงหายหมด และ deploy รอบนึงกินเวลา ~500-600s เพราะงั้น run log ต้องลง SQLite ไม่ใช่ขยาย status dict

- `runs` table (`job, started_at, duration_s, ok, summary JSON, error`) + `add_run/get_runs/run_counters/cleanup_old_runs` + `hr_fix_recent`
- `scheduler._record(job, trigger)` contextmanager ครอบ 4 job — วางไว้**ข้างใน** job function ไม่ใช่รอบ `_run_async` เพราะ `_run_async` กลืน exception เป็น `print` (รอบที่ล้มจะไม่เหลือแถว). `_do_scrape` แยกเป็น `_do_scrape` (wrapper) + `_scrape_once(box)`; `check_hr` แยกเป็น wrapper + `_check_hr_once`
- `check_hr` เช็ค `hr_notify_enabled` **ก่อน** เข้า `_record` — ไม่งั้น toggle ปิดไว้จะได้แถว fail ปลอมวันละ 2 แถวกลบของจริง
- retention เกาะ `retention_days` เดิม (floor 14 วัน) ตัดใน `_cleanup_job` 03:00 ไม่เพิ่ม cron
- `GET /api/runs` (หลัง basic auth ไม่ใส่ `_AUTH_BYPASS_PATHS` เพราะเปิด internal ของ scrape)
- แท็บใหม่ "รอบทำงาน": การ์ดสรุป 4 ใบ (รอบ 7 วัน / ล้มเหลว / เฉลี่ยวินาที / รอบถัดไป) + บล็อก **"รอพี่กดใน Telegram"** (hr_fixes ที่ยังเป็น `pending`/`del_asked`/`del_confirm`) + timeline รอบล่าสุดพร้อม chips จาก summary + H&R actions ล่าสุด. ใช้คลาส `tw-stats-*` เดิม เพิ่มแค่ `tw-run-*` (~80 บรรทัด) bump `?v=` ทั้ง css/js

Verify บน NAS: `_record` ทดสอบทั้งเส้นสำเร็จและเส้น raise → ได้ `ok=1 {'trigger':'auto','found':3}` กับ `ok=0 error='RuntimeError: boom'` exception ไม่หลุด (ลบแถว selftest ทิ้งแล้ว); `GET /api/runs` คืน 4 key ครบ; ยิง `POST /api/scrape` จริง ได้แถว `scrape … {'trigger':'manual','sources':2,'found':27,'new':2,'source_errors':0,'rows_today':105,'free_today':1}` 4.8s

ยังไม่ได้เปิดดูหน้าเว็บจริงด้วยตา — โครง HTML/JS ล้อแท็บ "สถิติ" ตัวเดิม

### 2026-07-27 (รอบ 6) — fix แถว H&R ซ้ำใน Run Detail
- `loadRuns()` เดิมโชว์ `hr_fixes` ทั้งชุดในบล็อกล่าง ทำให้รายการที่ยัง `pending`/`del_asked`/`del_confirm` โผล่ทั้งในบล็อก "รอพี่กดใน Telegram" และ "H&R actions ล่าสุด" — แยก `settled` (ตัด `HRFIX_WAITING` ออก) ให้บล็อกล่างใช้
- bump `app.js?v=20260727b`
- ตรวจ `--accent-dim` / `--leech-soft` มี override ใน `[data-theme="dark"]` แล้ว (style.css:83,90) แถว failed/waiting ไม่ขาวในโหมดมืด
- ยังไม่เคยเปิดดูแท็บนี้ในเบราว์เซอร์จริง — รอพี่เปิดดูทั้งโหมดสว่าง/มืด

### 2026-07-27 (รอบ 7) — เวลาในแท็บ Run Detail บังคับ Asia/Bangkok
- ตรวจข้อมูลจริง: `hr_fixes.decided_at` เก็บ `2026-07-27T00:48:53+07:00` (Bangkok ถูกแล้ว), `runs.started_at` เก็บ `2026-07-27 08:31:56` (naive Bangkok)
- ปัญหาอยู่ที่ฝั่งแสดงผล: `slice(5,16)` ตัดสตริงดิบ ได้ `07-27T00:48` — ติด `T` อ่านเหมือน ISO UTC และไม่บังคับ timezone เลย
- เพิ่ม `_fmtWhen()` ใน `app.js`: parse ทั้งสองรูปแบบ (ไม่มี offset = เติม `+07:00`) แล้ว `toLocaleString("en-GB", {timeZone:"Asia/Bangkok"})` ได้ `27/07 00:48` — ตรึงเป็น GMT+7 ไม่ว่าเบราว์เซอร์อยู่โซนไหน หรือ DB จะเก็บ offset อะไรมา
- ใช้ทั้ง `_runRow` และ `_hrFixRow`, bump `app.js?v=20260727c`

### 2026-07-29 (รอบ 8) — แท็บ Hit & Run แสดงสถานะรายไฟล์
- ของที่ขอ (ไฟล์ / โหลดจบเมื่อ / ความคืบหน้า seed / เหลืออีก / ระบบเห็นล่าสุด / สถานะ) มีครบใน `hr.parse_hr()` อยู่แล้ว และ `GET /api/hr` (main.py:391) คืน `rows/risky_ids/hit_count/seeding_count/cap` — งานนี้เลย**ไม่แตะ backend เลย** frontend อย่างเดียว
- panel `#panel-hr` + nav item ที่ 7 (`data-tab="hr"`) + `loadHr()`/`_hrRow()` ใน `app.js` + `if (tab === "hr") loadHr()` ใน `onTabActivate`
- `/api/hr` **scrape myhr.php สด**ทุกครั้งที่เรียก โหลดตอนกดเข้าแท็บกับปุ่ม refresh เท่านั้น ห้ามใส่ `setInterval` (จะยิง bearbit รัวด้วย session ที่ล็อกอินอยู่)
- เรียงตาม `slack_h` น้อยไปมาก (`?? Infinity` ให้แถวที่คำนวณ deadline ไม่ได้ตกไปท้าย) แถวที่อยู่ใน `risky_ids` ใช้คลาส `.waiting` เดิมไฮไลต์ — ค่านี้หน้าต้นฉบับไม่มี เป็นของที่เราคำนวณเอง
- "ระบบเห็นล่าสุด" กับ "สถานะ" ดูซ้ำแต่ไม่ซ้ำ: `seeding_now` = tracker เห็น client ตอนนี้ (โชว์ "กำลังนับอยู่"), `state_label` = 48 ชม. ไปถึงไหน. ของจริง `seeding_now=true` มักมาคู่กับ `last_seen_h=null` เลยต้องเช็ค `seeding_now` ก่อน ไม่งั้นได้ "เห็นล่าสุด ? ชม."
- CSS ใหม่แค่ `.tw-hr-bar/.tw-hr-live/.tw-hr-foot` + media query ย่อ padding nav ที่ <=430px (7 ปุ่มไม่พอดีจอ 375px ที่ padding เดิม) bump `?v=20260729a` ทั้ง css/js
- Verify: `node --check static/app.js` ผ่าน, deploy 11s, ในคอนเทนเนอร์เจอ `loadHr` 3 ครั้ง / `tw-hr-bar` 2 ครั้ง / `app.js?v=20260729a`; `/api/hr` ยิงจริงในคอนเทนเนอร์คืน 5 key ครบ
- ยังไม่ได้เปิดดูด้วยตาในเบราว์เซอร์ (เหมือนแท็บ "รอบทำงาน")

### 2026-07-29 (รอบ 9) — badge คูณ upload/ผู้ปล่อยไฟล์ + ใส่ใน noti

- **`db.sync_stickies` พังเงียบมาตลอด**: `c.rowcount` อ่านจาก Connection (มีแต่ Cursor) → `AttributeError` โยนก่อนถึงลูป refresh/demote และ `scheduler.py:197` กลืนเป็น print. แก้เป็น `cur = c.execute(...)` แล้วอ่าน `cur.rowcount` — sticky ถึงจะ promote/demote จริง
- **คูณ upload มีอยู่แล้ว ไม่ได้พัง**: เช็คหน้าเว็บสด `viewno18sbx.php` คอลัมน์ที่ 4 (`COL_MULTIPLIER`) คืน `x6` ตรงกับที่ DB เก็บ (แถว The First Jasmine site_id 2378834 = `x6`) — badge เดิมโชว์ `x6` แต่หน้าเว็บพิมพ์ `UPLOAD 6X` เลยเพิ่ม `multLabel()` ใน app.js แปลง `x6` → `UPLOAD 6X` ให้ตรงต้นฉบับ. มีแค่ 4 แถวทั้งหน้าที่มีคูณ (ที่เหลือคอลัมน์เป็น `No`) เลยดูเหมือนหาย
- **noti เพิ่ม ผู้ปล่อยไฟล์ + free + คูณ**: `db.badge_text()` ทำสตริงเดียว `👤 u · 🆓 FREE 100% · ⚡ UPLOAD 6X` ใช้ร่วมทุกช่องทาง — `_item()` ใน `line_notify.py`/`telegram_notify.py` (keyword + sticky), `hr.format_message()` (H&R digest), `hr_fix.scan_and_prompt()` (ปุ่ม auto-fix). ว่างทั้งสามค่า = ตัดบรรทัดทิ้ง ไม่ปล่อยบรรทัดเปล่า
- **myhr.php ไม่มีคอลัมน์พวกนี้เลย** — `db.attach_badges(rows)` join กลับตาราง `torrents` ด้วย `site_id` เรียกที่ `scheduler._check_hr_once` + `main.api_hr` จุดเดียวก่อน `summarize` เพื่อให้ทั้ง digest/prompt/แท็บ H&R ได้ข้อมูลชุดเดียวกัน. `hr.py` ยังบริสุทธิ์ (ไม่ import db) แค่พิมพ์ `r["badges"]` ถ้ามี
- ไฟล์ที่ไม่เคยถูก scrape เก็บไว้ = ไม่มี badge (ของจริงตอนนี้ 14/18 แถวมี uploader, free/คูณ ว่างเพราะเป็นแถวเก่า)
- Verify: `python3 db.py` + `python3 hr.py` self-check ผ่านในคอนเทนเนอร์, `attach_badges` บน myhr.php จริงคืน 14/18, `/api/hr` คืน `uploader/free_leech/multiplier` ครบ. bump `?v=20260729b`

### 2026-07-29 (รอบ 9b) — ปิดช่องโหว่ badge lookup + คลุม self-check
- **`badges_by_site_ids` ไม่ deterministic**: `torrents` เป็น `UNIQUE(source_id, site_id)` ไม่ใช่ `UNIQUE(site_id)` — สอง source แชร์ `site_id` เดียวกันได้ แล้ว dict build เก็บแถวที่ planner คืนมาทีหลัง = มีโอกาสแจ้งชื่อผู้ปล่อยไฟล์ผิดใน Telegram. myhr.php ไม่มี `source_id` ให้ filter เลยใส่ `ORDER BY id` ให้แถวใหม่สุดชนะแบบคาดเดาได้
- **`hr.format_message()` บรรทัด badge ไม่เคยรันจริง**: หน้าจริงตอนนั้น risky 0 รายการ เลย branch `badge_line` ไม่โดนแตะ. เพิ่ม assert ใน `hr.py` self-check ยัด `badges` เข้าแถว risky แล้วเช็คว่าบรรทัดโผล่ในตำแหน่งถูก (indent 3 ช่องระหว่างชื่อเรื่องกับบรรทัด seed)
- `hr_fix.apply_fix()` re-parse myhr.php เองโดย**ไม่**เรียก `attach_badges` — ตอนนี้ไม่มีปัญหาเพราะ path นั้นไม่พิมพ์ badge แต่ถ้าจะเพิ่มทีหลังต้อง enrich ก่อน
- Verify: deploy แล้วรัน `python hr.py` + `python db.py` ในคอนเทนเนอร์ ผ่านทั้งคู่

### 2026-07-30 (รอบ 10) — แท็บ H&R โชว์เวลาที่ดึงข้อมูล
- **โจทย์**: สถานะ seed ในแท็บ H&R ไม่บอกว่าข้อมูลเป็นของรอบไหน — `/api/hr` scrape `myhr.php` สดทุกครั้ง แต่ UI ไม่ได้โชว์เวลา
- `main.api_hr` เพิ่ม `fetched_at = datetime.now(_TZ).strftime("%Y-%m-%d %H:%M:%S")` (`_TZ` = Asia/Bangkok มีอยู่แล้วที่ `main.py:139`) — **ห้าม `datetime.now()` เปล่า** ไม่งั้นเป็น UTC แล้วเพี้ยนจาก `อัปเดตล่าสุด` ที่หัว dashboard (ซึ่งมาจาก `scheduler._last_scrape` = `datetime.now(_TZ)`) 7 ชม.
- เก็บวินาทีด้วย ต่างจาก `_last_scrape` ที่ใช้ `%H:%M` — อันนี้อยู่หลังปุ่ม refresh มือ กด 2 ครั้งในนาทีเดียวถ้าเลขไม่ขยับจะอ่านเหมือนปุ่มพัง
- `loadHr()` เรนเดอร์ใน header ของบล็อก "รายไฟล์" (`.tw-hr-fetched` `margin-left:auto` + tabular-nums) ไม่แตะ `index.html` — error path ที่เขียนทับ `hr-content` ทั้งก้อนจึงไม่ค้าง timestamp เก่าเอง. ตั้งใจไม่โชว์ต่อแถว (ค่าเดียวกันทุกแถว) และไม่โชว์เวลารอบ cron 09:10/21:10 (แท็บไม่ได้ใช้ข้อมูลรอบนั้น)
- ตั้งใจใช้คำ "ดึงข้อมูลเมื่อ" เลี่ยงชนกับ "เห็นล่าสุด" ในแถว (ตัวหลังเป็นเวลาที่ tracker เห็น client)
- bump asset `?v=20260730a` (ทั้ง app.js + style.css) ไม่งั้น browser cache JS เดิม
- Verify: deploy `-s torrentwatch` แล้ว curl บน NAS `http://127.0.0.1:5059/api/hr` (basic auth) คืน `"fetched_at":"2026-07-30 12:45:58"` ตรงเวลาไทย

### 2026-07-30 (รอบ 10b) — แท็บ H&R เลือกการเรียงได้
- เดิม `loadHr()` hardcode เรียง `slack_h` น้อยไปมาก. เพิ่ม toolbar `#hr-sort` 4 ปุ่ม (reuse `.tw-sort-group`/`.tw-sort-btn` ของแท็บวันนี้ ไม่ต้องเขียน CSS ใหม่): `slack` (default = ใกล้ครบกำหนดขึ้นก่อน), `remaining` (ขาด seed อีกน้อยสุด), `seen` (ไม่เห็น client นานสุดขึ้นก่อน = `last_seen_h` desc), `finished` (โหลดจบใหม่สุด)
- **สำคัญ: แยก fetch ออกจาก render** — `loadHr()` เก็บผลไว้ที่ `_hrData` แล้วเรียก `_renderHr()`; ปุ่ม sort เรียกแค่ `_renderHr()`. ถ้าให้ปุ่ม sort เรียก `loadHr()` จะ scrape `myhr.php` สดทุกครั้งที่กด (endpoint นี้ไม่แคช) = ยิง tracker รัวๆ ฟรีๆ
- comparator ทุกตัวดัน null ลงล่าง (`?? Infinity` สำหรับ asc, `?? -Infinity` สำหรับ desc) — แถวที่ไม่มี deadline/`last_seen_h` ไม่ควรลอยขึ้นบนสุดแทนแถวที่เสี่ยงจริง. `finished` เทียบ string ตรงๆ ได้เพราะ `finished_at` เป็น `%Y-%m-%d %H:%M`
- `state.sort` เพิ่มคีย์ `hr` (เดิมมี `today`/`history`) — sort ไม่ persist ข้าม reload ตั้งใจ ให้ default กลับเป็นอันที่เสี่ยงสุดเสมอ
- Verify: `node --check static/app.js` ผ่าน, deploy แล้ว curl บน NAS เจอ `HR_SORTS` ใน app.js ที่เสิร์ฟ + `hr-sort` ใน index.html, bump `?v=20260730c`
