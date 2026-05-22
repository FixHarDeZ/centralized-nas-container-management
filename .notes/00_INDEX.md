# Project Root — Index

## Overview
Root-level notes สำหรับ cross-stack changes และ project-wide decisions

---

## Environment Variables (`.env`)

| Variable | ค่าปัจจุบัน | ใช้งาน |
|---|---|---|
| `NAS_VOLUME_ROOT` | `/volume1` หรือ `/volume2` | docker container data paths ทุก stack |
| `NAS_MEDIA_ROOT` | `/volume1` | Jellyfin media library paths เท่านั้น |
| `NAS_TARGET_PATH` | `/volumeX/docker` | deploy.sh upload destination |

**การย้าย volume:** แก้ `NAS_VOLUME_ROOT` + `NAS_TARGET_PATH` ใน `.env` แล้ว deploy — ทุก stack ตามอัตโนมัติ  
**การย้ายแค่ media:** แก้ `NAS_MEDIA_ROOT` อย่างเดียว

---

## Stacks ที่ใช้ NAS_VOLUME_ROOT
- `uptime-kuma` — data volume
- `homepage` — volume mount + disk widget (`{{HOMEPAGE_VAR_VOLUME_ROOT}}`)
- `jellyfin` — config/cache volumes

## Stacks ที่ใช้ NAS_MEDIA_ROOT
- `jellyfin` — Movies, Series, Concerts, private_media

## Stacks ที่ไม่ใช้ path variables
- `maid-tracker`, `portainer`, `watchtower`, `line-secretary`, `torrentwatch` — ไม่มี host volume path ที่ขึ้นกับ volume root

---

## Change Log
| วันที่ | เรื่อง |
|---|---|
| 2026-05-22 | เพิ่ม NAS_VOLUME_ROOT / NAS_MEDIA_ROOT — replace hardcoded /volume1 ทั้ง project |
