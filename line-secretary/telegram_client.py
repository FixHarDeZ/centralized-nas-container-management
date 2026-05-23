import httpx

TELEGRAM_API = "https://api.telegram.org/bot{token}"


def _url(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


async def send(chat_id: str, text: str, token: str, max_len: int = 4096) -> None:
    """Send text to a Telegram chat, splitting if over 4096 chars."""
    if not token or not chat_id:
        return
    chunks = [text[i:i + max_len] for i in range(0, len(text), max_len)]
    async with httpx.AsyncClient(timeout=10) as c:
        for chunk in chunks:
            try:
                resp = await c.post(
                    _url(token, "sendMessage"),
                    json={"chat_id": chat_id, "text": chunk},
                )
                if resp.status_code != 200:
                    print(f"[Telegram] send failed {resp.status_code}: {resp.text[:200]}")
            except Exception as e:
                print(f"[Telegram] send error: {e}")


async def set_webhook(token: str, url: str) -> bool:
    """Register webhook URL with Telegram. Returns True on success."""
    if not token or not url:
        return False
    async with httpx.AsyncClient(timeout=10) as c:
        try:
            resp = await c.post(
                _url(token, "setWebhook"),
                json={"url": url, "allowed_updates": ["message"]},
            )
            data = resp.json()
            if data.get("ok"):
                print(f"[Telegram] webhook registered: {url}")
                return True
            print(f"[Telegram] setWebhook failed: {data.get('description')}")
        except Exception as e:
            print(f"[Telegram] setWebhook error: {e}")
    return False
