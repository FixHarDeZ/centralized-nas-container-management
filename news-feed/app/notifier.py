import logging
import os

from .notify import LineCreds, Notifier, TgCreds

logger = logging.getLogger(__name__)


def _notifier() -> Notifier:
    return Notifier(
        line=LineCreds(
            os.getenv("LINE_CHANNEL_ACCESS_TOKEN", ""),
            os.getenv("LINE_USER_ID", ""),
        ),
        telegram=TgCreds(
            os.getenv("NEWS_FEED_TELEGRAM_BOT_TOKEN", ""),
            os.getenv("TELEGRAM_CHAT_ID", ""),
            parse_mode="HTML",
        ),
    )


def _format_digest(articles: list[dict]) -> str:
    lines = ["📰 *ข่าวเทคโนโลยี/AI ล่าสุด*\n"]
    for i, a in enumerate(articles, 1):
        lines.append(f"{i}. <b>{a['title']}</b>")
        if a.get("summary_th"):
            lines.append(f"   {a['summary_th']}")
        lines.append(f"   🔗 {a['url']}\n")
    return "\n".join(lines)


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
    return _notifier().send(message)


def send_digest(articles: list[dict], config: dict) -> list[str]:
    if not articles:
        logger.info("no articles for digest, skipping")
        return []
    return _notifier().send(_format_digest(articles))
