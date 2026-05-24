# my-secretary: Telegram Support Design

**Date:** 2026-05-24  
**Stack:** `my-secretary/`  
**Status:** Approved

---

## Goal

Add Telegram bot support to my-secretary so it responds to messages on Telegram with the same AI + Notion capabilities as LINE. State (history, pending) is isolated per platform — LINE and Telegram are independent sessions.

---

## Architecture

```
LINE:      POST /webhook           → verify X-Line-Signature   → handle_message("U{id}",  text, line_push_fn)
Telegram:  POST /webhook/telegram  → verify X-Telegram-Bot-Api-Secret-Token → handle_message("tg_{chat_id}", text, tg_push_fn)
```

Both routes share the same `handle_message()` and `handle_non_text_message()` core logic. Platform differences are encapsulated in the `push_fn` callback and user_id namespace.

---

## File Changes

### `telegram_client.py` (new)

- `send_message(chat_id: int, text: str, token: str) -> None`  
  POST to `https://api.telegram.org/bot{token}/sendMessage`. Splits text at 4096 chars (Telegram limit).
- `register_webhook(token: str, url: str, secret_token: str) -> None`  
  POST to `setWebhook` with `url`, `secret_token`, and `allowed_updates=["message"]`.

### `config.py`

Add three new optional settings read from env:
- `TELEGRAM_BOT_TOKEN` — bot token; if empty, Telegram is disabled
- `TELEGRAM_WEBHOOK_URL` — full HTTPS URL Telegram will POST to (e.g. `https://<NAS_HOST>:8443/webhook/telegram`)
- `TELEGRAM_ALLOWED_CHAT_IDS` — comma-separated chat IDs; if empty, all chats accepted (not recommended)

### `main.py`

**Refactor `handle_message` and `handle_non_text_message`:**  
Replace all direct `line_client.push(user_id, ..., token)` calls with `await push_fn(text)`.  
New signatures:
```python
async def handle_message(user_id: str, text: str, push_fn) -> None
async def handle_non_text_message(user_id: str, msg_type: str, push_fn) -> None
```

**LINE webhook** (`POST /webhook`) extracts user_id/text from the event and calls:
```python
push_fn = lambda t: line_client.push(user_id, t, token)
await handle_message(user_id, text, push_fn)
```

**Telegram webhook** (`POST /webhook/telegram`, new):
- Validate `X-Telegram-Bot-Api-Secret-Token` header against `settings.TELEGRAM_WEBHOOK_SECRET`
- Extract `message.chat.id` and `message.text` from the Telegram update JSON
- Ignore updates with no `message` or no `text` (silently return 200)
- Check `str(chat_id)` against `settings.telegram_allowed_chat_ids`
- Build `push_fn = lambda t: telegram_client.send_message(chat_id, t, token)`
- Call `handle_message(f"tg_{chat_id}", text, push_fn)`

**Lifespan** (startup):  
If `TELEGRAM_BOT_TOKEN` and `TELEGRAM_WEBHOOK_URL` are both set, call `telegram_client.register_webhook(...)`. Log success or failure — do not crash if registration fails (bot still starts).

### `.env.example`

Add Telegram section with placeholder values.

---

## State Isolation

Store keys:
- LINE users: `U{LINE_user_id}` (unchanged)
- Telegram users: `tg_{chat_id}` (e.g. `tg_8663614341`)

All store operations (pending, pending_general, pending_note, history) use the namespaced user_id. No cross-platform sharing.

---

## Limitations (out of scope this iteration)

- Telegram image messages: respond "รับแค่ข้อความค่ะ" — no Notion upload
- Telegram inline keyboards / stickers: silently ignored (no `message.text`)
- Multiple Telegram accounts: all keyed by chat_id; no per-account profile

---

## Security

- Webhook validated via `X-Telegram-Bot-Api-Secret-Token` header (set in `setWebhook` call)
- Allowed chat IDs whitelist in env (same pattern as `LINE_SECRETARY_ALLOWED_USER_IDS`)
- Token never logged

---

## Testing

- Unit: `telegram_client.send_message` splits long text correctly
- Unit: Telegram webhook endpoint rejects missing/wrong secret header (400)
- Unit: unknown chat_id is silently ignored
- Integration: send a test message via Telegram → bot replies (manual on NAS)
