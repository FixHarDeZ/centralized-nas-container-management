import base64
import hashlib
import hmac

import httpx

LINE_API = "https://api.line.me/v2/bot"


def verify_signature(body: bytes, signature: str, channel_secret: str) -> bool:
    computed = base64.b64encode(
        hmac.new(channel_secret.encode(), body, hashlib.sha256).digest()
    ).decode()
    return hmac.compare_digest(computed, signature)


async def push(user_id: str, text: str, access_token: str) -> None:
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{LINE_API}/message/push",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"to": user_id, "messages": [{"type": "text", "text": text}]},
            timeout=10,
        )
