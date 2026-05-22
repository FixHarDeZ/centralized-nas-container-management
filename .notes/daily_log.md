# Daily Log

---

## 2026-05-22 — Centralise NAS volume root paths via env vars

### งานที่ทำ
- เพิ่ม `NAS_VOLUME_ROOT` และ `NAS_MEDIA_ROOT` ใน `.env` และ `.env.example`
- Replace hardcoded `/volume1` ใน compose files ทุกตัวด้วย `${NAS_VOLUME_ROOT}`
- แยก Jellyfin media paths ออกมาใช้ `${NAS_MEDIA_ROOT}` แทน เพราะอาจย้าย volume แยกกัน
- Homepage disk monitor widget ใช้ `{{HOMEPAGE_VAR_VOLUME_ROOT}}` ผ่าน Homepage's own substitution system
- ทดสอบด้วย `docker compose --env-file ../.env config` ทุก stack — interpolate ถูกต้องทั้งหมด
- ผู้ใช้ทดสอบจริงโดยเปลี่ยน `.env` เป็น `NAS_VOLUME_ROOT=/volume2` — ทำงานได้ทันที

### ไฟล์ที่เปลี่ยน
- `.env` — เพิ่ม `NAS_VOLUME_ROOT`, `NAS_MEDIA_ROOT`
- `.env.example` — เพิ่ม `NAS_VOLUME_ROOT`, `NAS_MEDIA_ROOT`
- `uptime-kuma/docker-compose.yml` — 1 volume line
- `homepage/docker-compose.yml` — 1 volume line + `HOMEPAGE_VAR_VOLUME_ROOT` env
- `jellyfin/docker-compose.yml` — 6 volume lines (config/cache ใช้ NAS_VOLUME_ROOT, media ใช้ NAS_MEDIA_ROOT)
- `homepage/config/widgets.yaml` — disk monitor ใช้ `{{HOMEPAGE_VAR_VOLUME_ROOT}}`

### Commits
- `9bfd6a8` refactor: centralise NAS volume root path via NAS_VOLUME_ROOT env var
- `4c2f2f0` refactor(jellyfin): split media paths to NAS_MEDIA_ROOT env var

### วิธีย้าย volume ในอนาคต
แก้ `.env` แค่ 2-3 บรรทัด แล้ว deploy:
```
NAS_VOLUME_ROOT=/volume2        # docker container data
NAS_MEDIA_ROOT=/volume1         # media library (อาจคงไว้หรือย้ายแยก)
NAS_TARGET_PATH=/volume2/docker # deploy destination
```
