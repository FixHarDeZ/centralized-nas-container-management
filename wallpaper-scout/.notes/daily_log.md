# Daily Log — wallpaper-scout

## 2026-07-02 — Multi-source: add booru (yande.re + konachan.net)

**Task:** source เดียว (Wallhaven) → รูปซ้ำ. เพิ่ม source ทางเลือก.

**Probe ก่อนสร้าง (จาก NAS = deploy env จริง, ไม่ใช่ workstation):**
- yande.re → 200 (ไม่ต้อง UA)
- konachan.**com** → 403 Cloudflare "Just a moment"; konachan.**net** → 200 ด้วย browser UA
- reddit → 403 ทุก endpoint (search/subreddit/old.reddit) แม้ browser UA. Reddit ฆ่า unauth API แล้ว → ต้อง OAuth (script app + client_id/secret ใน vault). **Deferred** (ผู้ใช้เลือก "booru now, reddit OAuth later")
- Unsplash/Pexels/Pixabay = ภาพถ่ายล้วน ไม่มี character topics → skip

**สร้าง:** `app/booru.py` (Moebooru, yande.re+konachan.net, `rating:s`, order:score→id map จาก toplist→date_added, client-side aspect/res filter). Source registry `_SOURCES` ใน scheduler. Per-topic `sources` column (JSON, default `["wallhaven"]`, ALTER TABLE migration สำหรับ DB เก่า). Frontend source chips. Namespaced dedup id (`wh` bare / `yr:`/`kc:`) กัน id ชน — filename แทน `:` ด้วย `-`.

**⚠️ db.py ขาด `from __future__ import annotations`** (module อื่นมีหมด) → `list[str] | None` พังบน py<3.10. เพิ่มเข้าไป.

**Live smoke-test (NAS, term "genshin_impact"):** yande.re mobile-fit 30/pc-fit 7, konachan.net pc-fit 32/mobile-fit 0 → complementary, filter ไม่ได้กรองจนเหลือ 0.

**Gotcha:** booru pc floor = 1920×1080 (ไม่ใช่ wallhaven 2560×1440) — corpus booru มี 1440p+ น้อย ถ้าใช้ floor เข้มจะเหลือน้อย. `rating:s` ยังโผล่ tag ล่อแหลม (bikini/cleavage) — SFW-legal แต่ไม่สะอาด, ทำ tag blacklist ทีหลังได้. Idol topics (IU) booru ช่วยไม่ได้ (อนิเมะ/เกมเท่านั้น) — ต้องรอ reddit OAuth.

**Tests:** `test_booru.py` (7) + scheduler multi-source routing/quota/default. รวม 56 passed. **ยังไม่ deploy, ยังไม่ commit.**

## 2026-07-01 — Review mimo handoff + dashboard redesign

**Task:** ตรวจท่าใหม่ (Photos album sync จาก mimo), แก้ให้ robust, redesign dashboard, โชว์ per-purpose ต่อ query

**Review ท่าใหม่ (album sync):** เก็บ feature ไว้ (ผู้ใช้เลือก "keep albums, fix bugs") แต่แก้ 3 จุด:
1. **Host cron อยู่นอก repo** → redeploy NAS ใหม่พังเงียบ. เพิ่ม `host-setup/install-photos-index-touch.sh` (idempotent installer, in-repo) รันครั้งเดียวต่อ NAS: `ssh nas 'sudo bash -s' < wallpaper-scout/host-setup/install-photos-index-touch.sh`. Hardened marker: ย้ายจาก `/tmp` (หายตอน reboot → `find -newer <ไม่มีไฟล์>` error) ไป `/volume1/homes/fixhardez/.wallpaper-last-touch` + init `-t 197001010000` กัน first-run/post-reboot.
2. **ไม่ re-login ตอน session หมด** → album หยุด sync ถาวรเงียบ. เพิ่ม `_AUTH_ERR_CODES={105,106,107,119}` ใน `_api` reconnect ครั้งเดียวแล้ว retry (single retry, ไม่ loop → auto-block risk ต่ำ).
3. **`sync_albums()` inline หลัง download = เปล่าประโยชน์** (ไฟล์ยังไม่ index + race) → ลบทิ้ง เหลือ periodic 5-min job ตัวเดียว.

**หมายเหตุ (honest):** ยัง**ไม่ได้ test** ว่า touch ตัวไหนโหลดแบริ่ง — container `os.utime` หรือ host cron. เก็บไว้ทั้งคู่. ถ้าอนาคต container touch พออย่างเดียว → ลบ cron ได้ (test ต้อง docker exec + eyeball Photos app = sudo/no-TTY friction, payoff ต่ำ เลยเลื่อน).

**Dashboard redesign:**
- Per-purpose ต่อ query: เพิ่ม `db.purpose_counts_by_topic()` (GROUP BY topic_id, purpose, all-time) → attach `counts_by_purpose` ใน `/api/topics`. Dashboard โชว์เป็น chip ต่อ purpose พร้อมยอด (`mobile 12 · pc 8 · best 3`).
- Rewrite `index.html`/`style.css`/`app.js`: จาก table เพลนๆ เป็น card grid + dark theme + accent, form เป็น card, purpose chips, ยอดวันนี้รวมบน topbar, confirm ก่อนลบ.

**Self-check:** `purpose_counts_by_topic` grouping ทดสอบ standalone SQL ผ่าน. Installer + inner script `bash -n` ผ่าน, path bake ถูก.

**ไฟล์ที่แก้:** `app/db.py` `app/main.py` `app/scheduler.py` `app/photos_albums.py` `app/static/{index.html,style.css,app.js}` + ใหม่ `host-setup/install-photos-index-touch.sh`

---

## 2026-07-01 — Synology Photos Album Sync

**Task:** เพิ่ม Synology Photos Normal Album integration ให้ wallpaper-scout

**สิ่งที่ทำ:**
- Research Synology Photos API — พบว่า Condition Albums ไม่รองรับ folder-based filter (รองรับแค่ `{"user_id": N}` ที่รวมทุกรูป)
- ใช้ Normal Albums แทน: สร้าง album ต่อ purpose + `add_item` หลัง download
- เพิ่ม `synology-api` library เข้า requirements.txt
- สร้าง `app/photos_albums.py` — lazy-init DSM session, recursive folder traversal, idempotent sync
- เพิ่ม DSM credentials ใน vault (`stacks.wallpaper_scout.dsm_*`) + manifest
- เพิ่ม `extra_hosts: host.docker.internal:host-gateway` ใน docker-compose.yml (Synology Docker ไม่ resolve `host.docker.internal` โดย default)
- Integrates: `ensure_albums_exist()` on startup, `sync_albums()` after each topic cycle with downloads
- Force touch wallpaper files เพื่อ trigger Synology Photos indexing (files ไม่ถูก index อัตโนมัติ)
- เพิ่ม `os.utime(dest_path, None)` ใน scheduler.py หลัง write_bytes ทุกไฟล์ — ยืนยันแล้วว่าไม่ touch = ไม่ขึ้น album

**ผลลัพธ์:**
- Album "Wallpapers — mobile" (id=15): 30 items synced
- Album "Wallpapers — pc" (id=16): 45 items synced
- ทำงานอัตโนมัติหลัง download cycle ทุกรอบ

**ปัญหาที่พบ:**
1. `host.docker.internal` ไม่ resolve ใน Synology Docker → แก้ด้วย `extra_hosts`
2. Synology Photos ไม่ index ไฟล์อัตโนมัติ → ต้อง touch files เพื่อ trigger (อาจเป็นเพราะ permissions หรือ indexing service delay)
3. Python logging ไม่มี handler สำหรับ custom modules → เพิ่ม StreamHandler ใน photos_albums.py
4. `SYNO.Foto.Browse.Item.list` ไม่รองรับ `album_id` param → ใช้ add_item แบบ idempotent แทน duplicate check

**ไฟล์ที่แก้:**
- `wallpaper-scout/app/photos_albums.py` (new)
- `wallpaper-scout/app/main.py` (+2 lines)
- `wallpaper-scout/app/scheduler.py` (+2 lines)
- `wallpaper-scout/requirements.txt` (+1 line)
- `wallpaper-scout/secrets.manifest.yaml` (+4 keys)
- `wallpaper-scout/docker-compose.yml` (+2 lines)
