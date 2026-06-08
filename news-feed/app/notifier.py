import logging
import os

import httpx

logger = logging.getLogger(__name__)


def _format_digest(articles: list[dict]) -> str:
    lines = ["📰 *ข่าวเทคโนโลยี/AI ล่าสุด*\n"]
    for i, a in enumerate(articles, 1):
        lines.append(f"{i}. <b>{a['title']}</b>")
        if a.get("summary_th"):
            lines.append(f"   {a['summary_th']}")
        lines.append(f"   🔗 {a['url']}\n")
    return "\n".join(lines)


def _send_line(message: str) -> bool:
    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
    user_id = os.getenv("LINE_USER_ID", "")
    if not token or not user_id:
        logger.warning("LINE credentials not set, skipping")
        return False
    try:
        resp = httpx.post(
            "https://api.line.me/v2/bot/message/push",
            headers={"Authorization": f"Bearer {token}"},
            json={"to": user_id, "messages": [{"type": "text", "text": message}]},
            timeout=15.0,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:
        logger.error("LINE send failed: %s", exc)
        return False


def _send_telegram(message: str) -> bool:
    token = os.getenv("NEWS_FEED_TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        logger.warning("Telegram credentials not set, skipping")
        return False
    try:
        resp = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            timeout=15.0,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:
        logger.error("Telegram send failed: %s", exc)
        return False


def send_summarizer_alert(config: dict) -> list[str]:
    message = (
        "⚠️ <b>News Feed: Summarizer Alert</b>\n\n"
        "Digest 2 รอบติดกันไม่มีบทความที่ส่งได้ ทั้งที่มีข่าวในระบบ\n"
        "Summarizer น่าจะมีปัญหา\n\n"
        "<b>วิธีตรวจสอบ:</b>\n"
        "1. ดู provider ใน Schedule Config (อาจ override .env)\n"
        "2. ทดสอบ API key ตรงๆ\n"
        "3. POST /api/digest/test → ดู candidates_in_window"
    )
    sent = []
    if _send_line(message):
        sent.append("line")
    if _send_telegram(message):
        sent.append("telegram")
    return sent


def send_digest(articles: list[dict], config: dict) -> list[str]:
    if not articles:
        logger.info("no articles for digest, skipping")
        return []
    message = _format_digest(articles)
    sent = []
    if _send_line(message):
        sent.append("line")
    if _send_telegram(message):
        sent.append("telegram")
    return sent
