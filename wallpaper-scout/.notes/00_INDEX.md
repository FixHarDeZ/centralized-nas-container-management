# Wallpaper Scout — Project Index (Memory Blueprint)

> อัปเดตล่าสุด: 2026-07-02 (multi-source: เพิ่ม booru — yande.re + konachan.net)
> ใช้ไฟล์นี้เป็น cold-start memory ก่อนเริ่มงานทุกครั้ง

## Overview

FastAPI stack ที่ให้ผู้ใช้ลงทะเบียน "topic" (คำค้น เช่น "IU", "Wuthering Waves") พร้อมระบุ purpose (mobile/pc wallpaper) + source(s), scrape รูปจากหลาย source (SFW only) ตาม preset สัดส่วน/ความละเอียด เขียนไฟล์ตรงเข้า `/volume1/homes/fixhardez/Photos/wallpapers/<purpose>/<topic>/` ให้ Synology Photos auto-index + sync เข้า Normal Albums อัตโนมัติ

## Sources (per-topic multi-select, default `["wallhaven"]`)

- **wallhaven** — real people/idols, photographic. Server-side ratio+res filter. Default.
- **booru** (`app/booru.py`) — anime/game. yande.re + konachan.**net** (Moebooru, `rating:s`). **konachan.com = Cloudflare 403 → ใช้ .net + browser UA**. Client-side filter (pc floor 1920×1080, mobile 1080×1920 — booru corpus มี 1440p+ น้อย). yande.re เอียง portrait/mobile, konachan เอียง landscape/pc. `rating:s` ยังโผล่ tag ล่อแหลม.
- **reddit** (`app/reddit.py`) — idol/คนจริง. OAuth **userless** (`grant_type=client_credentials`, HTTP-Basic client_id:secret → bearer, ไม่เก็บ user password). Token cache module-level. Global search `oauth.reddit.com/search` (`raw_json=1`, `include_over_18=off` + skip over_18, filter res/orientation เหมือน booru). id = `rd:`. คืน `[]` ถ้า creds ไม่ตั้ง. Vault: `stacks.wallpaper_scout.reddit.{client_id,client_secret}`. **⏳ pending: register app + vault creds + live-probe idol search quality** (global search อาจ noisy).
- **Dedup id namespaced:** wallhaven = bare id, booru = `yr:`/`kc:` prefix. `:` → `-` ใน filename. `max_new_per_cycle` = cap รวมต่อ purpose เติมตาม source list order.

## Tech Stack

| Component | Detail |
|---|---|
| Runtime | Python 3.12 · FastAPI · Uvicorn |
| Database | SQLite — `/data/wallpaper-scout.db` |
| Image sources | Wallhaven (`api/v1/search`) + booru (`app/booru.py`: yande.re + konachan.net Moebooru). reddit deferred. See Sources section above. |
| LLM | MiMo (`xiaomi/mimo-v2.5`) primary, Anthropic (`claude-sonnet-4-6`) fallback — text-only alias expansion, no vision |
| Scheduler | APScheduler `BackgroundScheduler` — one `IntervalTrigger` job per topic + one daily `CronTrigger` summary job |
| Frontend | Vanilla JS SPA |
| Auth | Nginx Basic Auth sidecar (LAN-only, no public HTTPS proxy — no inbound webhook needed) |
| Notifications | Telegram only — reuses `news-feed`'s bot/chat (`stacks.news_feed.telegram.*` vault keys), no separate wallpaper-scout bot |
| Photos sync | `synology-api` library → Synology Photos API via `host.docker.internal:5000`. Creates Normal Albums per purpose ("Wallpapers — mobile", "Wallpapers — pc"), syncs items after each download cycle + on startup. DSM credentials in vault (`stacks.wallpaper_scout.dsm_*`). Container needs `extra_hosts: host.docker.internal:host-gateway` in docker-compose. |

## Ports

| Context | Port |
|---|---|
| Container internal | `8000` |
| NAS host (LAN) | `5067` |

## Key design decisions

- **Dedup:** exact Wallhaven-ID only, `UNIQUE(topic_id, purpose, wallhaven_id)` in SQLite. No perceptual hashing.
- **Sort:** `toplist` once per topic (first cycle, `backfilled=0`), then `date_added` forever after — `toplist` is near-static and would starve a recurring scrape of new results.
- **Purpose presets are hardcoded**, not user-configurable: `mobile` (portrait, ≥1080x1920), `pc` (16:9/21:9/32:9, ≥2560x1440). (`laptop` was removed from `PURPOSE_PRESETS` after the initial build — existing topics with stale `"laptop"` in their `purposes` list are skipped with a warning at cycle time, not migrated in the DB.)
- **Synology Photos API** — used for album management only (Normal Albums). Login via `synology-api` library to DSM HTTP port 5000 via `host.docker.internal`. Condition Albums don't support folder-based filtering via API, so Normal Albums with `add_item` are used instead. Session is lazy-initialized on first use, not per-request.
- **⚠️ Synology Photos ไม่ auto-index ไฟล์จาก container** — มี touch สองชั้น: (1) container `os.utime(dest_path, None)` + parent dirs หลัง write_bytes, (2) host-side cron ทุก 2 นาที. **ยังไม่ได้ test ว่าตัวไหนโหลดแบริ่ง** — เก็บไว้ทั้งคู่. Host cron ติดตั้งผ่าน `host-setup/install-photos-index-touch.sh` (in-repo, idempotent, รันครั้งเดียวต่อ NAS ด้วย sudo) — **ห้ามพึ่ง state นอก repo**: `/usr/local/bin/touch-wallpapers.sh` + `/etc/cron.d/touch-wallpapers` ไม่อยู่ใน `deploy.sh` tar, redeploy NAS ใหม่ต้องรัน installer ซ้ำ. Marker อยู่ `/volume1/homes/fixhardez/.wallpaper-last-touch` (survive reboot).
- **Album sync re-login:** `photos_albums._api` ตรวจ `_AUTH_ERR_CODES={105,106,107,119}` → reconnect ครั้งเดียว + retry (single retry, ไม่ loop, auto-block risk ต่ำ). ก่อนหน้านี้ session ตายแล้ว album หยุด sync ถาวรเงียบ.
- **ไม่ sync_albums() inline หลัง download** — ไฟล์ยังไม่ index (race) → sync เห็น 0. ใช้ periodic job ตัวเดียว (ทุก 2 นาที, match cron cadence → Scout ใหม่เข้า album ใน ~2-4 นาที).
- **Per-purpose counts:** `db.purpose_counts_by_topic()` (GROUP BY topic_id, purpose, all-time) → `/api/topics` แนบ `counts_by_purpose` → dashboard โชว์ chip ต่อ purpose ว่ารูปลง purpose ไหนของแต่ละ query.
- **Retention:** keep forever, no cleanup job (unlike torrentwatch's 7-day inbox retention — this is a keep collection, not a transient inbox).
- **`/data` and `/photos_root` are both bind mounts, not named volumes** — the container runs as `fixhardez`'s dynamically-looked-up uid/gid, and a fresh named volume would be owned by root at creation (no baked-in Dockerfile uid to chown to), breaking SQLite writes at startup.
- **`schedule_topic()` passes `next_run_time=datetime.now(_TZ)`** on job creation — `IntervalTrigger`'s default first fire is `now + interval`, which would otherwise leave a freshly created topic showing zero images for up to a full day.

## Gaps / TODOs

- `nginx/.htpasswd` created manually, not via vault (`htpasswd -c nginx/.htpasswd <user>`).
- Celebrity/people topic coverage on Wallhaven not yet smoke-tested against the live API — first few days of real usage should confirm whether e.g. "IU" returns enough SFW+portrait results to be useful.
- Perceptual-hash near-dup detection deferred — revisit only if exact-ID dedup proves insufficient in practice.
- Quota (`max_new_per_cycle`) is enforced per-purpose, not per-topic-cycle-total — a topic with 2 purposes can download up to 2x the configured cap in one cycle. Intentional design or oversight — worth a human call if cap-hit precision matters.
- `mark_backfilled` fires even if a cycle's downloads all failed (e.g. CDN outage) — could permanently skip the one-time toplist backfill for that topic.
