import httpx

TELEGRAM_API = "https://api.telegram.org"


async def send_message(chat_id: int, text: str, token: str) -> None:
    async with httpx.AsyncClient() as client:
        for i in range(0, len(text), 4096):
            await client.post(
                f"{TELEGRAM_API}/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text[i:i + 4096]},
                timeout=10,
            )


async def register_webhook(token: str, url: str, secret_token: str) -> None:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{TELEGRAM_API}/bot{token}/setWebhook",
            json={
                "url": url,
                "secret_token": secret_token,
                "allowed_updates": ["message"],
            },
            timeout=15,
        )
        r.raise_for_status()
