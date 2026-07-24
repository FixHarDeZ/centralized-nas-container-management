# ops-bot/app/telegram_bot.py
import logging
from datetime import datetime
from typing import Optional

import httpx

from app.config import get_config
from app.llm_client import LLMAnalysis

logger = logging.getLogger(__name__)

SEVERITY_EMOJI = {
    "critical": "🔴",
    "warning": "🟡",
    "info": "🔵",
}

SEVERITY_THAI = {
    "critical": "วิกฤต",
    "warning": "เตือน",
    "info": "ข้อมูล",
}


def format_incident_message(
    service_name: str,
    analysis: LLMAnalysis,
    diagnostic_results: dict[str, str],
) -> str:
    severity_emoji = SEVERITY_EMOJI.get(analysis.severity, "⚪")
    severity_thai = SEVERITY_THAI.get(analysis.severity, analysis.severity)

    # Extract key diagnostic info for summary
    container_info = diagnostic_results.get("container_status", "")[:300]
    resources_info = diagnostic_results.get("system_resources", "")[:200]

    msg = (
        f"🤖 **แจ้งเตือน: {service_name} ล่ม!**\n"
        f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"{severity_emoji} ระดับ: {severity_thai}\n\n"
        f"🔍 **Root Cause:** {analysis.root_cause}\n\n"
        f"💡 **แนะนำ:** {analysis.suggested_fix}\n\n"
        f"⚠️ **{analysis.safety_note}**\n\n"
        f"📊 **ข้อมูล diagnostic:**\n"
        f"```\n{container_info}\n```"
    )

    return msg


def _build_inline_keyboard(incident_id: int, analysis: LLMAnalysis) -> dict:
    buttons = []

    buttons.append({
        "text": "📋 ดู Logs เพิ่มเติม",
        "callback_data": f"logs:{incident_id}",
    })

    return {"inline_keyboard": [buttons]}


class TelegramBot:
    def __init__(self):
        cfg = get_config()
        self.token = cfg.telegram_bot_token
        self.chat_id = cfg.telegram_chat_id
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    async def send_message(self, text: str, reply_markup: Optional[dict] = None) -> dict:
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{self.base_url}/sendMessage", json=payload)
            if resp.status_code != 200:
                logger.error(f"Telegram send failed ({resp.status_code}), retrying without Markdown")
                payload.pop("parse_mode", None)
                resp = await client.post(f"{self.base_url}/sendMessage", json=payload)
            if resp.status_code != 200:
                logger.error(f"Telegram send failed again: {resp.status_code} — {resp.text[:200]}")
                return {"ok": False}
            return resp.json()

    async def send_incident_report(
        self,
        service_name: str,
        analysis: LLMAnalysis,
        diagnostic_results: dict[str, str],
        incident_id: int,
    ) -> None:
        msg = format_incident_message(service_name, analysis, diagnostic_results)
        keyboard = _build_inline_keyboard(incident_id, analysis)
        await self.send_message(msg, reply_markup=keyboard)

    async def send_fix_confirmation(
        self, incident_id: int, action_type: str, result: str, success: bool
    ) -> None:
        status = "✅ สำเร็จ" if success else "❌ ล้มเหลว"
        msg = f"{status} — {action_type}\n\n```\n{result[:500]}\n```"
        await self.send_message(msg)

    async def answer_callback(self, callback_query_id: str, text: str) -> None:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{self.base_url}/answerCallbackQuery",
                json={"callback_query_id": callback_query_id, "text": text},
            )

    async def send_recovery_notification(self, service_name: str) -> None:
        msg = (
            f"🟢 **{service_name} กลับมาทำงานปกติแล้ว!**\n"
            f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        await self.send_message(msg)


_telegram_bot: Optional[TelegramBot] = None


def get_telegram_bot() -> TelegramBot:
    global _telegram_bot
    if _telegram_bot is None:
        _telegram_bot = TelegramBot()
    return _telegram_bot
