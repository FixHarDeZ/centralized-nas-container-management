# Wallpaper Scout — Project Index (Memory Blueprint)

> อัปเดตล่าสุด: 2026-07-01 (initial build)
> ใช้ไฟล์นี้เป็น cold-start memory ก่อนเริ่มงานทุกครั้ง

## Overview

FastAPI stack ที่ให้ผู้ใช้ลงทะเบียน "topic" (คำค้น เช่น "IU", "Wuthering Waves") พร้อมระบุ purpose (mobile/laptop/pc wallpaper), scrape รูปจาก Wallhaven API (SFW only) ตาม preset สัดส่วน/ความละเอียดคงที่ เขียนไฟล์ตรงเข้า `/volume1/homes/fixhardez/Photos/wallpapers/<purpose>/<topic>/` ให้ Synology Photos auto-index (ไม่ใช้ DSM Photos API เลย)

## Tech Stack

| Component | Detail |
|---|---|
| Runtime | Python 3.12 · FastAPI · Uvicorn |
| Database | SQLite — `/data/wallpaper-scout.db` |
| Image source | Wallhaven public API (`https://wallhaven.cc/api/v1/search`) |
| LLM | MiMo (`xiaomi/mimo-v2.5`) primary, Anthropic (`claude-sonnet-4-6`) fallback — text-only alias expansion, no vision |
| Scheduler | APScheduler `BackgroundScheduler` — one `IntervalTrigger` job per topic + one daily `CronTrigger` summary job |
| Frontend | Vanilla JS SPA |
| Auth | Nginx Basic Auth sidecar (LAN-only, no public HTTPS proxy — no inbound webhook needed) |
| Notifications | Telegram only — reuses `news-feed`'s bot/chat (`stacks.news_feed.telegram.*` vault keys), no separate wallpaper-scout bot |

## Ports

| Context | Port |
|---|---|
| Container internal | `8000` |
| NAS host (LAN) | `5067` |

## Key design decisions

- **Dedup:** exact Wallhaven-ID only, `UNIQUE(topic_id, purpose, wallhaven_id)` in SQLite. No perceptual hashing.
- **Sort:** `toplist` once per topic (first cycle, `backfilled=0`), then `date_added` forever after — `toplist` is near-static and would starve a recurring scrape of new results.
- **Purpose presets are hardcoded**, not user-configurable: `mobile` (portrait, ≥1080x1920), `laptop` (16:9/16:10, ≥1920x1080), `pc` (16:9/21:9/32:9, ≥2560x1440).
- **No DSM Photos API** — plain filesystem writes only, to avoid the DSM auto-block gotcha documented in root `CLAUDE.md`. Container `user:` must match host `fixhardez` UID/GID or synofoto won't index the files.
- **Retention:** keep forever, no cleanup job (unlike torrentwatch's 7-day inbox retention — this is a keep collection, not a transient inbox).
- **`/data` and `/photos_root` are both bind mounts, not named volumes** — the container runs as `fixhardez`'s dynamically-looked-up uid/gid, and a fresh named volume would be owned by root at creation (no baked-in Dockerfile uid to chown to), breaking SQLite writes at startup.
- **`schedule_topic()` passes `next_run_time=datetime.now(_TZ)`** on job creation — `IntervalTrigger`'s default first fire is `now + interval`, which would otherwise leave a freshly created topic showing zero images for up to a full day.

## Gaps / TODOs

- `nginx/.htpasswd` created manually, not via vault (`htpasswd -c nginx/.htpasswd <user>`).
- Celebrity/people topic coverage on Wallhaven not yet smoke-tested against the live API — first few days of real usage should confirm whether e.g. "IU" returns enough SFW+portrait results to be useful.
- Perceptual-hash near-dup detection deferred — revisit only if exact-ID dedup proves insufficient in practice.
- Quota (`max_new_per_cycle`) is enforced per-purpose, not per-topic-cycle-total — a topic with 2 purposes can download up to 2x the configured cap in one cycle. Intentional design or oversight — worth a human call if cap-hit precision matters.
- `mark_backfilled` fires even if a cycle's downloads all failed (e.g. CDN outage) — could permanently skip the one-time toplist backfill for that topic.
