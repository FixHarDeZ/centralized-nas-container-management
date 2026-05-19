import base64
import hashlib
import hmac

import httpx

LINE_API = "https://api.line.me/v2/bot"
LINE_DATA_API = "https://api-data.line.me/v2/bot"


def verify_signature(body: bytes, signature: str, channel_secret: str) -> bool:
    computed = base64.b64encode(
        hmac.new(channel_secret.encode(), body, hashlib.sha256).digest()
    ).decode()
    return hmac.compare_digest(computed, signature)


async def download_content(message_id: str, access_token: str) -> bytes:
    """Download binary content (image, etc.) from LINE Content API."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{LINE_DATA_API}/message/{message_id}/content",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30,
        )
        r.raise_for_status()
        return r.content


async def push(user_id: str, text: str, access_token: str) -> None:
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{LINE_API}/message/push",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"to": user_id, "messages": [{"type": "text", "text": text}]},
            timeout=10,
        )
