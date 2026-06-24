# watchtower Stack — Index

**Port:** — (no web layer)
**Status:** Running (auto-update + LINE/Telegram notify sidecar)

## Architecture

- `watchtower` (containrrr/watchtower) auto-updates containers; ติดป้าย
  `com.centurylinklabs.watchtower.enable=false` กับตัวเองเพื่อไม่ให้อัปเดตตัวเอง.
- `watchtower-notifier` sidecar (Python 3.12-slim) อ่าน Docker socket แบบ raw `socket`
  (ไม่ใช้ docker CLI/requests) แล้วส่งสรุปการอัปเดตเข้า LINE + Telegram.

## Env (notifier)

`WATCHTOWER_LINE_CHANNEL_ACCESS_TOKEN`, `WATCHTOWER_LINE_USER_ID`,
`WATCHTOWER_TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — ทุกตัว required (KeyError ตอน import ถ้าขาด).

## Notifier (2026-06-24)

ส่ง LINE/Telegram ผ่าน shared `Notifier` (`shared/notify.py`, stdlib `urllib`, vendored =
`notifier/notify.py` ผ่าน `make sync-shared`). `notifier.py` มี `_notifier` ระดับ module +
`notify(text)` delegate. ตัด `requests` แล้ว (เหลือ `tzdata` ใน requirements). แก้ shared module
ต้อง `make sync-shared`. ดู daily_log 2026-06-24.
